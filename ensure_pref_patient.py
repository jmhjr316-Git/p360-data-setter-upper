#!/usr/bin/env python3
"""
Ensure a preference-management-searchable test patient exists.

The Preference Management UI search requires BOTH:
  1. A P360 patient document (DocumentDB)
  2. A preference record (PostgreSQL preference DB) with the phone as constituenturn

QA data gets wiped frequently, so automation should call this before any
pref management test that searches for a patient.

Usage:
    python3 ensure_pref_patient.py --env qa --client 5011 --phone 7249148327
    python3 ensure_pref_patient.py --env staging --client 9001 --phone 7249148327

    # With specific state for PC-28070 tests:
    python3 ensure_pref_patient.py --env staging --client 9001 --phone 7249148399 --unreachable
    python3 ensure_pref_patient.py --env staging --client 9001 --phone 7249148400 --dnc
"""
import argparse
import sys
import uuid
import psycopg2

sys.path.insert(0, '/mnt/c/Code/Data_setter_upper')
from tests.helpers_p360 import set_environment, ensure_patient, get_patient, close

# Preference DB connection info per environment
PREF_DB = {
    "qa": {
        "host": "pcrdsqa.cxa8jqblcefj.us-east-2.rds.amazonaws.com",
        "dbname": "preference",
        "user": "preference1",
        "password": "preference1",
    },
    "staging": {
        "host": "pcrdsstg.cmf55ybhwikl.us-east-2.rds.amazonaws.com",
        "dbname": "preference",
        "user": "preference1",
        "password": "preference1",
    },
}


def format_urn(phone: str) -> str:
    """Normalize a 10-digit phone to urn:TEL:+1XXXXXXXXXX."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return f"urn:TEL:+{digits}"


def ensure_preference_record(env: str, client_id: int, phone: str,
                             unreachable: bool = False, dnc: bool = False) -> None:
    """Insert a CONTACT_OPT_IN preference record if one doesn't exist."""
    cfg = PREF_DB[env]
    urn = format_urn(phone)

    status = "ACCEPTED"
    if dnc:
        status = "DO_NOT_CONTACT"

    # Build the contactOptInDetails entry. unreachableNumber and stopRequested
    # live INSIDE the channel detail (matching how bot-sms-channel writes them).
    detail = {
        "sender": "+19195517322",
        "status": status,
        "channel": "SMS",
        "attempts": 1,
        "disconnected": False,
        "stopRequested": bool(dnc),
        "lastModifiedBy": "system bot-sms-channel",
        "lastModifiedDate": "2026-08-20T11:53:42.197011243",
    }
    if unreachable:
        detail["unreachableNumber"] = True

    attrs = {
        "feature": "CONTACT_OPT_IN",
        "program": "OCP",
        "preferenceType": "PROGRAM_FEATURE",
        "preferenceSubType": "CONTACT_OPT_IN",
        "contactOptInDetails": [detail],
    }

    import json
    attrs_json = json.dumps(attrs)

    conn = psycopg2.connect(
        host=cfg["host"], dbname=cfg["dbname"],
        user=cfg["user"], password=cfg["password"],
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Check if a record already exists
    cur.execute(
        "SELECT preferenceid FROM preference.preference "
        "WHERE clientid = %s AND constituenturn = %s "
        "AND preferenceattributes->>'preferenceSubType' = 'CONTACT_OPT_IN' AND NOT deleted",
        (client_id, urn),
    )
    existing = cur.fetchone()

    if existing:
        # Update it to match desired state
        cur.execute(
            "UPDATE preference.preference SET preferenceattributes = %s::jsonb, lastmodified = NOW() "
            "WHERE preferenceid = %s",
            (attrs_json, existing[0]),
        )
        print(f"  [{env}] Updated preference record for {urn} (client {client_id})")
    else:
        cur.execute(
            """INSERT INTO preference.preference
               (preferenceid, clientid, constituenturn, preferencetypeid, preferencesubtypeid,
                preferenceattributes, deleted, version, created, lastmodified, lastmodifiedby)
               VALUES (
                 %s, %s, %s,
                 (SELECT preferencetypeid FROM preference.preferencetype WHERE name = 'PROGRAM_FEATURE' LIMIT 1),
                 (SELECT preferencesubtypeid FROM preference.preferencesubtype WHERE name = 'CONTACT_OPT_IN' LIMIT 1),
                 %s::jsonb, false, 1, NOW(), NOW(), 'E2E_AUTOMATION'
               )""",
            (str(uuid.uuid4()), client_id, urn, attrs_json),
        )
        print(f"  [{env}] Created preference record for {urn} (client {client_id})")

    cur.close()
    conn.close()


def ensure_p360_patient(env: str, client_id: int, phone: str) -> None:
    """Ensure the P360 patient document exists.

    Uses the structure that the Preference Management app actually needs to
    render an interactable patient detail view. The critical field is
    atebPatientId — without it the patient card renders but cannot be opened.
    Structure mirrors known-working QA/staging patients (e.g. 7249143802).
    """
    set_environment(env)
    existing = get_patient(client_id, phone)
    if existing:
        print(f"  [{env}] P360 patient exists for {phone} (client {client_id})")
    else:
        # atebPatientId must be unique-ish; derive from phone digits
        ateb_id = phone[-8:]
        patient = {
            "clientId": client_id,
            "storeId": client_id,
            "storeNpi": "1821516543",
            "atebPatientId": ateb_id,
            "dateOfBirth": "19850601",
            "name": {"firstName": "Automation", "lastName": "PrefTest" + phone[-4:]},
            "phone": {"primary": phone},
            "testCase": "PrefMgmtAutomation",
            "prescriptions": [
                {
                    "medication": {
                        "medicationName": "automation test drug",
                        "gpi": "59720867869337",
                        "ndc": "13663892838",
                    },
                    "rxNum": "9009401",
                    "fillDate": "20230215",
                    "daysSupply": 30,
                    "refillsRemaining": 4,
                    "originalRefillsAuth": 5,
                    "rxStatus": "OPEN",
                    "patientRxId": 14563,
                }
            ],
        }
        ensure_patient(patient)
        print(f"  [{env}] Created P360 patient for {phone} (client {client_id}) with atebPatientId={ateb_id}")
    close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, choices=["qa", "staging"])
    ap.add_argument("--client", required=True, type=int)
    ap.add_argument("--phone", required=True)
    ap.add_argument("--unreachable", action="store_true", help="Set unreachableNumber=true")
    ap.add_argument("--dnc", action="store_true", help="Set DO_NOT_CONTACT status (STOP)")
    args = ap.parse_args()

    print(f"Ensuring pref-searchable patient: {args.phone} (client {args.client}, {args.env})")
    ensure_p360_patient(args.env, args.client, args.phone)
    ensure_preference_record(args.env, args.client, args.phone,
                             unreachable=args.unreachable, dnc=args.dnc)
    print("Done.")


if __name__ == "__main__":
    main()
