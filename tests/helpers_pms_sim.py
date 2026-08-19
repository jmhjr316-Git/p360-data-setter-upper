"""PMS Simulator Data Builder — status-driven prescription data generator.

Generates XSD-valid PDX EPS prescription XML and uploads it to the PMS
simulator. Optionally creates matching P360 patient documents in DocumentDB.
Works as both a Python library (for test automation) and as the backend for
the Data_setter_upper Tkinter GUI.

ARCHITECTURE:
    1. User selects a desired RxStatus outcome (e.g., READY_FOR_PICKUP)
    2. build_scenario() auto-generates all XML fields that produce that status
    3. upload_scenario() pushes XML to the sim + upserts P360 patient doc
    4. delete_scenario() tears it all down

SUPPORTED STATUSES:
    READY_FOR_PICKUP      — StatusResponse 206
    IN_QUEUE              — StatusResponse 204
    WAITING_FOR_PRESCRIBER — StatusResponse 200
    REFILLABLE            — StatusResponse 207, picked up > 5 days ago
    RX_PICKED_UP          — StatusResponse 207, deliveredDaysAgo <= 5
    SHIPPED               — StatusResponse 208
    NOT_REFILLABLE        — RxResponse rxStatusCode=900, rejectCode block
    CONTROLLED_SUBSTANCE  — drug schedule=2, otherwise refillable
    TOO_SOON              — requires channel config minPercentageDaysSupply > 0
    RX_CROSS_STORE        — NOT testable via sim (documented below)
    RX_DELIVERED          — NOT reachable via PDX EPS (documented below)

USAGE (automation):
    from tests.helpers_pms_sim import build_scenario, upload_scenario, RxStatus

    scenario = build_scenario(
        rx_status=RxStatus.READY_FOR_PICKUP,
        rx_number="5610001",
        patient_first="STATUS",
        patient_last="TESTPATIENT",
        patient_phone="5550561001",
        patient_dob="19850101",
        drug_name="LISINOPRIL 10MG TAB",
    )
    upload_scenario(scenario)

    # Later:
    from tests.helpers_pms_sim import delete_scenario
    delete_scenario(scenario)

USAGE (legacy compat — still works):
    from tests.helpers_pms_sim import upload_rx, delete_rx, SimRx
    rx = SimRx(rx_number="5610001", drug_name="LISINOPRIL 10MG TAB")
    upload_rx(rx)

XSD RULES ENFORCED:
    - rxStatusDescription uses exact enum from EPS_ATEB_IVR.xsd
    - transactionControlReference max 10 chars
    - productName max 28 chars
    - syncScriptEnrolled is last child of rxInformation
    - StatusResponse shipper fields all required
    - rejectCode description exact enum
    - rejectCodeGroup only valid in RxResponse NOT StatusResponse
    - storeNumber must match channel config pmsStoreNumber

NON-TESTABLE STATUSES:
    RX_CROSS_STORE — The simulator always uses the configured store number,
        so storeNumber in the XML will always match pmsStoreNumber. Cross-store
        requires a REAL multi-store PMS where the Rx lives at a different store
        than the channel is configured for. To test this, you'd need two actual
        PMS stores or a custom mock that returns a different store in <control>.

    RX_DELIVERED — PDX EPS does not have a DELIVERED refill status. The adapter
        maps deliveredDaysAgo to a release date, and the bot checks
        RefillStatus.DELIVERED. But PDX EPS only ever sets RefillStatus.PICKED_UP
        (code 207). DELIVERED comes from other adapters like McKesson/Liberty
        that have explicit delivered codes.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

SIM_BASE_URL = "https://ivr-mock-svcs.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp"
DEFAULT_STORE_NUMBER = "70050001"  # QA store number for client 8000 (pmsStoreNumber for XML)
DEFAULT_CLIENT_ID = 8000
DEFAULT_STORE_ID = 9001  # OPE store ID (from channel config orgContext URN)
DEFAULT_STORE_NPI = "1821516543"  # Pharmacy NPI for the store

# Known client → store configuration
# storeId = OPE store ID (matches urn:OPE-STORE:{storeId} in channel config orgContext)
# storeNpi = pharmacy NPI
# pmsStoreNumber = what goes in XML <storeNumber> for the PMS sim
CLIENT_STORE_CONFIG = {
    8000: {"store_id": 9001, "store_npi": "1234580001", "pms_store_number": "70050001"},
    9001: {"store_id": 9001, "store_npi": "1821516543", "pms_store_number": "70050001"},
}

# ──────────────────────────────────────────────────────────────────────────────
# XSD ENUMS — the ONLY valid values for rxStatusDescription
# ──────────────────────────────────────────────────────────────────────────────

RX_STATUS_DESCRIPTIONS = {
    0: "000 = Rx Accepted",
    50: "050 = Rx Accepted; AutoFill Accepted",
    200: "200 = Waiting for Call Prescriber exception",
    204: "204 = Being filled",
    205: "205 = RESERVED - Not Used",
    206: "206 = Filled, waiting for pickup",
    207: "207 = Picked up",
    208: "208 = Shipped",
    209: "209 = Never filled",
    900: "900 = Rx Rejected",
    950: "950 = Rx Rejected; AutoFill Rejected",
}

# Also keyed by string code for convenience
RX_STATUS_DESCRIPTIONS_STR = {
    "000": "000 = Rx Accepted",
    "050": "050 = Rx Accepted; AutoFill Accepted",
    "200": "200 = Waiting for Call Prescriber exception",
    "204": "204 = Being filled",
    "205": "205 = RESERVED - Not Used",
    "206": "206 = Filled, waiting for pickup",
    "207": "207 = Picked up",
    "208": "208 = Shipped",
    "209": "209 = Never filled",
    "900": "900 = Rx Rejected",
    "950": "950 = Rx Rejected; AutoFill Rejected",
}


# Reject code descriptions — EXACT enum values from EPS_ATEB_IVR.xsd RejectCodeDescriptionTO
REJECT_CODE_DESCRIPTIONS = {
    "100": "100 = Security Violation - Wrong Class of Service.",
    "101": "101 = Security Violation - Wrong Store Number.",
    "102": "102 = Security Violation – Invalid Patient Record Number.",
    "103": "103 = Security Violation - IVR is not available",
    "500": "500 = Prescription is already in process of being filled.",
    "503": "503 = Cannot deliver to P.O. Box.",
    "504": "504 = No patient credit card cards on file.",
    "505": "505 = Prescription schedule cannot be delivered.",
    "506": "506 = Prescription has been transferred out of pharmacy.",
    "507": "507 = Prescription has been deactivated.",
    "508": "508 = Cannot fill prescription without patient permission to contact prescriber.",
    "509": "509 = Prescription number is not known to pharmacy.",
    "511": "511 = Store not configured for mail delivery.",
    "512": "512 = Missing/incomplete delivery address.",
    "513": "513 = Unable to process refill request, call back during pharmacy operating hours.",
    "514": "514 = Prescription autotransfer failed.",
    "515": "515 = Prescription autotransfer prohibited.",
    "521": "521 = Cannot refill prescription, prescriber requires patient call for refill(s)",
    "522": "522 = Invalid value found in personalHealthInformation element: valid values are 'Restrict PHI' or 'PHI Allowed'",
}


# ──────────────────────────────────────────────────────────────────────────────
# STATUS ENUM — desired outcome statuses
# ──────────────────────────────────────────────────────────────────────────────


class RxStatus(str, Enum):
    """Desired rx status outcomes the builder can produce."""

    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    IN_QUEUE = "IN_QUEUE"
    WAITING_FOR_PRESCRIBER = "WAITING_FOR_PRESCRIBER"
    REFILLABLE = "REFILLABLE"
    RX_PICKED_UP = "RX_PICKED_UP"
    SHIPPED = "SHIPPED"
    NOT_REFILLABLE = "NOT_REFILLABLE"
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    TOO_SOON = "TOO_SOON"
    RX_CROSS_STORE = "RX_CROSS_STORE"
    RX_DELIVERED = "RX_DELIVERED"


# ──────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SimRx:
    """Prescription data for the PMS simulator (low-level control).

    For status-driven creation, use build_scenario() instead.
    """

    rx_number: str
    drug_name: str  # Max 28 chars (XSD constraint)
    status_code: int = 206
    status_description: str = "206 = Filled, waiting for pickup"
    patient_first: str = "STATUS"
    patient_last: str = "TESTPATIENT"
    patient_dob: str = "1985-01-01T06:00:00"
    patient_phone: str = "5550561001"
    store_number: str = DEFAULT_STORE_NUMBER
    refills_remaining: int = 3
    authorized_refills: int = 5
    copay: float = 10.0
    days_supply: int = 30
    dispense_quantity: float = 30.0
    sig_text: str = "Take one tablet by mouth every day"
    prescriber_first: str = "JOHN"
    prescriber_last: str = "SMITH"
    # Optional fields for shipping statuses
    promise_datetime: str = "2026-08-15T10:00:00"
    shipper_name: str = "FEDEX"
    tracking_number: str = "TRACK123456"
    delivered_days_ago: int = 0
    # RxResponse-specific fields
    rx_response_status_code: int | None = None  # Defaults to 000 unless overridden
    rx_response_status_description: str | None = None
    refillable: str = "Y"
    drug_schedule: str = "L"  # L=legend (non-controlled), 2-5=controlled
    prescription_status: str = "A"  # A=Active, D=Deactivated, T=Transferred
    last_fill_date: str | None = None
    first_fill_date: str | None = None
    rx_expiration_date: str = "2027-12-31T00:00:00"
    # Reject code for RxResponse (NOT StatusResponse per XSD)
    reject_code: str | None = None
    # Ship datetime for StatusResponse
    ship_datetime: str | None = None


@dataclass
class SimScenario:
    """A complete test scenario: SimRx + P360 patient data + metadata."""

    rx: SimRx
    rx_status: RxStatus
    p360_patient: dict[str, Any] | None = None
    notes: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO BUILDER — the main API
# ──────────────────────────────────────────────────────────────────────────────


def build_scenario(
    rx_status: RxStatus,
    rx_number: str,
    patient_first: str = "STATUS",
    patient_last: str = "TESTPATIENT",
    patient_phone: str = "5550561001",
    patient_dob: str = "19850101",
    drug_name: str = "LISINOPRIL 10MG TAB",
    store_number: str = DEFAULT_STORE_NUMBER,
    client_id: int = DEFAULT_CLIENT_ID,
    store_id: int | None = None,
    store_npi: str | None = None,
    copay: float = 10.0,
    days_supply: int = 30,
    refills_remaining: int = 3,
    authorized_refills: int = 5,
    include_p360: bool = True,
    **kwargs,
) -> SimScenario:
    """Build a complete scenario that produces the desired rx_status.

    This is the primary API. It auto-generates all XML field values to match
    the desired outcome status, following the exact logic in RxStatusUtils.java
    and the pdxEPS.json adapter config.

    Args:
        rx_status: The desired outcome (e.g., RxStatus.READY_FOR_PICKUP)
        rx_number: Prescription number (used in file names)
        patient_first/last/phone/dob: Patient demographics
        drug_name: Drug product name (max 28 chars, auto-truncated)
        store_number: pmsStoreNumber — goes in XML <storeNumber> for sim lookup
        client_id: Client ID for P360 patient doc
        store_id: OPE store ID for P360 (from orgContext URN, e.g., 9001).
                  If None, looked up from CLIENT_STORE_CONFIG or defaults to client_id.
        store_npi: Pharmacy NPI for P360 (e.g., "1821516543").
                   If None, looked up from CLIENT_STORE_CONFIG.
        copay: Copay amount
        days_supply: Days supply on last fill
        refills_remaining: Remaining refills
        authorized_refills: Originally authorized refills
        include_p360: Whether to build matching P360 patient doc
        **kwargs: Additional overrides passed to SimRx

    Returns:
        SimScenario with populated SimRx and optional P360 patient doc

    Raises:
        ValueError: If rx_status is RX_CROSS_STORE or RX_DELIVERED (not testable)
    """
    if rx_status == RxStatus.RX_CROSS_STORE:
        raise ValueError(
            "RX_CROSS_STORE is not testable via the simulator. "
            "The sim always uses the configured store number, so storeNumber "
            "in the XML will always match pmsStoreNumber. Cross-store requires "
            "a real multi-store PMS or custom mock returning a different store."
        )

    if rx_status == RxStatus.RX_DELIVERED:
        raise ValueError(
            "RX_DELIVERED is not reachable via PDX EPS. The adapter only maps "
            "code 207 to PICKED_UP, never DELIVERED. DELIVERED comes from "
            "other adapters (McKesson/Liberty) with explicit delivered codes."
        )

    now = datetime.now()

    # Normalize DOB to XML format (accepts YYYYMMDD or ISO)
    dob_xml = _normalize_dob_to_xml(patient_dob)

    # Build the recipe based on desired status
    recipe = _STATUS_RECIPES[rx_status]

    # Compute dates based on recipe
    dates = recipe["date_fn"](now, days_supply)

    # Build SimRx
    rx = SimRx(
        rx_number=rx_number,
        drug_name=drug_name[:28],  # XSD max length
        status_code=recipe["status_response_code"],
        status_description=RX_STATUS_DESCRIPTIONS[recipe["status_response_code"]],
        patient_first=patient_first.upper(),
        patient_last=patient_last.upper(),
        patient_dob=dob_xml,
        patient_phone=patient_phone,
        store_number=store_number,
        refills_remaining=recipe.get("refills_remaining", refills_remaining),
        authorized_refills=authorized_refills,
        copay=copay,
        days_supply=days_supply,
        dispense_quantity=float(days_supply),
        prescriber_first="JOHN",
        prescriber_last="SMITH",
        promise_datetime=dates["promise_datetime"],
        shipper_name=recipe.get("shipper_name", "NONE"),
        tracking_number=recipe.get("tracking_number", "NONE"),
        delivered_days_ago=dates["delivered_days_ago"],
        rx_response_status_code=recipe["rx_response_code"],
        rx_response_status_description=RX_STATUS_DESCRIPTIONS[recipe["rx_response_code"]],
        refillable=recipe.get("refillable", "Y"),
        drug_schedule=recipe.get("drug_schedule", "L"),
        prescription_status=recipe.get("prescription_status", "A"),
        last_fill_date=dates["last_fill_date"],
        first_fill_date=dates["first_fill_date"],
        rx_expiration_date=dates["rx_expiration_date"],
        reject_code=recipe.get("reject_code"),
        ship_datetime=dates.get("ship_datetime"),
    )

    # Apply any explicit overrides
    for key, value in kwargs.items():
        if hasattr(rx, key):
            setattr(rx, key, value)

    # Build P360 patient document
    p360_doc = None
    if include_p360:
        # Resolve store_id and store_npi from CLIENT_STORE_CONFIG if not explicitly provided
        resolved_store_id = store_id
        resolved_store_npi = store_npi

        if resolved_store_id is None or resolved_store_npi is None:
            client_config = CLIENT_STORE_CONFIG.get(client_id, {})
            if resolved_store_id is None:
                resolved_store_id = client_config.get("store_id", client_id)
            if resolved_store_npi is None:
                resolved_store_npi = client_config.get("store_npi", DEFAULT_STORE_NPI)

        p360_doc = _build_p360_patient(
            rx=rx,
            rx_status=rx_status,
            client_id=client_id,
            store_id=resolved_store_id,
            store_npi=resolved_store_npi,
            patient_dob=patient_dob,
        )

    return SimScenario(
        rx=rx,
        rx_status=rx_status,
        p360_patient=p360_doc,
        notes=recipe.get("notes", ""),
    )


def upload_scenario(scenario: SimScenario, upload_p360: bool = True) -> None:
    """Upload a scenario to the simulator and optionally to P360.

    Args:
        scenario: The SimScenario from build_scenario()
        upload_p360: If True and scenario has p360_patient, upsert to DocumentDB.
                     Uses ensure_patient_with_rx() to merge prescriptions into
                     existing patients rather than replacing them.
    """
    upload_rx(scenario.rx)

    if upload_p360 and scenario.p360_patient:
        from tests.helpers_p360 import ensure_patient_with_rx
        ensure_patient_with_rx(scenario.p360_patient)
        logger.info(
            "Uploaded P360 patient for %s %s",
            scenario.rx.patient_first,
            scenario.rx.patient_last,
        )


def delete_scenario(scenario: SimScenario, delete_p360: bool = False) -> None:
    """Delete a scenario's sim data. Optionally delete P360 patient.

    Args:
        scenario: The SimScenario to clean up
        delete_p360: If True, also delete the P360 patient document
    """
    delete_rx(scenario.rx.rx_number)

    if delete_p360 and scenario.p360_patient:
        from tests.helpers_p360 import delete_patient
        delete_patient(
            client_id=scenario.p360_patient["clientId"],
            phone=scenario.p360_patient["phone"]["primary"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# STATUS RECIPES — mapping desired status → required XML field values
# ──────────────────────────────────────────────────────────────────────────────


def _dates_ready_for_pickup(now: datetime, days_supply: int) -> dict:
    return {
        "last_fill_date": (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "delivered_days_ago": 0,
        "ship_datetime": now.strftime("%Y-%m-%dT%H:%M:%S.000"),
    }


def _dates_in_queue(now: datetime, days_supply: int) -> dict:
    return {
        "last_fill_date": (now - timedelta(days=35)).strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "delivered_days_ago": 0,
        "ship_datetime": now.strftime("%Y-%m-%dT%H:%M:%S.000"),
    }


def _dates_waiting_for_prescriber(now: datetime, days_supply: int) -> dict:
    return {
        "last_fill_date": (now - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "delivered_days_ago": 0,
        "ship_datetime": now.strftime("%Y-%m-%dT%H:%M:%S.000"),
    }


def _dates_refillable(now: datetime, days_supply: int) -> dict:
    """Picked up > 5 days ago → REFILLABLE (not RX_PICKED_UP)."""
    last_fill = now - timedelta(days=max(days_supply, 10))
    return {
        "last_fill_date": last_fill.strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
        "delivered_days_ago": (now - last_fill).days,
        "ship_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
    }


def _dates_rx_picked_up(now: datetime, days_supply: int) -> dict:
    """Picked up <= 5 days ago → RX_PICKED_UP."""
    last_fill = now - timedelta(days=2)
    return {
        "last_fill_date": last_fill.strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
        "delivered_days_ago": 2,
        "ship_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
    }


def _dates_shipped(now: datetime, days_supply: int) -> dict:
    ship_date = now - timedelta(days=1)
    return {
        "last_fill_date": (now - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": (now + timedelta(days=3)).strftime("%Y-%m-%dT10:00:00.000"),
        "delivered_days_ago": 1,
        "shipper_name": "FEDEX",
        "tracking_number": "FX123456789",
        "ship_datetime": ship_date.strftime("%Y-%m-%dT10:00:00.000"),
    }


def _dates_not_refillable(now: datetime, days_supply: int) -> dict:
    return {
        "last_fill_date": (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": now.strftime("%Y-%m-%dT10:00:00.000"),
        "delivered_days_ago": 30,
        "ship_datetime": (now - timedelta(days=30)).strftime("%Y-%m-%dT10:00:00.000"),
    }


def _dates_controlled_substance(now: datetime, days_supply: int) -> dict:
    """Same as refillable but with schedule 2."""
    last_fill = now - timedelta(days=max(days_supply, 10))
    return {
        "last_fill_date": last_fill.strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
        "delivered_days_ago": (now - last_fill).days,
        "ship_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
    }


def _dates_too_soon(now: datetime, days_supply: int) -> dict:
    """Filled recently — not enough days consumed for refill."""
    # Fill 5 days ago with 30 day supply → only 16% consumed
    last_fill = now - timedelta(days=5)
    return {
        "last_fill_date": last_fill.strftime("%Y-%m-%dT00:00:00"),
        "first_fill_date": (now - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00"),
        "rx_expiration_date": (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00"),
        "promise_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
        # deliveredDaysAgo > 5 so it passes the RX_PICKED_UP check
        "delivered_days_ago": (now - last_fill).days + 1,
        "ship_datetime": last_fill.strftime("%Y-%m-%dT10:00:00.000"),
    }


_STATUS_RECIPES: dict[RxStatus, dict[str, Any]] = {
    RxStatus.READY_FOR_PICKUP: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 206,  # Filled, waiting for pickup
        "date_fn": _dates_ready_for_pickup,
        "refillable": "Y",
        "notes": "StatusResponse 206 → RefillStatus.READY_FOR_PICKUP → non-refillable path → READY_FOR_PICKUP",
    },
    RxStatus.IN_QUEUE: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 204,  # Being filled
        "date_fn": _dates_in_queue,
        "refillable": "Y",
        "notes": "StatusResponse 204 → RefillStatus.IN_QUEUE → non-refillable path → IN_QUEUE",
    },
    RxStatus.WAITING_FOR_PRESCRIBER: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 200,  # Waiting for Call Prescriber exception
        "date_fn": _dates_waiting_for_prescriber,
        "refillable": "Y",
        "notes": "StatusResponse 200 → RefillStatus.WAITING_FOR_PRESCRIBER → non-refillable path",
    },
    RxStatus.REFILLABLE: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 207,  # Picked up (but long ago)
        "date_fn": _dates_refillable,
        "refillable": "Y",
        "notes": (
            "StatusResponse 207 with deliveredDaysAgo > 5 → refillable path. "
            "Drug schedule=L (non-controlled), no TOO_SOON (days consumed > min%)."
        ),
    },
    RxStatus.RX_PICKED_UP: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 207,  # Picked up (recently)
        "date_fn": _dates_rx_picked_up,
        "refillable": "Y",
        "notes": (
            "StatusResponse 207 with deliveredDaysAgo <= 5 → refillable path → "
            "daysSinceLastFill <= daysAfterPickup → RX_PICKED_UP"
        ),
    },
    RxStatus.SHIPPED: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 208,  # Shipped
        "shipper_name": "FEDEX",
        "tracking_number": "FX123456789",
        "date_fn": _dates_shipped,
        "refillable": "Y",
        "notes": "StatusResponse 208 → RefillStatus.SHIPPED (but not FILLED_NOT_SHIPPED which is 204-like)",
    },
    RxStatus.NOT_REFILLABLE: {
        "rx_response_code": 900,  # 900 = Rx Rejected
        "status_response_code": 207,  # Status doesn't matter much, 207 is fine
        "refillable": "N",
        "refills_remaining": 0,
        "reject_code": "513",  # NOT_REFILLABLE reject code
        "date_fn": _dates_not_refillable,
        "notes": (
            "RxResponse rxStatusCode=900 → RxStatus.UNKNOWN → falls through to NOT_REFILLABLE. "
            "rejectCode 513 in RxResponse (NOT in StatusResponse per XSD). "
            "Valid reject codes for NOT_REFILLABLE: 513, 514, 515, 521."
        ),
    },
    RxStatus.CONTROLLED_SUBSTANCE: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 207,  # Picked up (long ago)
        "drug_schedule": "2",  # Schedule 2 = controlled
        "date_fn": _dates_controlled_substance,
        "refillable": "Y",
        "notes": (
            "StatusResponse 207, deliveredDaysAgo > 5, drug schedule=2. "
            "Refillable path → passes TOO_SOON → hits drugSchedule < minAllowedDrugSchedule(3) → CONTROLLED_SUBSTANCE"
        ),
    },
    RxStatus.TOO_SOON: {
        "rx_response_code": 0,  # 000 = Rx Accepted
        "status_response_code": 207,  # Picked up
        "date_fn": _dates_too_soon,
        "refillable": "Y",
        "notes": (
            "StatusResponse 207, deliveredDaysAgo > 5, lastFillDate very recent. "
            "Refillable path → daysSinceLastFill/lastFillDaySupply*100 < minPercentageDaysSupply. "
            "REQUIRES channel config: minPercentageDaysSupply > 0 (default is 0 which disables). "
            "AND inboundCampaignIdForManualRxRules must be blank/absent."
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# P360 PATIENT DOCUMENT BUILDER
# ──────────────────────────────────────────────────────────────────────────────


def _build_p360_patient(
    rx: SimRx,
    rx_status: RxStatus,
    client_id: int,
    store_id: int,
    store_npi: str,
    patient_dob: str,
) -> dict[str, Any]:
    """Build a P360 patient document matching the sim Rx data.

    Document format matches what the personalization engine expects:
    - search field with lastNameUpper/firstNameUpper/dob/phoneNumber
    - orgs with e360OrgId/e360StoreId
    - mdfcode ACTIVE
    - patientStatus 0

    IMPORTANT field distinctions:
    - storeId = OPE store ID (from orgContext URN, e.g., 9001 for urn:OPE-STORE:9001)
    - storeNpi = pharmacy NPI (e.g., "1821516543" for client 9001)
    - pmsStoreNumber (rx.store_number) = what goes in XML <storeNumber> for sim lookup
      These are DIFFERENT values and must not be conflated.
    """
    # Normalize DOB to YYYYMMDD for P360
    dob_p360 = _normalize_dob_to_p360(patient_dob)

    # Determine fill date in YYYYMMDD format for P360
    if rx.last_fill_date:
        fill_date_p360 = rx.last_fill_date[:10].replace("-", "")
    else:
        fill_date_p360 = datetime.now().strftime("%Y%m%d")

    return {
        "clientId": client_id,
        "storeId": store_id,
        "storeNpi": store_npi,
        "atebPatientId": int(rx.rx_number) if rx.rx_number.isdigit() else 99001,
        "dateOfBirth": dob_p360,
        "name": {
            "firstName": rx.patient_first,
            "lastName": rx.patient_last,
        },
        "phone": {
            "primary": rx.patient_phone,
        },
        "search": {
            "lastNameUpper": rx.patient_last.upper(),
            "firstNameUpper": rx.patient_first.upper(),
            "dob": dob_p360,
            "phoneNumber": rx.patient_phone,
        },
        "orgs": [
            {
                "e360OrgId": client_id,
                "e360StoreId": store_id,
            }
        ],
        "mdfcode": "ACTIVE",
        "patientStatus": 0,
        "prescriptions": [
            {
                "medication": {
                    "medicationName": rx.drug_name,
                    "gpi": "27100010000310",
                    "ndc": "00093007101",
                },
                "rxNum": rx.rx_number,
                "fillDate": fill_date_p360,
                "daysSupply": rx.days_supply,
                "refillsRemaining": rx.refills_remaining,
                "originalRefillsAuth": rx.authorized_refills,
                "rxStatus": "OPEN",
            }
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# XML BUILDERS
# ──────────────────────────────────────────────────────────────────────────────


def _build_rx_response_xml(rx: SimRx) -> str:
    """Build RxResponse XML (INFO transaction response).

    XSD rules enforced:
    - rxStatusDescription exact enum
    - syncScriptEnrolled as last child of rxInformation
    - productName max 28 chars
    - transactionControlReference max 10 chars
    - rejectCodeGroup only in RxResponse (not StatusResponse)
    """
    rx_code = rx.rx_response_status_code if rx.rx_response_status_code is not None else 0
    rx_desc = rx.rx_response_status_description or RX_STATUS_DESCRIPTIONS[0]

    # Format code with leading zeros (3 digits)
    rx_code_str = f"{rx_code:03d}"

    # Build reject code block if needed (ONLY valid in RxResponse per XSD)
    reject_block = ""
    if rx.reject_code:
        reject_desc = REJECT_CODE_DESCRIPTIONS.get(rx.reject_code, f"{rx.reject_code} = Unknown reject code")
        reject_block = f"""
      <rejectCodeGroup>
        <rejectCode>
          <code>{rx.reject_code}</code>
          <description>{reject_desc}</description>
        </rejectCode>
      </rejectCodeGroup>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<getRxResponse version="1.0.18.4">
  <control>
    <source>ivr</source>
    <destination>eps</destination>
    <storeNumberType>nhin</storeNumberType>
    <storeNumber>{rx.store_number}</storeNumber>
    <softwareVersnum>2607</softwareVersnum>
    <transactionControlReference>9ebecdfc</transactionControlReference>
    <dateTimeOfInitiation>2026-01-01T00:00:00.000</dateTimeOfInitiation>
    <classOfServiceKey>LEVEL 1</classOfServiceKey>
  </control>
  <msgStatus>
    <msgStatusCode>000</msgStatusCode>
  </msgStatus>
  <rxDataGroup>
    <rxDataItem>
      <number>{rx.rx_number}</number>
      <rxStatusCode>{rx_code_str}</rxStatusCode>
      <rxStatusDescription>{rx_desc}</rxStatusDescription>{reject_block}
      <rxInformation>
        <refillable>{rx.refillable}</refillable>
        <authorizedRefills>{rx.authorized_refills}</authorizedRefills>
        <sigText>{rx.sig_text}</sigText>
        <autoFillOption>N</autoFillOption>
        <autoFillOptionDate>2026-01-01T00:00:00</autoFillOptionDate>
        <callForRefillOption>D</callForRefillOption>
        <rxExpirationDate>{rx.rx_expiration_date}</rxExpirationDate>
        <firstFillDate>{rx.first_fill_date or "2026-01-15T00:00:00"}</firstFillDate>
        <lastFillDate>{rx.last_fill_date or "2026-07-15T00:00:00"}</lastFillDate>
        <dispensedDaysSupply>{rx.days_supply}</dispensedDaysSupply>
        <dispenseQuantity>{rx.dispense_quantity}</dispenseQuantity>
        <remainingQuantity>100.0</remainingQuantity>
        <prescribedQuantity>{rx.dispense_quantity}</prescribedQuantity>
        <patientAmountPaid>0.0</patientAmountPaid>
        <prescriptionStatus>{rx.prescription_status}</prescriptionStatus>
        <refillsRemaining>{rx.refills_remaining}</refillsRemaining>
        <finalCopay>{rx.copay}</finalCopay>
        <syncScriptEnrolled>R</syncScriptEnrolled>
      </rxInformation>
      <patient>
        <personName>
          <lastName>{rx.patient_last}</lastName>
          <firstName>{rx.patient_first}</firstName>
          <language>en</language>
        </personName>
        <birthDate>{rx.patient_dob}</birthDate>
        <genderCode>M</genderCode>
        <telephoneGroup>
          <telephoneNumber>
            <number>{rx.patient_phone}</number>
            <qualifier>1</qualifier>
            <sms>N</sms>
          </telephoneNumber>
        </telephoneGroup>
        <safetyCaps>Y</safetyCaps>
      </patient>
      <drug>
        <productName>{rx.drug_name[:28]}</productName>
        <schedule>{rx.drug_schedule}</schedule>
      </drug>
      <prescriber>
        <allowFAX>N</allowFAX>
        <personName>
          <lastName>{rx.prescriber_last}</lastName>
          <firstName>{rx.prescriber_first}</firstName>
          <language>en</language>
        </personName>
      </prescriber>
    </rxDataItem>
  </rxDataGroup>
</getRxResponse>"""


def _build_status_response_xml(rx: SimRx) -> str:
    """Build StatusResponse XML (STATUS transaction response).

    XSD rules enforced:
    - All shipper fields required after deliveredDaysAgo
    - rxStatusDescription exact enum
    - NO rejectCodeGroup (only valid in RxResponse)
    - transactionControlReference max 10 chars
    """
    ship_dt = rx.ship_datetime or "2026-08-10T10:00:00.000"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rxStatusResponse version="1.0.18.4">
  <control>
    <source>ivr</source>
    <destination>eps</destination>
    <storeNumberType>nhin</storeNumberType>
    <storeNumber>{rx.store_number}</storeNumber>
    <softwareVersnum>2607</softwareVersnum>
    <transactionControlReference>9ebecdfc</transactionControlReference>
    <dateTimeOfInitiation>2026-01-01T00:00:00.000</dateTimeOfInitiation>
    <classOfServiceKey>LEVEL 1</classOfServiceKey>
  </control>
  <msgStatus>
    <msgStatusCode>000</msgStatusCode>
  </msgStatus>
  <rxStatusGroup>
    <rxStatusItem>
      <number>{rx.rx_number}</number>
      <rxStatusCode>{rx.status_code}</rxStatusCode>
      <rxStatusDescription>{rx.status_description}</rxStatusDescription>
      <promiseDateTime>{rx.promise_datetime}</promiseDateTime>
      <deliveredDaysAgo>{rx.delivered_days_ago}</deliveredDaysAgo>
      <shipperName>{rx.shipper_name}</shipperName>
      <shipperTrackingNumber>{rx.tracking_number}</shipperTrackingNumber>
      <shipDateTime>{ship_dt}</shipDateTime>
      <orderNumber>ORD{rx.rx_number[:7]}</orderNumber>
    </rxStatusItem>
  </rxStatusGroup>
</rxStatusResponse>"""


def _build_refill_response_xml(rx: SimRx) -> str:
    """Build RefillResponse XML (REFILL transaction response)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<refillRxResponse version="1.0.18.4">
  <control>
    <source>ivr</source>
    <destination>eps</destination>
    <storeNumberType>nhin</storeNumberType>
    <storeNumber>{rx.store_number}</storeNumber>
    <softwareVersnum>2607</softwareVersnum>
    <transactionControlReference>9ebecdfc</transactionControlReference>
    <dateTimeOfInitiation>2026-01-01T00:00:00.000</dateTimeOfInitiation>
    <classOfServiceKey>LEVEL 1</classOfServiceKey>
  </control>
  <msgStatus>
    <msgStatusCode>000</msgStatusCode>
  </msgStatus>
  <rxStatusGroup>
    <rxStatusItem>
      <number>{rx.rx_number}</number>
      <rxStatusCode>{rx.status_code}</rxStatusCode>
      <rxStatusDescription>{rx.status_description}</rxStatusDescription>
      <promiseDateTime>{rx.promise_datetime}</promiseDateTime>
    </rxStatusItem>
  </rxStatusGroup>
</refillRxResponse>"""


# ──────────────────────────────────────────────────────────────────────────────
# UPLOAD / DELETE — network operations
# ──────────────────────────────────────────────────────────────────────────────


def upload_rx(rx: SimRx) -> None:
    """Upload all 3 response files for a prescription to the simulator.

    Creates RxResponse, StatusResponse, and RefillResponse XML files
    at PDX/{Type}{rx_number}.xml on the sim.
    """
    files = {
        f"PDX/RxResponse{rx.rx_number}.xml": _build_rx_response_xml(rx),
        f"PDX/StatusResponse{rx.rx_number}.xml": _build_status_response_xml(rx),
        f"PDX/RefillResponse{rx.rx_number}.xml": _build_refill_response_xml(rx),
    }

    with httpx.Client(verify=False, timeout=10.0) as client:
        for file_path, content in files.items():
            encoded_content = urllib.parse.quote(content)
            url = f"{SIM_BASE_URL}?action=write&file_path={file_path}&content={encoded_content}"
            resp = client.get(url)
            if resp.status_code != 200 or "error" in resp.text.lower():
                raise RuntimeError(
                    f"Failed to upload {file_path}: {resp.status_code} {resp.text[:200]}"
                )
            logger.debug("Uploaded %s", file_path)

    logger.info(
        "Uploaded sim data for rx %s (%s) — status %s (%s)",
        rx.rx_number,
        rx.drug_name,
        rx.status_code,
        rx.status_description,
    )


def delete_rx(rx_number: str) -> None:
    """Delete all response files for a prescription from the simulator."""
    files = [
        f"PDX/RxResponse{rx_number}.xml",
        f"PDX/StatusResponse{rx_number}.xml",
        f"PDX/RefillResponse{rx_number}.xml",
    ]

    with httpx.Client(verify=False, timeout=10.0) as client:
        for file_path in files:
            url = f"{SIM_BASE_URL}?action=delete&file_path={file_path}"
            client.get(url)  # Ignore errors on delete (file might not exist)

    logger.info("Deleted sim data for rx %s", rx_number)


def upload_batch(rxs: list[SimRx]) -> None:
    """Upload multiple prescriptions at once."""
    for rx in rxs:
        upload_rx(rx)


def list_sim_files(path: str = "PDX") -> list[str]:
    """List files on the simulator at the given path."""
    with httpx.Client(verify=False, timeout=10.0) as client:
        url = f"{SIM_BASE_URL}?action=list&file_path={path}"
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list files: {resp.status_code} {resp.text[:200]}")
        # Response is newline-separated file list
        return [line.strip() for line in resp.text.strip().split("\n") if line.strip()]


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _normalize_dob_to_xml(dob: str) -> str:
    """Convert DOB from various formats to XML format (YYYY-MM-DDTHH:MM:SS)."""
    # If already in XML format
    if "T" in dob:
        return dob
    # YYYYMMDD
    if len(dob) == 8 and dob.isdigit():
        return f"{dob[:4]}-{dob[4:6]}-{dob[6:8]}T06:00:00"
    # YYYY-MM-DD
    if len(dob) == 10 and "-" in dob:
        return f"{dob}T06:00:00"
    # Fallback
    return dob


def _normalize_dob_to_p360(dob: str) -> str:
    """Convert DOB from various formats to P360 format (YYYYMMDD)."""
    # Already YYYYMMDD
    if len(dob) == 8 and dob.isdigit():
        return dob
    # YYYY-MM-DD
    if len(dob) == 10 and "-" in dob:
        return dob.replace("-", "")
    # ISO with time
    if "T" in dob:
        return dob[:10].replace("-", "")
    return dob


# ──────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS — build + upload in one call
# ──────────────────────────────────────────────────────────────────────────────


def create_ready_for_pickup(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a READY_FOR_PICKUP scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.READY_FOR_PICKUP, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_in_queue(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create an IN_QUEUE scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.IN_QUEUE, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_waiting_for_prescriber(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a WAITING_FOR_PRESCRIBER scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.WAITING_FOR_PRESCRIBER, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_refillable(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a REFILLABLE scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.REFILLABLE, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_rx_picked_up(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create an RX_PICKED_UP scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.RX_PICKED_UP, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_shipped(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a SHIPPED scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.SHIPPED, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_not_refillable(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a NOT_REFILLABLE scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.NOT_REFILLABLE, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_controlled_substance(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a CONTROLLED_SUBSTANCE scenario and upload it."""
    scenario = build_scenario(rx_status=RxStatus.CONTROLLED_SUBSTANCE, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario


def create_too_soon(rx_number: str, **kwargs) -> SimScenario:
    """One-liner: create a TOO_SOON scenario and upload it.

    NOTE: Requires channel config minPercentageDaysSupply > 0.
    """
    scenario = build_scenario(rx_status=RxStatus.TOO_SOON, rx_number=rx_number, **kwargs)
    upload_scenario(scenario)
    return scenario
