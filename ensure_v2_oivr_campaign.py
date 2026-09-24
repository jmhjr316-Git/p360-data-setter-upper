#!/usr/bin/env python3
"""
Ensure the "AUTOMATION OIVR SMS CAMPAIGN" custom campaign exists in a target env/client
for the V2 Campaign Configuration UI automation (PC-29062 / PC-29401 scenarios).

Why: those scenarios open a campaign named "AUTOMATION OIVR SMS CAMPAIGN" and verify the
Send Now / Honor Calling Windows / Transfers toggles. The campaign must be a CUSTOM
campaign (has INFORMATIONAL message configs) so those sections render. It exists in QA
(client 5011) but not in staging (client 9001). Data is wiped periodically, so seed it.

Approach (spec-faithful, no hand-built JSON): GET the canonical QA campaign definition,
strip all server-generated identity fields (id/version/createdDate/lastModifiedDate)
recursively, adjust dates, and POST it to the target. Idempotent: if a campaign with the
same name already exists in the target client, do nothing.

Usage:
  python3 ensure_v2_oivr_campaign.py --env staging --client 9001
  python3 ensure_v2_oivr_campaign.py --env qa --client 5011   # no-op (source lives here)

Token: reads OCP_MSGCMPGN_TOKEN from env (the long-lived super-admin token). The UI repo's
.env has it; export it or run `set -a; source .env; set +a` first.

NOTE: uses the msg-cmpgn-svcs *v2* API (/cxf/api/messagecampaign/v2). v2 is what the E360 UI
uses; it has the correct campaign shape (top-level channelConfigurations + messageTypeConfigurations)
and supports DELETE (v1 does NOT — v1 DELETE returns 405, and a v1-shaped campaign is missing the
v2 channel configs so it fails validation on Save, e.g. sendNow toggles won't persist).
"""
import argparse
import copy
import datetime
import json
import os
import sys
import urllib.request
import urllib.error

BASE = {
    "qa": "https://msg-cmpgn-svcs.pc.q.platform.enlivenhealth.co/cxf/api/messagecampaign/v2",
    "staging": "https://msg-cmpgn-svcs.pc.s.platform.enlivenhealth.co/cxf/api/messagecampaign/v2",
}
# Canonical source campaign (QA client 5011)
SOURCE_ENV = "qa"
SOURCE_CLIENT = 5011
SOURCE_CAMPAIGN_ID = "fa3b0ab6-e72f-430d-bfd1-bc611864a36c"
CAMPAIGN_NAME = "AUTOMATION OIVR SMS CAMPAIGN"

# Server-generated fields to remove at every level so the target mints fresh ones.
STRIP_KEYS = {"id", "version", "createdDate", "lastModifiedDate"}


def _token():
    tok = os.environ.get("OCP_MSGCMPGN_TOKEN", "").strip()
    if not tok:
        sys.exit("ERROR: OCP_MSGCMPGN_TOKEN not set. `set -a; source .env; set +a` in the UI repo first.")
    return tok


def _req(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    ctx = __import__("ssl").create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = __import__("ssl").CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _strip(obj):
    """Recursively remove server-generated identity fields."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in STRIP_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _find_campaign_by_name(env, client, token, name):
    for pg in range(1, 8):
        url = f"{BASE[env]}/clients/{client}/campaigns?pageNumber={pg}&pageSize=200"
        status, body = _req("GET", url, token)
        if status != 200 or not body:
            break
        items = body if isinstance(body, list) else body.get("content", [])
        if not items:
            break
        for c in items:
            if str(c.get("name", "")).strip() == name:
                return c
        if len(items) < 200:
            break
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, choices=["qa", "staging"])
    ap.add_argument("--client", required=True, type=int)
    ap.add_argument("--org-context", default=None,
                    help="Optional orgContext URN to attach (QA source has none).")
    args = ap.parse_args()
    token = _token()

    # Idempotency: already present in target?
    existing = _find_campaign_by_name(args.env, args.client, token, CAMPAIGN_NAME)
    if existing:
        print(f"OK: '{CAMPAIGN_NAME}' already exists in {args.env} client {args.client} "
              f"(id={existing.get('id')}, status={existing.get('status')}). No-op.")
        return 0

    # Pull the canonical definition from QA.
    src_url = f"{BASE[SOURCE_ENV]}/clients/{SOURCE_CLIENT}/campaigns/{SOURCE_CAMPAIGN_ID}"
    status, src = _req("GET", src_url, token)
    if status != 200 or not isinstance(src, dict):
        sys.exit(f"ERROR: could not fetch source campaign ({status}): {src}")

    payload = _strip(copy.deepcopy(src))
    # Fresh, valid dates (source uses a past endDate but stays ENABLED; keep the campaign
    # openly dated so it's clearly available).
    today = datetime.date.today()
    payload["startDate"] = today.isoformat()
    payload["endDate"] = (today + datetime.timedelta(days=3650)).isoformat()
    payload["status"] = "ENABLED"
    if args.org_context:
        payload["orgContexts"] = [args.org_context]

    create_url = f"{BASE[args.env]}/clients/{args.client}/campaigns"
    status, body = _req("POST", create_url, token, payload)
    if status in (200, 201):
        new_id = body.get("id") if isinstance(body, dict) else None
        print(f"CREATED: '{CAMPAIGN_NAME}' in {args.env} client {args.client} (id={new_id}).")
        return 0
    sys.exit(f"ERROR: create failed ({status}): {body}")


if __name__ == "__main__":
    sys.exit(main())
