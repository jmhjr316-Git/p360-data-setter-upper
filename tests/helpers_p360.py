"""P360 DocumentDB helper — create/ensure test patients exist.

Provides a Python equivalent of the Node.js patientDb.js helper used by
the PC platform tests. Connects to DocumentDB (p360_daily_docker.patient)
and inserts patients idempotently (match on clientId + phone.primary + name).

Usage:
    from tests.helpers_p360 import ensure_patient, get_patient, P360_URI

    patient_doc = {
        "clientId": 8000,
        "storeId": 80000,
        "storeNpi": "1234580001",
        "atebPatientId": 99001,
        "dateOfBirth": "19850101",
        "name": {"firstName": "TEST", "lastName": "STATUS"},
        "phone": {"primary": "5550561001"},
        "prescriptions": [...],
    }
    ensure_patient(patient_doc)
"""

import logging
from typing import Any

import pymongo

logger = logging.getLogger(__name__)

P360_URI = (
    "mongodb://docdb_admin:P360DocumentDockerCopy0507"
    "@p360-document-db-dev.cluster-ccmb0vzyiebh.us-east-2.docdb.amazonaws.com:27017"
    "/?ssl=true&retryWrites=false&tlsAllowInvalidCertificates=true"
    "&authSource=admin&authMechanism=SCRAM-SHA-1"
)
P360_DB = "p360_daily_docker"
P360_COLLECTION = "patient"

# Environment presets
P360_ENVIRONMENTS = {
    "qa": {
        "uri": (
            "mongodb://docdb_admin:P360DocumentDockerCopy0507"
            "@p360-document-db-dev.cluster-ccmb0vzyiebh.us-east-2.docdb.amazonaws.com:27017"
            "/?ssl=true&retryWrites=false&tlsAllowInvalidCertificates=true"
            "&authSource=admin&authMechanism=SCRAM-SHA-1"
        ),
        "db": "p360_daily_docker",
    },
    "staging": {
        "uri": (
            "mongodb://svc_krc:8gT%211c.J"
            "@p360-document-db-stg.cluster-c8ynciexdc7u.us-east-2.docdb.amazonaws.com:27017"
            "/p360?ssl=true&retryWrites=false&tlsAllowInvalidCertificates=true"
            "&authSource=admin&authMechanism=SCRAM-SHA-1"
        ),
        "db": "p360",
    },
}

_client: pymongo.MongoClient | None = None


def set_environment(env: str) -> None:
    """Switch P360 target environment. Valid values: 'qa', 'staging'.

    Closes any existing connection and updates URI/DB for subsequent calls.
    """
    global P360_URI, P360_DB, _client
    env = env.lower().strip()
    if env not in P360_ENVIRONMENTS:
        raise ValueError(f"Unknown environment '{env}'. Valid: {list(P360_ENVIRONMENTS.keys())}")
    # Close existing connection if switching
    if _client:
        _client.close()
        _client = None
    cfg = P360_ENVIRONMENTS[env]
    P360_URI = cfg["uri"]
    P360_DB = cfg["db"]


def _get_client() -> pymongo.MongoClient:
    global _client
    if _client is None:
        _client = pymongo.MongoClient(P360_URI)
    return _client


def _get_collection():
    return _get_client()[P360_DB][P360_COLLECTION]


def ensure_patient(patient_data: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a patient. Returns the document.

    Matches on clientId + phone.primary + name.firstName + name.lastName.
    Uses replace_one with upsert=True — atomic, no duplicates, full doc refresh.

    NOTE: This REPLACES the entire document including prescriptions.
    To add prescriptions to an existing patient, use ensure_patient_with_rx() instead.
    """
    coll = _get_collection()
    query = {
        "clientId": patient_data["clientId"],
        "phone.primary": patient_data["phone"]["primary"],
        "name.firstName": patient_data["name"]["firstName"],
        "name.lastName": patient_data["name"]["lastName"],
    }

    result = coll.replace_one(query, patient_data, upsert=True)
    if result.upserted_id:
        logger.info(
            "Inserted patient %s %s → %s",
            patient_data["name"]["firstName"],
            patient_data["name"]["lastName"],
            result.upserted_id,
        )
    else:
        logger.info(
            "Updated patient %s %s (matched %d)",
            patient_data["name"]["firstName"],
            patient_data["name"]["lastName"],
            result.matched_count,
        )
    return patient_data


def ensure_patient_with_rx(patient_data: dict[str, Any]) -> dict[str, Any]:
    """Insert a patient or merge prescriptions into an existing one.

    If the patient already exists (matched on clientId + phone + name):
    - New prescriptions are added to the existing array
    - Existing prescriptions with the same rxNum are replaced (updated)
    - All other patient fields are updated

    If the patient doesn't exist, creates a new document (same as ensure_patient).

    This is the preferred method when adding prescriptions incrementally.
    """
    coll = _get_collection()
    query = {
        "clientId": patient_data["clientId"],
        "phone.primary": patient_data["phone"]["primary"],
        "name.firstName": patient_data["name"]["firstName"],
        "name.lastName": patient_data["name"]["lastName"],
    }

    existing = coll.find_one(query)

    if existing is None:
        # No existing patient — just insert
        result = coll.replace_one(query, patient_data, upsert=True)
        logger.info(
            "Inserted patient %s %s",
            patient_data["name"]["firstName"],
            patient_data["name"]["lastName"],
        )
    else:
        # Merge prescriptions: keep existing, add/update new ones by rxNum
        existing_rxs = {rx["rxNum"]: rx for rx in existing.get("prescriptions", [])}
        new_rxs = patient_data.get("prescriptions", [])

        for rx in new_rxs:
            existing_rxs[rx["rxNum"]] = rx  # Add or replace by rxNum

        # Update the document with merged prescriptions + refreshed fields
        merged_doc = dict(patient_data)
        merged_doc["prescriptions"] = list(existing_rxs.values())

        result = coll.replace_one(query, merged_doc)
        logger.info(
            "Merged %d rx into patient %s %s (now %d total rx)",
            len(new_rxs),
            patient_data["name"]["firstName"],
            patient_data["name"]["lastName"],
            len(merged_doc["prescriptions"]),
        )
        patient_data = merged_doc

    return patient_data


def get_patient(client_id: int, phone: str) -> dict[str, Any] | None:
    """Look up a patient by clientId and phone number."""
    coll = _get_collection()
    return coll.find_one({"clientId": client_id, "phone.primary": phone})


def delete_patient(client_id: int, phone: str) -> bool:
    """Delete a test patient. Returns True if deleted."""
    coll = _get_collection()
    result = coll.delete_one({"clientId": client_id, "phone.primary": phone})
    return result.deleted_count > 0


def close():
    """Close the MongoDB connection."""
    global _client
    if _client:
        _client.close()
        _client = None
