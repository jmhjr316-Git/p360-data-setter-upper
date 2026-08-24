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

SIM_BASE_URL = "https://pmssim.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp"
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


# ══════════════════════════════════════════════════════════════════════════════
# McKESSON (PerSe) SIMULATOR SUPPORT
# ══════════════════════════════════════════════════════════════════════════════
#
# McKesson uses the PerSe simulator servlet. Files live at:
#   WEB-INF/rsp/PerSe/RxInfoRsp{rxnum}.xml
#   WEB-INF/rsp/PerSe/SubmitIVROrderRsp{rxnum}.xml
#
# Status is driven by FillInfo attributes:
#   IsReady=true                           → READY_FOR_PICKUP
#   IsReady=false, NotReadyReasonCode=1    → IN_QUEUE
#   IsReady=false, NotReadyReasonCode=2    → PICKED_UP (check releaseDate)
#   IsRefillable=false, NotRefillableReasonCode:
#     1 → READY_FOR_PICKUP (via not-refillable path)
#     2 → IN_QUEUE (via not-refillable path)
#     3 → CONTROLLED_SUBSTANCE (CII)
#     4 → OUT_OF_REFILLS
#     5 → EXPIRED
#     6 → TRANSFERRED
#     7 → DEACTIVATED
#     8 → TOO_SOON
#     9 → OUT_OF_STOCK
#    10 → special handling in code
# ══════════════════════════════════════════════════════════════════════════════


class McKessonStatus(str, Enum):
    """Desired McKesson rx status outcomes the builder can produce."""

    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    IN_QUEUE = "IN_QUEUE"
    REFILLABLE = "REFILLABLE"
    RX_PICKED_UP = "RX_PICKED_UP"
    NOT_REFILLABLE_EXPIRED = "NOT_REFILLABLE_EXPIRED"
    NOT_REFILLABLE_NO_REFILLS = "NOT_REFILLABLE_NO_REFILLS"
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    TOO_SOON = "TOO_SOON"
    TRANSFERRED = "TRANSFERRED"
    DEACTIVATED = "DEACTIVATED"


@dataclass
class McKessonRx:
    """McKesson/PerSe prescription data for the simulator."""

    rx_number: str
    drug_name: str
    store_number: str = "125"
    patient_first: str = "TEST"
    patient_last: str = "MCKESSON"
    patient_dob: str = "1975-08-22"  # Format: YYYY-MM-DD
    patient_phone: str = "555-234-5678"
    patient_id: str = "1078600"
    refills_remaining: str = "3"
    refills_authorized: str = "5"
    days_supply: int = 30
    quantity: int = 30
    copay: str = "25"
    sig_text: str = "TAKE ONE TABLET BY MOUTH DAILY"
    dea_class: str = "0"  # 0=non-controlled, 2=CII, etc.
    ndc: str = "00093751001"
    prescriber_first: str = "JOHN"
    prescriber_last: str = "SMITH"
    expiration_date: str = "2028-12-31"
    # FillInfo attributes
    is_ready: bool = False
    is_refillable: bool = True
    refill_qty: int = 30
    # NotReadyInfo (when is_ready=False and is_refillable=True)
    not_ready_reason_code: str | None = None  # "1"=in queue, "2"=picked up
    released_to_patient_datetime: str | None = None
    # NotRefillableInfo (when is_refillable=False)
    not_refillable_reason_code: str | None = None
    is_doctor_auth_allowed: str = "false"
    # ReadyInfo (when is_ready=True)
    patient_pay_amount: str | None = None
    # Fill dates
    first_fill_date: str = "2025-06-01"
    last_fill_date: str = "2026-05-01"
    last_fill_number: str = "3"


@dataclass
class McKessonScenario:
    """A complete McKesson test scenario."""

    rx: McKessonRx
    status: McKessonStatus
    p360_patient: dict[str, Any] | None = None
    notes: str = ""


# McKesson status recipes
_MCKESSON_STATUS_RECIPES: dict[McKessonStatus, dict[str, Any]] = {
    McKessonStatus.READY_FOR_PICKUP: {
        "is_ready": True,
        "is_refillable": True,
        "patient_pay_amount": "25",
        "not_ready_reason_code": None,
        "not_refillable_reason_code": None,
    },
    McKessonStatus.IN_QUEUE: {
        "is_ready": False,
        "is_refillable": True,
        "not_ready_reason_code": "1",
        "not_refillable_reason_code": None,
    },
    McKessonStatus.REFILLABLE: {
        "is_ready": False,
        "is_refillable": True,
        "not_ready_reason_code": "2",
        "released_to_patient_datetime": None,  # will be computed
        "not_refillable_reason_code": None,
    },
    McKessonStatus.RX_PICKED_UP: {
        "is_ready": False,
        "is_refillable": True,
        "not_ready_reason_code": "2",
        "released_to_patient_datetime": None,  # will be computed (recent)
        "not_refillable_reason_code": None,
    },
    McKessonStatus.NOT_REFILLABLE_EXPIRED: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "5",
        "is_doctor_auth_allowed": "false",
    },
    McKessonStatus.NOT_REFILLABLE_NO_REFILLS: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "4",
        "is_doctor_auth_allowed": "true",
        "refills_remaining": "0",
    },
    McKessonStatus.CONTROLLED_SUBSTANCE: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "3",
        "is_doctor_auth_allowed": "false",
        "dea_class": "2",
        "refills_remaining": "0",
    },
    McKessonStatus.TOO_SOON: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "8",
        "is_doctor_auth_allowed": "false",
    },
    McKessonStatus.TRANSFERRED: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "6",
        "is_doctor_auth_allowed": "false",
    },
    McKessonStatus.DEACTIVATED: {
        "is_ready": False,
        "is_refillable": False,
        "not_refillable_reason_code": "7",
        "is_doctor_auth_allowed": "false",
    },
}


def build_mckesson_scenario(
    status: McKessonStatus,
    rx_number: str,
    patient_first: str = "TEST",
    patient_last: str = "MCKESSON",
    patient_phone: str = "555-234-5678",
    patient_dob: str = "1975-08-22",
    drug_name: str = "METFORMIN 500MG TAB",
    store_number: str = "125",
    client_id: int = 9000,
    copay: str = "25",
    days_supply: int = 30,
    refills_remaining: str = "3",
    refills_authorized: str = "5",
    dea_class: str = "0",
    include_p360: bool = True,
    store_id: int = DEFAULT_STORE_ID,
    store_npi: str = DEFAULT_STORE_NPI,
) -> McKessonScenario:
    """Build a McKesson/PerSe scenario for a desired status outcome.

    Args:
        status: The desired McKesson rx status outcome.
        rx_number: The prescription number.
        patient_first: Patient first name.
        patient_last: Patient last name.
        patient_phone: Patient phone (format: XXX-XXX-XXXX or 10 digits).
        patient_dob: Patient DOB (YYYY-MM-DD format).
        drug_name: Drug name (no length limit for McKesson).
        store_number: McKesson store number.
        client_id: Client ID for P360.
        copay: Patient copay amount (string).
        days_supply: Days supply per fill.
        refills_remaining: Refills remaining.
        refills_authorized: Refills authorized.
        dea_class: DEA schedule (0=non-controlled, 2=CII, etc.).
        include_p360: Whether to build P360 patient data.
        store_id: OPE store ID for P360.
        store_npi: Store NPI for P360.

    Returns:
        McKessonScenario with rx data and optional P360 patient.
    """
    now = datetime.now()
    recipe = _MCKESSON_STATUS_RECIPES[status].copy()

    # Override dea_class from recipe if specified
    if "dea_class" in recipe:
        dea_class = recipe.pop("dea_class")
    if "refills_remaining" in recipe:
        refills_remaining = recipe.pop("refills_remaining")

    # Compute dates based on status
    if status == McKessonStatus.REFILLABLE:
        # Picked up long ago (> 5 days)
        release_dt = now - timedelta(days=90)
        recipe["released_to_patient_datetime"] = release_dt.strftime("%Y-%m-%dT%H:%M:%S.000-04:00")
        last_fill = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    elif status == McKessonStatus.RX_PICKED_UP:
        # Picked up recently (≤ 5 days)
        release_dt = now - timedelta(days=2)
        recipe["released_to_patient_datetime"] = release_dt.strftime("%Y-%m-%dT%H:%M:%S.000-04:00")
        last_fill = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    elif status == McKessonStatus.IN_QUEUE:
        last_fill = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    elif status == McKessonStatus.READY_FOR_PICKUP:
        last_fill = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        last_fill = (now - timedelta(days=60)).strftime("%Y-%m-%d")

    first_fill = (now - timedelta(days=180)).strftime("%Y-%m-%d")

    # Normalize DOB to YYYY-MM-DD for PerSe XML (McKesson adapter requires ISO date)
    dob_for_xml = patient_dob
    if len(patient_dob) == 8 and patient_dob.isdigit():
        # Convert YYYYMMDD → YYYY-MM-DD
        dob_for_xml = f"{patient_dob[:4]}-{patient_dob[4:6]}-{patient_dob[6:8]}"

    rx = McKessonRx(
        rx_number=rx_number,
        drug_name=drug_name,
        store_number=store_number,
        patient_first=patient_first,
        patient_last=patient_last,
        patient_dob=dob_for_xml,
        patient_phone=patient_phone,
        refills_remaining=refills_remaining,
        refills_authorized=refills_authorized,
        days_supply=days_supply,
        quantity=days_supply,
        copay=copay,
        sig_text="TAKE ONE TABLET BY MOUTH DAILY",
        dea_class=dea_class,
        expiration_date="2028-12-31",
        is_ready=recipe.get("is_ready", False),
        is_refillable=recipe.get("is_refillable", True),
        refill_qty=days_supply,
        not_ready_reason_code=recipe.get("not_ready_reason_code"),
        released_to_patient_datetime=recipe.get("released_to_patient_datetime"),
        not_refillable_reason_code=recipe.get("not_refillable_reason_code"),
        is_doctor_auth_allowed=recipe.get("is_doctor_auth_allowed", "false"),
        patient_pay_amount=recipe.get("patient_pay_amount"),
        first_fill_date=first_fill,
        last_fill_date=last_fill,
    )

    # Build P360 patient if requested
    p360_patient = None
    if include_p360:
        phone_digits = patient_phone.replace("-", "").replace(" ", "")
        dob_p360 = patient_dob.replace("-", "")
        fill_date_p360 = last_fill.replace("-", "")
        p360_patient = {
            "clientId": client_id,
            "storeId": store_id,
            "storeNpi": store_npi,
            "atebPatientId": int(rx_number) if rx_number.isdigit() else 99001,
            "dateOfBirth": dob_p360,
            "name": {
                "firstName": patient_first,
                "lastName": patient_last,
            },
            "phone": {
                "primary": phone_digits,
            },
            "search": {
                "lastNameUpper": patient_last.upper(),
                "firstNameUpper": patient_first.upper(),
                "dob": dob_p360,
                "phoneNumber": phone_digits,
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
                        "medicationName": drug_name,
                        "ndc": rx.ndc,
                    },
                    "rxNum": rx_number,
                    "fillDate": fill_date_p360,
                    "daysSupply": days_supply,
                    "refillsRemaining": int(refills_remaining),
                    "originalRefillsAuth": int(refills_authorized),
                    "rxStatus": "OPEN",
                }
            ],
        }

    return McKessonScenario(
        rx=rx,
        status=status,
        p360_patient=p360_patient,
        notes=f"McKesson {status.value} — {drug_name}",
    )


def _build_mckesson_rx_info_xml(rx: McKessonRx) -> str:
    """Build the PerSe RxInfoRsp XML for a McKesson prescription."""
    # Build FillInfo children
    fill_children = ""

    if rx.is_ready and rx.patient_pay_amount:
        fill_children += f'          <ns2:ReadyInfo PatientPayAmount="{rx.patient_pay_amount}" />\n'

    if not rx.is_ready and rx.not_ready_reason_code:
        release_attr = ""
        if rx.released_to_patient_datetime:
            release_attr = f' ReleasedToPatientDateTime="{rx.released_to_patient_datetime}"'
        fill_children += f'          <ns2:NotReadyInfo{release_attr} NotReadyReasonCode="{rx.not_ready_reason_code}" />\n'

    if not rx.is_refillable and rx.not_refillable_reason_code:
        fill_children += f'          <ns2:NotRefillableInfo NotRefillableReasonCode="{rx.not_refillable_reason_code}" IsDoctorAuthAllowed="{rx.is_doctor_auth_allowed}" />\n'

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<ns1:Envelope xmlns:ns1="http://schemas.xmlsoap.org/soap/envelope/">
  <ns1:Header>
    <ns2:MsgHeader xmlns:ns2="http://www.techrx.com/trexone/1_1" TimeStamp="{datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000-04:00")}" SourceID="TRexOne" Version="1.1" MsgName="RxInfoRsp" DestinationID="Ateb" MsgID="1{rx.rx_number}" />
  </ns1:Header>
  <ns1:Body>
    <ns2:RxInfoRsp xmlns:ns2="http://www.techrx.com/trexone/1_1">
      <ns2:RxInfoFound StoreNum="{rx.store_number}" RxNum="{rx.rx_number}">
        <ns2:PatientInfo>
          <ns3:LastName xmlns:ns3="http://www.techrx.com/trexone/1_0">{rx.patient_last}</ns3:LastName>
          <ns3:FirstName xmlns:ns3="http://www.techrx.com/trexone/1_0">{rx.patient_first}</ns3:FirstName>
          <ns3:DateOfBirth xmlns:ns3="http://www.techrx.com/trexone/1_0">{rx.patient_dob}</ns3:DateOfBirth>
          <ns3:PrimaryPhone xmlns:ns3="http://www.techrx.com/trexone/1_0">{rx.patient_phone}</ns3:PrimaryPhone>
          <ns3:ExternalPatientID xmlns:ns3="http://www.techrx.com/trexone/1_0">{rx.patient_id}</ns3:ExternalPatientID>
          <ns3:Extension xmlns:ns3="http://www.techrx.com/trexone/1_0">
            <ns3:Address type="primary" State="NC" City="RALEIGH" Zip="27604" Line1="100 TEST ST" />
            <ns3:SSN />
            <ns3:Gender>M</ns3:Gender>
          </ns3:Extension>
        </ns2:PatientInfo>
        <ns2:FillInfo IsReady="{str(rx.is_ready).lower()}" RefillQty="{rx.refill_qty}" IsRefillable="{str(rx.is_refillable).lower()}">
{fill_children}          <ns2:Extension>
            <ns2:NextRefillDate>1900-01-01</ns2:NextRefillDate>
            <ns2:PrescriberInfo LastName="{rx.prescriber_last}" FirstName="{rx.prescriber_first}" DEANumber="1234567" />
            <ns2:RxInfo RefillsRemaining="{rx.refills_remaining}" RefillsAuthorized="{rx.refills_authorized}" ExpirationDate="{rx.expiration_date}" SigText="{rx.sig_text}" DrugName="{rx.drug_name}"{f' DEAClass="{rx.dea_class}"' if rx.dea_class and rx.dea_class != "0" else ""}>
              <ns3:FirstFill xmlns:ns3="http://www.techrx.com/trexone/1_0" DaysSupply="{rx.days_supply}" FillNumber="0" FillDate="{rx.first_fill_date}" Quantity="{rx.quantity}" />
              <ns3:LastFill xmlns:ns3="http://www.techrx.com/trexone/1_0" DaysSupply="{rx.days_supply}" FillNumber="{rx.last_fill_number}" FillDate="{rx.last_fill_date}" Quantity="{rx.quantity}" />
            </ns2:RxInfo>
            <ns2:DispensedNDC>{rx.ndc}</ns2:DispensedNDC>
          </ns2:Extension>
        </ns2:FillInfo>
        <ns2:ProductInfo NDC="{rx.ndc}" QtyOnHand="50.0" />
      </ns2:RxInfoFound>
    </ns2:RxInfoRsp>
  </ns1:Body>
</ns1:Envelope>'''
    return xml


def _build_mckesson_refill_response_xml(rx: McKessonRx) -> str:
    """Build the PerSe SubmitIVROrderRsp (refill success) XML."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:trex1_0="http://www.techrx.com/trexone/1_0"
    xmlns:trex1_1="http://www.techrx.com/trexone/1_1">
  <soap:Header>
    <trex1_1:MsgHeader
        MsgName="GenericSuccessRsp"
        Version="1.0"
        SourceID="TestServlet"
        DestinationID="Ateb"
        MsgID="1" />
  </soap:Header>
  <soap:Body>
    <trex1_0:GenericSuccessRsp />
  </soap:Body>
</soap:Envelope>'''


def upload_mckesson_rx(rx: McKessonRx) -> None:
    """Upload McKesson/PerSe response files to the simulator.

    Creates RxInfoRsp and SubmitIVROrderRsp files at PerSe/{Type}{rx_number}.xml.
    """
    files = {
        f"PerSe/RxInfoRsp{rx.rx_number}.xml": _build_mckesson_rx_info_xml(rx),
        f"PerSe/SubmitIVROrderRsp{rx.rx_number}.xml": _build_mckesson_refill_response_xml(rx),
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
        "Uploaded McKesson sim data for rx %s (%s) — %s/%s",
        rx.rx_number,
        rx.drug_name,
        "ready" if rx.is_ready else "not-ready",
        "refillable" if rx.is_refillable else "not-refillable",
    )


def delete_mckesson_rx(rx_number: str) -> None:
    """Delete McKesson/PerSe response files from the simulator."""
    files = [
        f"PerSe/RxInfoRsp{rx_number}.xml",
        f"PerSe/SubmitIVROrderRsp{rx_number}.xml",
    ]

    with httpx.Client(verify=False, timeout=10.0) as client:
        for file_path in files:
            url = f"{SIM_BASE_URL}?action=delete&file_path={file_path}"
            client.get(url)

    logger.info("Deleted McKesson sim data for rx %s", rx_number)


def upload_mckesson_scenario(scenario: McKessonScenario, upload_p360: bool = True) -> None:
    """Upload a McKesson scenario to the simulator and optionally P360."""
    upload_mckesson_rx(scenario.rx)

    if upload_p360 and scenario.p360_patient:
        from tests.helpers_p360 import ensure_patient_with_rx
        ensure_patient_with_rx(scenario.p360_patient)
        logger.info(
            "Uploaded P360 patient for %s %s (McKesson)",
            scenario.rx.patient_first,
            scenario.rx.patient_last,
        )


def delete_mckesson_scenario(scenario: McKessonScenario, delete_p360: bool = False) -> None:
    """Delete a McKesson scenario's sim data."""
    delete_mckesson_rx(scenario.rx.rx_number)

    if delete_p360 and scenario.p360_patient:
        from tests.helpers_p360 import delete_patient
        delete_patient(
            client_id=scenario.p360_patient["clientId"],
            phone=scenario.p360_patient["phone"]["primary"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# McKesson convenience one-liners
# ──────────────────────────────────────────────────────────────────────────────


def create_mckesson_ready_for_pickup(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson READY_FOR_PICKUP scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.READY_FOR_PICKUP, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_in_queue(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson IN_QUEUE scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.IN_QUEUE, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_refillable(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson REFILLABLE scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.REFILLABLE, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_picked_up(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson RX_PICKED_UP scenario (recently picked up)."""
    scenario = build_mckesson_scenario(status=McKessonStatus.RX_PICKED_UP, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_controlled(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson CONTROLLED_SUBSTANCE scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.CONTROLLED_SUBSTANCE, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_too_soon(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson TOO_SOON scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.TOO_SOON, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_expired(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson NOT_REFILLABLE_EXPIRED scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.NOT_REFILLABLE_EXPIRED, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


def create_mckesson_no_refills(rx_number: str, **kwargs) -> McKessonScenario:
    """Create and upload a McKesson NOT_REFILLABLE_NO_REFILLS scenario."""
    scenario = build_mckesson_scenario(status=McKessonStatus.NOT_REFILLABLE_NO_REFILLS, rx_number=rx_number, **kwargs)
    upload_mckesson_scenario(scenario)
    return scenario


# List of McKesson statuses available for the UI
MCKESSON_AVAILABLE_STATUSES = list(McKessonStatus)


# =============================================================================
# LIBERTY PMS BUILDER
# =============================================================================
# Liberty uses JSON files served by WireMock (not the Tomcat PMS simulator).
# Upload mechanism: PUT to WireMock admin API at /__admin/files/liberty/
# Three files per Rx:
#   - libertyquery{rxnum}.json  (GET /libertypms/prescription/{rxnum})
#   - libertystatus{rxnum}.json (GET /libertypms/refill/{rxnum})
#   - libertyrefill{rxnum}.json (POST /libertypms/refill)
# =============================================================================

WIREMOCK_BASE_URL = "https://ivr-mock-svcs.pc.q.awscloud.private"
WIREMOCK_FILES_API = f"{WIREMOCK_BASE_URL}/__admin/files"


class LibertyStatus(str, Enum):
    """Liberty PMS statuses that the builder can produce."""
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    IN_QUEUE = "IN_QUEUE"
    REFILLABLE = "REFILLABLE"
    RX_PICKED_UP = "RX_PICKED_UP"
    SHIPPED = "SHIPPED"
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    TOO_SOON = "TOO_SOON"
    NOT_REFILLABLE_NO_REFILLS = "NOT_REFILLABLE_NO_REFILLS"
    NOT_REFILLABLE_EXPIRED = "NOT_REFILLABLE_EXPIRED"
    ON_HOLD = "ON_HOLD"


@dataclass
class LibertyRx:
    """Represents a Liberty prescription with all fields needed for JSON generation."""
    rx_number: str
    patient_first: str = "STATUS"
    patient_last: str = "TESTPATIENT"
    patient_phone: str = "5550561001"
    patient_dob: str = "1985-01-15"  # YYYY-MM-DD
    drug_name: str = "LISINOPRIL 10MG TAB"
    drug_ndc: str = "00591073101"
    drug_schedule: str = ""  # empty = non-controlled, "2" = Schedule II
    prescriber_first: str = "JOHN"
    prescriber_last: str = "SMITH"
    prescriber_npi: str = "1234567890"
    # Rx details
    refills_authorized: int = 5
    last_refill_number: int = 1
    days_supply: int = 30
    dispense_quantity: int = 30
    copay: float = 10.0
    # Fill status - last fill in the fills array
    last_fill_status_code: str = "Verified"  # Entered, Counted, Verified, PickedUp, Delivered, Shipped
    last_fill_date: str = ""  # YYYY-MM-DD, auto-calculated if empty
    pickup_date: str | None = None  # YYYY-MM-DD or None
    # Status file fields
    status_status: str = "Refillable"  # Refillable, No_Refills, Expired, Too_Early, On_Hold
    status_last_fill_status: str = "Picked_Up"  # Ready, In_Process, Shipped, Picked_Up, Delivered
    status_last_fill_date: str = ""  # M/D/YYYY format for status file
    # Computed
    refills_remaining: int = 4
    available_quantity: int = 90
    written_date: str = ""
    refill_until_date: str = ""


@dataclass
class LibertyScenario:
    """A complete Liberty test scenario including all JSON content."""
    rx: LibertyRx
    query_json: str  # libertyquery content
    status_json: str  # libertystatus content
    refill_json: str  # libertyrefill content
    p360_patient: dict | None = None


def _normalize_dob_to_liberty(dob: str) -> str:
    """Convert various DOB formats to YYYY-MM-DD for Liberty."""
    dob = dob.strip()
    if len(dob) == 8 and dob.isdigit():
        # YYYYMMDD
        return f"{dob[:4]}-{dob[4:6]}-{dob[6:8]}"
    if "T" in dob:
        return dob.split("T")[0]
    if "-" in dob and len(dob) == 10:
        return dob
    return dob


def build_liberty_scenario(
    status: LibertyStatus,
    rx_number: str,
    patient_first: str = "STATUS",
    patient_last: str = "TESTPATIENT",
    patient_phone: str = "5550561001",
    patient_dob: str = "19850115",
    drug_name: str = "LISINOPRIL 10MG TAB",
    drug_ndc: str = "00591073101",
    store_number: str = "70050001",
    client_id: int = 8000,
    copay: float = 10.0,
    days_supply: int = 30,
    refills_remaining: int = 4,
    refills_authorized: int = 5,
    include_p360: bool = True,
) -> LibertyScenario:
    """Build a Liberty scenario that will resolve to the desired status.

    The Liberty adapter maps JSON fields to RxInfoV2DTO, then RxStatusUtils
    determines the final status based on the same logic as PDX/McKesson.
    """
    now = datetime.now()
    dob_formatted = _normalize_dob_to_liberty(patient_dob)

    # Defaults
    last_fill_status_code = "Verified"
    status_status = "Refillable"
    status_last_fill_status = "Picked_Up"
    drug_schedule = ""
    pickup_date = None
    last_refill_number = 1

    # Calculate dates based on desired status
    if status == LibertyStatus.READY_FOR_PICKUP:
        # Last fill statusCode = "Verified" → READY_FOR_PICKUP in INFO
        # Status file lastFill.status = "Ready"
        last_fill_status_code = "Verified"
        status_status = "Refillable"
        status_last_fill_status = "Ready"
        fill_date = now - timedelta(days=1)
        pickup_date = None

    elif status == LibertyStatus.IN_QUEUE:
        # Last fill statusCode = "Entered" → IN_QUEUE
        # Status file lastFill.status = "In_Process"
        last_fill_status_code = "Entered"
        status_status = "Refillable"
        status_last_fill_status = "In_Process"
        fill_date = now - timedelta(days=1)
        pickup_date = None

    elif status == LibertyStatus.REFILLABLE:
        # PickedUp long ago (> daysAfterPickup=5)
        last_fill_status_code = "PickedUp"
        status_status = "Refillable"
        status_last_fill_status = "Picked_Up"
        fill_date = now - timedelta(days=days_supply + 10)
        pickup_date = (fill_date + timedelta(days=2)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.RX_PICKED_UP:
        # PickedUp recently (≤ daysAfterPickup=5)
        last_fill_status_code = "PickedUp"
        status_status = "Refillable"
        status_last_fill_status = "Picked_Up"
        fill_date = now - timedelta(days=2)
        pickup_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.SHIPPED:
        # Delivered/Shipped
        last_fill_status_code = "Delivered"
        status_status = "Refillable"
        status_last_fill_status = "Delivered"
        fill_date = now - timedelta(days=3)
        pickup_date = None

    elif status == LibertyStatus.CONTROLLED_SUBSTANCE:
        # Schedule 2 drug, otherwise refillable
        last_fill_status_code = "PickedUp"
        status_status = "Refillable"
        status_last_fill_status = "Picked_Up"
        drug_schedule = "2"
        fill_date = now - timedelta(days=days_supply + 10)
        pickup_date = (fill_date + timedelta(days=2)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.TOO_SOON:
        # Fill very recent, low % consumed
        last_fill_status_code = "PickedUp"
        status_status = "Too_Early"
        status_last_fill_status = "Picked_Up"
        fill_date = now - timedelta(days=2)
        pickup_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.NOT_REFILLABLE_NO_REFILLS:
        # No refills remaining
        last_fill_status_code = "PickedUp"
        status_status = "No_Refills"
        status_last_fill_status = "Picked_Up"
        refills_remaining = 0
        refills_authorized = last_refill_number
        fill_date = now - timedelta(days=30)
        pickup_date = (fill_date + timedelta(days=1)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.NOT_REFILLABLE_EXPIRED:
        # Rx expired
        last_fill_status_code = "PickedUp"
        status_status = "Expired"
        status_last_fill_status = "Picked_Up"
        fill_date = now - timedelta(days=365)
        pickup_date = (fill_date + timedelta(days=1)).strftime("%Y-%m-%d")

    elif status == LibertyStatus.ON_HOLD:
        # On hold
        last_fill_status_code = "PickedUp"
        status_status = "On_Hold"
        status_last_fill_status = "Picked_Up"
        fill_date = now - timedelta(days=10)
        pickup_date = None

    else:
        raise ValueError(f"Unsupported Liberty status: {status}")

    fill_date_str = fill_date.strftime("%Y-%m-%d")
    written_date = (fill_date - timedelta(days=30)).strftime("%Y-%m-%d")
    refill_until_date = (now + timedelta(days=365)).strftime("%Y-%m-%d")

    # Status file uses M/D/YYYY for dates
    status_fill_date_str = f"{fill_date.month}/{fill_date.day}/{fill_date.year}"
    status_refill_until = f"{(now + timedelta(days=365)).month}/{(now + timedelta(days=365)).day}/{(now + timedelta(days=365)).year}"

    dispense_quantity = days_supply  # typically matches
    available_quantity = refills_remaining * dispense_quantity if refills_remaining > 0 else 0

    rx = LibertyRx(
        rx_number=rx_number,
        patient_first=patient_first,
        patient_last=patient_last,
        patient_phone=patient_phone,
        patient_dob=dob_formatted,
        drug_name=drug_name,
        drug_ndc=drug_ndc,
        drug_schedule=drug_schedule,
        prescriber_first="JOHN",
        prescriber_last="SMITH",
        prescriber_npi="1234567890",
        refills_authorized=refills_authorized,
        last_refill_number=last_refill_number,
        days_supply=days_supply,
        dispense_quantity=dispense_quantity,
        copay=copay,
        last_fill_status_code=last_fill_status_code,
        last_fill_date=fill_date_str,
        pickup_date=pickup_date,
        status_status=status_status,
        status_last_fill_status=status_last_fill_status,
        status_last_fill_date=status_fill_date_str,
        refills_remaining=refills_remaining,
        available_quantity=available_quantity,
        written_date=written_date,
        refill_until_date=refill_until_date,
    )

    query_json = _build_liberty_query_json(rx)
    status_json = _build_liberty_status_json(rx, status_refill_until)
    refill_json = _build_liberty_refill_json(rx)

    p360_patient = None
    if include_p360:
        p360_patient = _build_p360_patient(
            patient_first=patient_first,
            patient_last=patient_last,
            patient_phone=patient_phone,
            patient_dob=patient_dob,
            rx_number=rx_number,
            drug_name=drug_name,
            days_supply=days_supply,
            store_number=store_number,
            client_id=client_id,
        )

    return LibertyScenario(
        rx=rx,
        query_json=query_json,
        status_json=status_json,
        refill_json=refill_json,
        p360_patient=p360_patient,
    )


def _build_liberty_query_json(rx: LibertyRx) -> str:
    """Build the libertyquery JSON file content."""
    import json

    # Build fill history - single fill entry (the last one)
    fill = {
        "RefillNumber": rx.last_refill_number,
        "DispenseDate": rx.last_fill_date,
        "DispenseQuantity": rx.dispense_quantity,
        "DaysSupply": rx.days_supply,
        "DrugDispensed": {
            "Id": "DRUG1",
            "NDC": rx.drug_ndc,
            "Name": rx.drug_name,
            "IsCompound": 0,
            "IsVaccine": 0,
            "Manufacturer": "GENERIC PHARMA",
            "Schedule": rx.drug_schedule,
            "Imprint": "",
            "Warnings": [],
            "CustomField1": "",
            "CustomField2": "",
            "CustomField3": "",
            "CustomField4": "",
            "Strength": "",
            "Form": "TAB",
        },
        "SIG": "TAKE ONE TABLET BY MOUTH DAILY",
        "DAW": "0",
        "RphInitials": "RP",
        "RphName": "Robert Pharmacist",
        "Status": rx.last_fill_status_code,
        "StatusCode": rx.last_fill_status_code,
        "StatusCodeDate": f"{rx.last_fill_date} 10:00:00",
        "PatientPay": rx.copay,
        "ExpirationDate": (datetime.strptime(rx.last_fill_date, "%Y-%m-%d") + timedelta(days=rx.days_supply)).strftime("%Y-%m-%d"),
        "LotNumber": "",
        "WorkflowLocation": None,
        "Cost": 5.0,
        "ACQ": 5.0,
        "AWP": 50.0,
        "UsualAndCustomary": 55.0,
        "Doses": None,
        "Primary": None,
        "Secondary": None,
        "LastModified": f"{rx.last_fill_date} 10:00:00",
        "PickupDate": f"{rx.pickup_date} 14:00:00" if rx.pickup_date else None,
    }

    query = {
        "ScriptNumber": int(rx.rx_number),
        "WrittenDate": rx.written_date,
        "RefillsAuthorized": rx.refills_authorized,
        "LastRefillNumber": rx.last_refill_number,
        "RefillUntilDate": rx.refill_until_date,
        "FullDispenseQuantity": rx.dispense_quantity,
        "AuthorizedQuantity": rx.refills_authorized * rx.dispense_quantity,
        "AvailableQuantity": rx.available_quantity,
        "Origin": "3",
        "Patient": {
            "Id": f"PAT{rx.rx_number}",
            "ExternalId": "",
            "AccountNumber": 0,
            "ChargeCode": "N",
            "Name": {
                "FirstName": rx.patient_first.upper(),
                "MiddleInitial": "",
                "LastName": rx.patient_last.upper(),
            },
            "Address": {
                "Street1": "123 TEST ST",
                "Street2": "",
                "City": "TESTVILLE",
                "State": "TX",
                "Zip": "75001",
            },
            "BirthDate": rx.patient_dob,
            "Gender": "M",
            "SSN": "",
            "DriversLicenseNumber": "",
            "Phone": rx.patient_phone,
            "PhoneType": "H",
            "Phone2": "",
            "Phone2Type": None,
            "IsTextOk": 0,
            "Email": "",
            "Language": "en_US",
            "CustomField1": "",
            "CustomField2": "",
            "CustomField3": "",
            "CustomField4": "",
            "Allergies": [],
            "NursingHome": None,
        },
        "DrugPrescribed": {
            "Id": "DRUG1",
            "NDC": rx.drug_ndc,
            "Name": rx.drug_name,
            "IsCompound": 0,
            "IsVaccine": 0,
            "Manufacturer": "GENERIC PHARMA",
            "Schedule": rx.drug_schedule,
            "Imprint": "",
            "Warnings": [],
            "CustomField1": "",
            "CustomField2": "",
            "CustomField3": "",
            "CustomField4": "",
            "Strength": "",
            "Form": "TAB",
        },
        "Prescriber": {
            "Id": "DOC001",
            "Name": {
                "FirstName": rx.prescriber_first,
                "MiddleInitial": "",
                "LastName": rx.prescriber_last,
            },
            "Clinic": "TEST CLINIC",
            "Address": {
                "Street1": "456 MEDICAL DR",
                "Street2": "",
                "City": "TESTVILLE",
                "State": "TX",
                "Zip": "75001",
            },
            "Phone": "5551234567",
            "Fax": "5551234568",
            "NPI": rx.prescriber_npi,
            "DEA": "AS1234567",
            "CustomField1": "",
            "CustomField2": "",
            "CustomField3": "",
            "CustomField4": "",
        },
        "QueueName": "",
        "IsAutoFill": 0,
        "Location": None,
        "Status": None,
        "StatusCode": None,
        "Fills": [fill],
    }

    return json.dumps(query, indent=2)


def _build_liberty_status_json(rx: LibertyRx, refill_until: str) -> str:
    """Build the libertystatus JSON file content."""
    import json

    status = {
        "ScriptNumber": int(rx.rx_number),
        "Status": rx.status_status,
        "RefillsAuthorized": rx.refills_authorized,
        "LastRefillNumber": rx.last_refill_number,
        "RefillUntilDate": refill_until,
        "FullDispenseQuantity": rx.dispense_quantity,
        "AuthorizedQuantity": rx.refills_authorized * rx.dispense_quantity,
        "AvailableQuantity": rx.available_quantity,
        "LastFill": {
            "RefillNumber": rx.last_refill_number,
            "DispenseDate": rx.status_last_fill_date,
            "DispenseQuantity": rx.dispense_quantity,
            "DaysSupply": rx.days_supply,
            "Status": rx.status_last_fill_status,
        },
    }

    return json.dumps(status, indent=2)


def _build_liberty_refill_json(rx: LibertyRx) -> str:
    """Build the libertyrefill JSON file content (always success)."""
    import json

    refill = [{"ScriptNumber": rx.rx_number, "Status": "Success"}]
    return json.dumps(refill, indent=2)


def upload_liberty_rx(rx_number: str, query_json: str, status_json: str, refill_json: str) -> None:
    """Upload Liberty JSON files to WireMock via the admin files API."""
    import requests

    files_to_upload = [
        (f"liberty/libertyquery{rx_number}.json", query_json),
        (f"liberty/libertystatus{rx_number}.json", status_json),
        (f"liberty/libertyrefill{rx_number}.json", refill_json),
    ]

    for file_path, content in files_to_upload:
        url = f"{WIREMOCK_FILES_API}/{file_path}"
        resp = requests.put(url, data=content.encode("utf-8"),
                            headers={"Content-Type": "application/octet-stream"},
                            verify=False, timeout=10)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to upload {file_path}: HTTP {resp.status_code} — {resp.text}"
            )


def delete_liberty_rx(rx_number: str) -> None:
    """Delete Liberty JSON files from WireMock."""
    import requests

    files_to_delete = [
        f"liberty/libertyquery{rx_number}.json",
        f"liberty/libertystatus{rx_number}.json",
        f"liberty/libertyrefill{rx_number}.json",
    ]

    for file_path in files_to_delete:
        url = f"{WIREMOCK_FILES_API}/{file_path}"
        resp = requests.delete(url, verify=False, timeout=10)
        # 200 or 404 are both fine (file might not exist)
        if resp.status_code not in (200, 204, 404):
            raise RuntimeError(
                f"Failed to delete {file_path}: HTTP {resp.status_code} — {resp.text}"
            )


def upload_liberty_scenario(scenario: LibertyScenario, upload_p360: bool = True) -> None:
    """Upload all files for a Liberty scenario."""
    upload_liberty_rx(
        scenario.rx.rx_number,
        scenario.query_json,
        scenario.status_json,
        scenario.refill_json,
    )
    if upload_p360 and scenario.p360_patient:
        _upsert_p360_patient(scenario.p360_patient)


def delete_liberty_scenario(scenario: LibertyScenario, delete_p360: bool = False) -> None:
    """Delete all files for a Liberty scenario."""
    delete_liberty_rx(scenario.rx.rx_number)
    if delete_p360 and scenario.p360_patient:
        _delete_p360_patient(scenario.p360_patient)


# --- Liberty convenience one-liners ---

def create_liberty_ready_for_pickup(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty READY_FOR_PICKUP scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.READY_FOR_PICKUP, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_in_queue(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty IN_QUEUE scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.IN_QUEUE, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_refillable(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty REFILLABLE scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.REFILLABLE, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_picked_up(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty RX_PICKED_UP scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.RX_PICKED_UP, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_shipped(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty SHIPPED scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.SHIPPED, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_controlled(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty CONTROLLED_SUBSTANCE scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.CONTROLLED_SUBSTANCE, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_too_soon(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty TOO_SOON scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.TOO_SOON, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_no_refills(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty NOT_REFILLABLE_NO_REFILLS scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.NOT_REFILLABLE_NO_REFILLS, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_expired(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty NOT_REFILLABLE_EXPIRED scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.NOT_REFILLABLE_EXPIRED, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


def create_liberty_on_hold(rx_number: str, **kwargs) -> LibertyScenario:
    """Create and upload a Liberty ON_HOLD scenario."""
    scenario = build_liberty_scenario(status=LibertyStatus.ON_HOLD, rx_number=rx_number, **kwargs)
    upload_liberty_scenario(scenario)
    return scenario


# List of Liberty statuses available for the UI
LIBERTY_AVAILABLE_STATUSES = list(LibertyStatus)


# =============================================================================
# EPIC 2018 PMS BUILDER
# =============================================================================
# Epic uses SOAP XML files served by WireMock (same host as Liberty).
# Upload mechanism: PUT to WireMock admin API at /__admin/files/epic/2018/soap11/
# Two files per Rx:
#   - GetPrescriptionInfoResponse-{rxnum}-{ncpdpId}.xml (INFO)
#   - RequestFillsResponse-{rxnum}-{ncpdpId}.xml (REFILL)
# Note: Epic has mergeInfoStatus=false — only one INFO call, no separate STATUS.
# =============================================================================


class EpicStatus(str, Enum):
    """Epic PMS statuses that the builder can produce."""
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    IN_QUEUE = "IN_QUEUE"
    REFILLABLE = "REFILLABLE"
    RX_PICKED_UP = "RX_PICKED_UP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CONTROLLED_SUBSTANCE = "CONTROLLED_SUBSTANCE"
    TOO_SOON = "TOO_SOON"
    NOT_REFILLABLE = "NOT_REFILLABLE"
    NOT_REFILLABLE_EXPIRED = "NOT_REFILLABLE_EXPIRED"
    NOT_REFILLABLE_NO_REFILLS = "NOT_REFILLABLE_NO_REFILLS"
    WAITING_FOR_PRESCRIBER = "WAITING_FOR_PRESCRIBER"
    TRANSFERRED = "TRANSFERRED"


@dataclass
class EpicRx:
    """Represents an Epic prescription with all fields needed for SOAP XML generation."""
    rx_number: str
    prescription_id: str = ""  # Internal Epic ID (defaults to rx_number)
    ncpdp_id: str = "9759001"  # Pharmacy NCPDP ID (store)
    patient_first: str = "STATUS"
    patient_last: str = "TESTPATIENT"
    patient_phone: str = "555-555-5555"
    patient_dob: str = "1985-01-15"  # YYYY-MM-DD
    drug_name: str = "lisinopril 10 MG tablet"
    drug_ndc: str = "0591-0730-01"
    dea_code: str = "CV"  # CI, CII, CIII, CIV, CV
    dea_code_number: str = "5"  # 1-5
    prescriber_name: str = "Jason Md (Ser) Fry, MD"
    # Status flags
    is_fillable: str = "true"
    has_fill_in_progress: str = "false"
    has_fill_ready_for_pickup: str = "false"
    reason_not_fillable: str = "0"
    reason_not_rarable: str = "0"
    # Fill details
    fill_status: str = "PendingFill"  # PendingFill, READY_TO_DISPENSE, DISPENSED, SHIPPED, DELIVERED
    fill_day_supply: int = 30
    fill_copay: str = "10.00"
    fills_remaining: int = 11
    # Dates
    first_dispensed: str = ""
    last_dispensed: str = ""
    last_dispensed_day_supply: int = 30
    dispensed_on: str = ""  # Fill.DispensedOn — xsi:nil if not dispensed
    filled_on: str = ""
    end_date: str = ""
    sig: str = "Take by mouth."


@dataclass
class EpicScenario:
    """A complete Epic test scenario including all XML content."""
    rx: EpicRx
    info_xml: str  # GetPrescriptionInfoResponse content
    refill_xml: str  # RequestFillsResponse content
    p360_patient: dict | None = None


def build_epic_scenario(
    status: EpicStatus,
    rx_number: str,
    ncpdp_id: str = "9759001",
    patient_first: str = "STATUS",
    patient_last: str = "TESTPATIENT",
    patient_phone: str = "555-555-5555",
    patient_dob: str = "19850115",
    drug_name: str = "lisinopril 10 MG tablet",
    drug_ndc: str = "0591-0730-01",
    store_number: str = "9759001",
    client_id: int = 9001,
    copay: float = 10.0,
    days_supply: int = 30,
    refills_remaining: int = 11,
    include_p360: bool = True,
) -> EpicScenario:
    """Build an Epic scenario that will resolve to the desired status."""
    now = datetime.now()
    dob_formatted = _normalize_dob_to_liberty(patient_dob)  # reuse YYYY-MM-DD normalizer

    # Defaults
    is_fillable = "true"
    has_fill_in_progress = "false"
    has_fill_ready_for_pickup = "false"
    reason_not_fillable = "0"
    reason_not_rarable = "0"
    fill_status = "PendingFill"
    dea_code = "CV"
    dea_code_number = "5"
    dispensed_on = ""  # xsi:nil when empty

    if status == EpicStatus.READY_FOR_PICKUP:
        has_fill_ready_for_pickup = "true"
        fill_status = "READY_TO_DISPENSE"
        filled_on = (now - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on

    elif status == EpicStatus.IN_QUEUE:
        has_fill_in_progress = "true"
        fill_status = "PendingFill"
        filled_on = (now - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on

    elif status == EpicStatus.REFILLABLE:
        # Fillable, dispensed long ago (> daysAfterPickup=5)
        is_fillable = "true"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=days_supply + 10)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=days_supply + 8)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.RX_PICKED_UP:
        # Dispensed recently (≤ 5 days)
        is_fillable = "true"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=1)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.SHIPPED:
        is_fillable = "true"
        fill_status = "SHIPPED"
        filled_on = (now - timedelta(days=3)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=2)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.DELIVERED:
        is_fillable = "true"
        fill_status = "DELIVERED"
        filled_on = (now - timedelta(days=3)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=1)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.CONTROLLED_SUBSTANCE:
        # Schedule II, otherwise fillable + dispensed long ago
        is_fillable = "true"
        fill_status = "DISPENSED"
        dea_code = "CII"
        dea_code_number = "2"
        filled_on = (now - timedelta(days=days_supply + 10)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=days_supply + 8)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.TOO_SOON:
        # ReasonNotFillable=11 → TOO_SOON
        is_fillable = "false"
        reason_not_fillable = "11"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=1)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.NOT_REFILLABLE:
        # ReasonNotFillable=1 → NOT_REFILLABLE
        is_fillable = "false"
        reason_not_fillable = "1"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=30)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=29)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.NOT_REFILLABLE_EXPIRED:
        # ReasonNotFillable=10 → EXPIRED
        is_fillable = "false"
        reason_not_fillable = "10"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=365)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=364)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.NOT_REFILLABLE_NO_REFILLS:
        # ReasonNotFillable=7 → OUT_OF_REFILLS
        is_fillable = "false"
        reason_not_fillable = "7"
        refills_remaining = 0
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=30)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=29)).strftime("%Y-%m-%dT14:00:00")

    elif status == EpicStatus.WAITING_FOR_PRESCRIBER:
        # ReasonNotRARable=3 → WAITING_FOR_PRESCRIBER
        is_fillable = "false"
        reason_not_rarable = "3"
        fill_status = "PendingFill"
        filled_on = (now - timedelta(days=5)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on

    elif status == EpicStatus.TRANSFERRED:
        # ReasonNotRARable=9 → TRANSFERRED
        is_fillable = "false"
        reason_not_rarable = "9"
        fill_status = "DISPENSED"
        filled_on = (now - timedelta(days=60)).strftime("%Y-%m-%dT10:00:00")
        last_dispensed = filled_on
        dispensed_on = (now - timedelta(days=59)).strftime("%Y-%m-%dT14:00:00")

    else:
        raise ValueError(f"Unsupported Epic status: {status}")

    first_dispensed = (now - timedelta(days=180)).strftime("%Y-%m-%dT10:00:00")
    end_date = (now + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z")

    rx = EpicRx(
        rx_number=rx_number,
        prescription_id=rx_number,
        ncpdp_id=ncpdp_id,
        patient_first=patient_first,
        patient_last=patient_last,
        patient_phone=patient_phone,
        patient_dob=f"{dob_formatted}T00:00:00Z",
        drug_name=drug_name,
        drug_ndc=drug_ndc,
        dea_code=dea_code,
        dea_code_number=dea_code_number,
        prescriber_name="Jason Md (Ser) Fry, MD",
        is_fillable=is_fillable,
        has_fill_in_progress=has_fill_in_progress,
        has_fill_ready_for_pickup=has_fill_ready_for_pickup,
        reason_not_fillable=reason_not_fillable,
        reason_not_rarable=reason_not_rarable,
        fill_status=fill_status,
        fill_day_supply=days_supply,
        fill_copay=f"{copay:.2f}",
        fills_remaining=refills_remaining,
        first_dispensed=first_dispensed,
        last_dispensed=last_dispensed,
        last_dispensed_day_supply=days_supply,
        dispensed_on=dispensed_on,
        filled_on=filled_on,
        end_date=end_date,
        sig="Take by mouth.",
    )

    info_xml = _build_epic_info_xml(rx)
    refill_xml = _build_epic_refill_xml(rx)

    p360_patient = None
    if include_p360:
        p360_patient = _build_p360_patient(
            patient_first=patient_first,
            patient_last=patient_last,
            patient_phone=patient_phone.replace("-", ""),
            patient_dob=patient_dob,
            rx_number=rx_number,
            drug_name=drug_name,
            days_supply=days_supply,
            store_number=store_number,
            client_id=client_id,
        )

    return EpicScenario(rx=rx, info_xml=info_xml, refill_xml=refill_xml, p360_patient=p360_patient)


def _build_epic_info_xml(rx: EpicRx) -> str:
    """Build the GetPrescriptionInfoResponse SOAP XML."""
    dispensed_on_element = (
        f'<web:DispensedOn>{rx.dispensed_on}</web:DispensedOn>'
        if rx.dispensed_on
        else '<web:DispensedOn xsi:nil="true"/>'
    )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:web="Epic.Clinical.Pharmacy.WebServices2018"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <soapenv:Header>
        <web:Action soapenv:mustUnderstand="1"/>
    </soapenv:Header>
    <soapenv:Body>
        <web:GetPrescriptionInfoResponse>
            <web:GetPrescriptionInfoResult>
                <web:Patient>
                    <web:City>Testville</web:City>
                    <web:Country>United States of America</web:Country>
                    <web:CreditCards/>
                    <web:CustomFields/>
                    <web:DateOfBirth>{rx.patient_dob}</web:DateOfBirth>
                    <web:DisplayName>{rx.patient_last}, {rx.patient_first}</web:DisplayName>
                    <web:EmailAddress></web:EmailAddress>
                    <web:EnterpriseId>E{rx.rx_number}</web:EnterpriseId>
                    <web:FYIs xsi:nil="true"/>
                    <web:FirstName>{rx.patient_first}</web:FirstName>
                    <web:FullName>{rx.patient_first} {rx.patient_last}</web:FullName>
                    <web:HomePhone>{rx.patient_phone}</web:HomePhone>
                    <web:LastName>{rx.patient_last}</web:LastName>
                    <web:MedicalRecordNumber>E{rx.rx_number}</web:MedicalRecordNumber>
                    <web:MiddleName></web:MiddleName>
                    <web:MobilePhone>{rx.patient_phone}</web:MobilePhone>
                    <web:PatientType></web:PatientType>
                    <web:PharmacyDocuments xsi:nil="true"/>
                    <web:PreferredDeliveryMethod>Pickup</web:PreferredDeliveryMethod>
                    <web:State>North Carolina</web:State>
                    <web:StateAbbreviation>NC</web:StateAbbreviation>
                    <web:StreetAddress>123 Test St</web:StreetAddress>
                    <web:WorkPhone>{rx.patient_phone}</web:WorkPhone>
                    <web:ZipCode>27601</web:ZipCode>
                </web:Patient>
                <web:Prescriptions>
                    <web:Prescription>
                        <web:AuthorizingProviderDisplayName>{rx.prescriber_name}</web:AuthorizingProviderDisplayName>
                        <web:DEACode>{rx.dea_code}</web:DEACode>
                        <web:DEACodeNumber>{rx.dea_code_number}</web:DEACodeNumber>
                        <web:DEACodeTitle>C-{rx.dea_code_number}</web:DEACodeTitle>
                        <web:Dose xsi:nil="true"/>
                        <web:EndDate>{rx.end_date}</web:EndDate>
                        <web:Fills>
                            <web:Fill>
                                <web:CreditCardPayments/>
                                <web:CustomFields/>
                                <web:DaySupply>{rx.fill_day_supply}</web:DaySupply>
                                <web:DeliveryMethod>Pickup</web:DeliveryMethod>
                                {dispensed_on_element}
                                <web:DisplayName>{rx.fill_day_supply} tablet in containers</web:DisplayName>
                                <web:FilledOn>{rx.filled_on}</web:FilledOn>
                                <web:FillType>Fill</web:FillType>
                                <web:Flags></web:Flags>
                                <web:Id>{rx.prescription_id}01</web:Id>
                                <web:IsCompletionFill>false</web:IsCompletionFill>
                                <web:IsDispensable>false</web:IsDispensable>
                                <web:IsFillInProgress>{rx.has_fill_in_progress}</web:IsFillInProgress>
                                <web:IsPartialFill>false</web:IsPartialFill>
                                <web:Ndc>{rx.drug_ndc}</web:Ndc>
                                <web:PatientPayAmountDue>{rx.fill_copay}</web:PatientPayAmountDue>
                                <web:PatientPayAmountTotal>{rx.fill_copay}</web:PatientPayAmountTotal>
                                <web:PickupPharmacyDisplayName>TEST PHARMACY</web:PickupPharmacyDisplayName>
                                <web:PickupPharmacyNCPDPId>{rx.ncpdp_id}</web:PickupPharmacyNCPDPId>
                                <web:PrescriptionId>{rx.prescription_id}</web:PrescriptionId>
                                <web:PrescriptionNumber>{rx.rx_number}</web:PrescriptionNumber>
                                <web:Quantity>{rx.fill_day_supply} tablet</web:Quantity>
                                <web:Status>{rx.fill_status}</web:Status>
                                <web:TrackingNumber xsi:nil="true"/>
                            </web:Fill>
                        </web:Fills>
                        <web:FillsRemaining>{rx.fills_remaining}</web:FillsRemaining>
                        <web:FirstDispensed>{rx.first_dispensed}</web:FirstDispensed>
                        <web:Flags></web:Flags>
                        <web:Frequency xsi:nil="true"/>
                        <web:HasFillInProgress>{rx.has_fill_in_progress}</web:HasFillInProgress>
                        <web:HasFillReadyForPickup>{rx.has_fill_ready_for_pickup}</web:HasFillReadyForPickup>
                        <web:Id>{rx.prescription_id}</web:Id>
                        <web:IsEnrolledInAutoFill>false</web:IsEnrolledInAutoFill>
                        <web:IsFillable>{rx.is_fillable}</web:IsFillable>
                        <web:IsPartialFillRemaining>false</web:IsPartialFillRemaining>
                        <web:IsRARable>false</web:IsRARable>
                        <web:LastDispensed>{rx.last_dispensed}</web:LastDispensed>
                        <web:LastDispensedDaySupply>{rx.last_dispensed_day_supply}</web:LastDispensedDaySupply>
                        <web:Medication>{rx.drug_name}</web:Medication>
                        <web:OrderingProviderDisplayName>{rx.prescriber_name}</web:OrderingProviderDisplayName>
                        <web:OwningPharmacy>
                            <web:AvailableDeliveryMethods>
                                <web:DeliveryMethod>Pickup</web:DeliveryMethod>
                            </web:AvailableDeliveryMethods>
                            <web:DisplayName>TEST PHARMACY</web:DisplayName>
                            <web:Id>8593</web:Id>
                            <web:IsIntegrated>true</web:IsIntegrated>
                            <web:NCPDPId>{rx.ncpdp_id}</web:NCPDPId>
                        </web:OwningPharmacy>
                        <web:PrescriptionNumber>{rx.rx_number}</web:PrescriptionNumber>
                        <web:RARPrescriptionId xsi:nil="true"/>
                        <web:RARPrescriptionNumber xsi:nil="true"/>
                        <web:RARStatus xsi:nil="true"/>
                        <web:ReasonNotFillable>{rx.reason_not_fillable}</web:ReasonNotFillable>
                        <web:ReasonNotRARable>{rx.reason_not_rarable}</web:ReasonNotRARable>
                        <web:Route>Oral</web:Route>
                        <web:Sig>{rx.sig}</web:Sig>
                        <web:StartDate>{rx.first_dispensed}</web:StartDate>
                        <web:Status>Active</web:Status>
                        <web:Timestamp>{rx.filled_on}</web:Timestamp>
                    </web:Prescription>
                </web:Prescriptions>
            </web:GetPrescriptionInfoResult>
        </web:GetPrescriptionInfoResponse>
    </soapenv:Body>
</soapenv:Envelope>'''


def _build_epic_refill_xml(rx: EpicRx) -> str:
    """Build the RequestFillsResponse SOAP XML (always success)."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:web="Epic.Clinical.Pharmacy.WebServices2018">
    <soapenv:Header/>
    <soapenv:Body>
        <web:RequestFillsResponse>
            <web:RequestFillsResult>
                <web:ErrorCode>0</web:ErrorCode>
                <web:ErrorMessage></web:ErrorMessage>
                <web:PrescriptionsUpdated>1</web:PrescriptionsUpdated>
                <web:UpdatePrescriptionResults>
                    <web:UpdatePrescriptionResult>
                        <web:ErrorCode>0</web:ErrorCode>
                        <web:ErrorMessage></web:ErrorMessage>
                        <web:FillId xsi:nil="true"
                            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"></web:FillId>
                        <web:PrescriptionId>{rx.prescription_id}</web:PrescriptionId>
                        <web:UpdateTimestamp>{datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}</web:UpdateTimestamp>
                        <web:WasUpdated>true</web:WasUpdated>
                    </web:UpdatePrescriptionResult>
                </web:UpdatePrescriptionResults>
            </web:RequestFillsResult>
        </web:RequestFillsResponse>
    </soapenv:Body>
</soapenv:Envelope>'''


def upload_epic_rx(rx_number: str, ncpdp_id: str, info_xml: str, refill_xml: str) -> None:
    """Upload Epic XML files to WireMock via the admin files API."""
    import requests

    files_to_upload = [
        (f"epic/2018/soap11/GetPrescriptionInfoResponse-{rx_number}-{ncpdp_id}.xml", info_xml),
        (f"epic/2018/soap11/RequestFillsResponse-{rx_number}-{ncpdp_id}.xml", refill_xml),
    ]

    for file_path, content in files_to_upload:
        url = f"{WIREMOCK_FILES_API}/{file_path}"
        resp = requests.put(url, data=content.encode("utf-8"),
                            headers={"Content-Type": "application/octet-stream"},
                            verify=False, timeout=10)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to upload {file_path}: HTTP {resp.status_code} — {resp.text}"
            )


def delete_epic_rx(rx_number: str, ncpdp_id: str = "9759001") -> None:
    """Delete Epic XML files from WireMock."""
    import requests

    files_to_delete = [
        f"epic/2018/soap11/GetPrescriptionInfoResponse-{rx_number}-{ncpdp_id}.xml",
        f"epic/2018/soap11/RequestFillsResponse-{rx_number}-{ncpdp_id}.xml",
    ]

    for file_path in files_to_delete:
        url = f"{WIREMOCK_FILES_API}/{file_path}"
        resp = requests.delete(url, verify=False, timeout=10)
        if resp.status_code not in (200, 204, 404):
            raise RuntimeError(
                f"Failed to delete {file_path}: HTTP {resp.status_code} — {resp.text}"
            )


def upload_epic_scenario(scenario: EpicScenario, upload_p360: bool = True) -> None:
    """Upload all files for an Epic scenario."""
    upload_epic_rx(
        scenario.rx.rx_number,
        scenario.rx.ncpdp_id,
        scenario.info_xml,
        scenario.refill_xml,
    )
    if upload_p360 and scenario.p360_patient:
        _upsert_p360_patient(scenario.p360_patient)


def delete_epic_scenario(scenario: EpicScenario, delete_p360: bool = False) -> None:
    """Delete all files for an Epic scenario."""
    delete_epic_rx(scenario.rx.rx_number, scenario.rx.ncpdp_id)
    if delete_p360 and scenario.p360_patient:
        _delete_p360_patient(scenario.p360_patient)


# --- Epic convenience one-liners ---

def create_epic_ready_for_pickup(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic READY_FOR_PICKUP scenario."""
    scenario = build_epic_scenario(status=EpicStatus.READY_FOR_PICKUP, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_in_queue(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic IN_QUEUE scenario."""
    scenario = build_epic_scenario(status=EpicStatus.IN_QUEUE, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_refillable(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic REFILLABLE scenario."""
    scenario = build_epic_scenario(status=EpicStatus.REFILLABLE, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_picked_up(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic RX_PICKED_UP scenario."""
    scenario = build_epic_scenario(status=EpicStatus.RX_PICKED_UP, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_shipped(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic SHIPPED scenario."""
    scenario = build_epic_scenario(status=EpicStatus.SHIPPED, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_controlled(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic CONTROLLED_SUBSTANCE scenario."""
    scenario = build_epic_scenario(status=EpicStatus.CONTROLLED_SUBSTANCE, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_too_soon(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic TOO_SOON scenario."""
    scenario = build_epic_scenario(status=EpicStatus.TOO_SOON, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_no_refills(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic NOT_REFILLABLE_NO_REFILLS scenario."""
    scenario = build_epic_scenario(status=EpicStatus.NOT_REFILLABLE_NO_REFILLS, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_expired(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic NOT_REFILLABLE_EXPIRED scenario."""
    scenario = build_epic_scenario(status=EpicStatus.NOT_REFILLABLE_EXPIRED, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


def create_epic_waiting_for_prescriber(rx_number: str, **kwargs) -> EpicScenario:
    """Create and upload an Epic WAITING_FOR_PRESCRIBER scenario."""
    scenario = build_epic_scenario(status=EpicStatus.WAITING_FOR_PRESCRIBER, rx_number=rx_number, **kwargs)
    upload_epic_scenario(scenario)
    return scenario


# List of Epic statuses available for the UI
EPIC_AVAILABLE_STATUSES = list(EpicStatus)


# =============================================================================
# PMS CONFIG MANAGEMENT (ateb DB)
# =============================================================================
# The ateb DB is ephemeral — it gets reseeded on deploys. These helpers ensure
# the pms-services client/store/adapter config exists before tests run.
# =============================================================================

ATEB_DB_HOST = "ip-10-69-37-54.us-east-2.compute.internal"
ATEB_DB_PORT = 30150
ATEB_DB_NAME = "ateb"
ATEB_DB_USER = "ateb"
ATEB_DB_PASS = "ateb"

# Adapter type IDs (from pms.adaptertype)
ADAPTER_TYPE_IDS = {
    "PDX": 3,       # PDXEPS
    "McKesson": 6,  # MCKESSON
    "Liberty": 7,   # LIBERTY
    "Epic": 10,     # EPIC2018
}

# Connection configs: adapter → (connectionconfigid, url)
CONNECTION_CONFIGS = {
    "PDX": (11, "http://pmssim:8181/FsiXmlSimulator/PDXSimulatorServlet"),
    "McKesson": (15, "http://pmssim:8181/FsiXmlSimulator/PerSeSimulatorServlet"),
    "Liberty": (17, "http://ivr-mock-svcs:8080/libertypms"),
    "Epic": (18, "http://ivr-mock-svcs:8080/epic/PharmacyServices2018/soap11"),
}

# Default store numbers per PMS type
DEFAULT_PMS_STORES = {
    "PDX": "70050001",
    "McKesson": "125",
    "Liberty": "8174884613",
    "Epic": "9759001",
}


def _get_ateb_connection():
    """Get a psycopg2 connection to the ateb DB."""
    import psycopg2
    return psycopg2.connect(
        host=ATEB_DB_HOST,
        port=ATEB_DB_PORT,
        dbname=ATEB_DB_NAME,
        user=ATEB_DB_USER,
        password=ATEB_DB_PASS,
    )


def ensure_pms_config(
    client_id: int,
    pms_type: str,
    store_id: str | None = None,
) -> dict:
    """Ensure pms-services config exists for a client/store/adapter combo.

    Idempotent — checks if the config already exists before creating.
    Also ensures the connectionconfig exists.

    Args:
        client_id: The client ID (e.g., 8000, 9001)
        pms_type: One of "PDX", "McKesson", "Liberty", "Epic"
        store_id: Store ID to configure. Defaults to DEFAULT_PMS_STORES[pms_type].

    Returns:
        dict with keys: clientconfigid, storeconfigid, connectionconfigid, store_id
    """
    if pms_type not in ADAPTER_TYPE_IDS:
        raise ValueError(f"Unknown pms_type: {pms_type}. Must be one of: {list(ADAPTER_TYPE_IDS.keys())}")

    adapter_type_id = ADAPTER_TYPE_IDS[pms_type]
    conn_id, conn_url = CONNECTION_CONFIGS[pms_type]
    if store_id is None:
        store_id = DEFAULT_PMS_STORES[pms_type]

    conn = _get_ateb_connection()
    try:
        with conn.cursor() as cur:
            # 1. Ensure connectionconfig exists
            cur.execute(
                "SELECT connectionconfigid FROM pms.connectionconfig WHERE connectionconfigid = %s",
                (conn_id,)
            )
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO pms.connectionconfig (connectionconfigid, url, communicationtypeid) "
                    "VALUES (%s, %s, 2)",
                    (conn_id, conn_url)
                )

            # 2. Ensure clientconfig exists
            cur.execute(
                "SELECT clientconfigid FROM pms.clientconfig "
                "WHERE clientid = %s AND adaptertypeid = %s",
                (client_id, adapter_type_id)
            )
            row = cur.fetchone()
            if row:
                client_config_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO pms.clientconfig (clientid, adaptertypeid, configstatusid) "
                    "VALUES (%s, %s, 1) RETURNING clientconfigid",
                    (client_id, adapter_type_id)
                )
                client_config_id = cur.fetchone()[0]

            # 3. Ensure storeconfig exists
            cur.execute(
                "SELECT storeconfigid FROM pms.storeconfig "
                "WHERE clientconfigid = %s AND storeid = %s",
                (client_config_id, store_id)
            )
            row = cur.fetchone()
            if row:
                store_config_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO pms.storeconfig (clientconfigid, storeid, connectionconfigid) "
                    "VALUES (%s, %s, %s) RETURNING storeconfigid",
                    (client_config_id, store_id, conn_id)
                )
                store_config_id = cur.fetchone()[0]

            conn.commit()

        return {
            "clientconfigid": client_config_id,
            "storeconfigid": store_config_id,
            "connectionconfigid": conn_id,
            "store_id": store_id,
        }
    finally:
        conn.close()


def ensure_all_pms_configs(client_id: int) -> dict:
    """Ensure all 4 PMS types are configured for a client.

    Returns dict of pms_type → config info.
    """
    results = {}
    for pms_type in ADAPTER_TYPE_IDS:
        results[pms_type] = ensure_pms_config(client_id, pms_type)
    return results


# =============================================================================
# CHANNEL CONFIG MANAGEMENT
# =============================================================================

CHANNELCONFIG_DB_HOST = "pcrdsqa.cxa8jqblcefj.us-east-2.rds.amazonaws.com"
CHANNELCONFIG_DB_NAME = "channelconfig"
CHANNELCONFIG_DB_USER = "channelconfig1"
CHANNELCONFIG_DB_PASS = "channelconfig1"


def _get_channelconfig_connection():
    """Get a psycopg2 connection to the channelconfig DB."""
    import psycopg2
    return psycopg2.connect(
        host=CHANNELCONFIG_DB_HOST,
        port=5432,
        dbname=CHANNELCONFIG_DB_NAME,
        user=CHANNELCONFIG_DB_USER,
        password=CHANNELCONFIG_DB_PASS,
        sslmode="require",
    )


def set_channel_pms_store(
    client_id: int,
    store_number: str,
    pms_type: str | None = None,
    channel_id: int = 2,  # INBOUND_IVR
) -> dict:
    """Update the channel config's pmsStoreNumber (and optionally pmsType).

    Args:
        client_id: The client ID
        store_number: The pmsStoreNumber value to set
        pms_type: Optional — also set the pmsType field (e.g., "PDX", "McKesson", "Liberty", "Epic")
        channel_id: Channel ID (2=INBOUND_IVR, 1=SMS, 4=OUTBOUND_IVR)

    Returns:
        dict with old and new values
    """
    conn = _get_channelconfig_connection()
    try:
        with conn.cursor() as cur:
            # Get current values
            cur.execute(
                "SELECT channelconfigid, configuration->>'pmsStoreNumber' as store, "
                "configuration->>'pmsType' as pms_type "
                "FROM channelconfig.channelconfig "
                "WHERE clientid = %s AND channelid = %s",
                (client_id, channel_id)
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No channel config found for client {client_id}, channel {channel_id}")

            old_store = row[1]
            old_pms_type = row[2]

            # Build update
            update_obj = {"pmsStoreNumber": store_number}
            if pms_type:
                update_obj["pmsType"] = pms_type

            import json
            cur.execute(
                "UPDATE channelconfig.channelconfig "
                "SET configuration = configuration || %s::jsonb "
                "WHERE clientid = %s AND channelid = %s",
                (json.dumps(update_obj), client_id, channel_id)
            )
            conn.commit()

        return {
            "old_store": old_store,
            "old_pms_type": old_pms_type,
            "new_store": store_number,
            "new_pms_type": pms_type or old_pms_type,
        }
    finally:
        conn.close()


def switch_pms_type(client_id: int, pms_type: str, channel_id: int = 2) -> dict:
    """High-level: ensure ateb config exists AND point channel config to it.

    This is the one-call solution for switching a client to a different PMS type.

    Args:
        client_id: The client ID
        pms_type: One of "PDX", "McKesson", "Liberty", "Epic"
        channel_id: Channel ID (default 2=INBOUND_IVR)

    Returns:
        dict with ateb config + channel config change details
    """
    # Ensure ateb has the config
    ateb_config = ensure_pms_config(client_id, pms_type)

    # Point channel config to the right store
    channel_result = set_channel_pms_store(
        client_id=client_id,
        store_number=ateb_config["store_id"],
        pms_type=pms_type,
        channel_id=channel_id,
    )

    return {
        "pms_type": pms_type,
        "store_number": ateb_config["store_id"],
        "ateb": ateb_config,
        "channel_config": channel_result,
    }
