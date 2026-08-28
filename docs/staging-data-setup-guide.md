# Staging Data Setup Guide

Quick reference for creating test prescription data in the **Staging** environment.

## Environment Info

| | QA | Staging |
|---|---|---|
| PMS Sim URL | `pmssim.pc.q.awscloud.private` | `10.13.60.40` (DNS pending) |
| Host header | _(none needed)_ | `pmssim-ocp-sit.k8s.raleng.omnicell.com` |
| WireMock | `ivr-mock-svcs.pc.q.awscloud.private` | TBD |

DNS CNAME for staging hasn't been created yet. The UI handles the IP + Host header workaround automatically when you select "Staging" in the environment dropdown.

## Using the UI

1. Launch: `python launch_builder.py`
2. Switch environment to **Staging** (top-right dropdown)
3. Pick PMS type, patient info, desired status
4. Check **Include P360** to also create the patient document
5. Hit **Submit**

That's it. The tool generates all required files with matched data (NDC, fill dates, patient IDs) and uploads them to the staging sim.

## Using the Library (for automation agents)

```python
import sys
sys.path.insert(0, '/mnt/c/Code/Data_setter_upper')
from tests.helpers_pms_sim import (
    set_environment,
    build_mckesson_scenario, upload_mckesson_scenario, McKessonStatus,
    build_liberty_scenario, upload_liberty_scenario, LibertyStatus,
    build_scenario, upload_scenario, RxStatus,  # PDX
)
from tests.helpers_p360 import ensure_patient, close as close_p360

# 1. Target staging
set_environment('staging')

# 2. Build + upload (McKesson example)
scenario = build_mckesson_scenario(
    status=McKessonStatus.REFILLABLE,
    rx_number='8001001',
    patient_first='TEST',
    patient_last='PATIENT',
    patient_phone='5551234567',
    patient_dob='19900101',
    drug_name='METFORMIN 500MG TAB',
    store_number='125',
    client_id=9001,
    include_p360=True,
)
upload_mckesson_scenario(scenario)

# 3. Upload P360 patient (if include_p360=True)
if scenario.p360_patient:
    ensure_patient(scenario.p360_patient)
    close_p360()
```

## Available PMS Builders

| PMS Type | Builder Function | Status Enum | Store |
|---|---|---|---|
| PDX EPS | `build_scenario()` + `upload_scenario()` | `RxStatus` | 70050001 |
| McKesson | `build_mckesson_scenario()` + `upload_mckesson_scenario()` | `McKessonStatus` | 125 |
| Liberty | `build_liberty_scenario()` + `upload_liberty_scenario()` | `LibertyStatus` | 8174884613 |
| Epic | `build_epic_scenario()` + `upload_epic_scenario()` | `EpicStatus` | 9759001 |
| PDX 275 | `build_pdx275_scenario()` + `upload_pdx275_scenario()` | `Pdx275Status` | 01 |
| RX30 | `build_atebgen_scenario()` + `upload_atebgen_scenario()` | `AtebGenStatus` | 02 |

## Critical: P360 Must Match PMS Sim

When `include_p360=True`, the builder automatically ensures these fields match between the P360 patient document and what pms-services returns from the sim:

| P360 Field | Must Match | PMS Response Field |
|---|---|---|
| `medication.ndc` | = | `drug.ndc` |
| `fillDate` | = | `rx.lastFillDate` |
| `atebPatientId` | = | `patient.pin` / patient ID |
| `prescriptions[].rxNum` | = | rx number |

**If these don't match, personalization will fail silently** — the patient won't get refill prompts on inbound IVR.

## Staging Limitations

- **WireMock not available yet** — Liberty and Epic won't work in staging until we have a staging WireMock endpoint
- **DNS not resolved** — using IP `10.13.60.40` with Host header (handled by `set_environment('staging')`)
- **PDX275 / RX30** — requires `manage.jsp` legacy file support (MR 34 pending). If pod restarts, legacy support is lost until MR merges.

## Troubleshooting

**Personalization not triggering?**
1. Verify PMS data exists: call pms-services `/rxs/{rxNum}` directly
2. Compare P360 NDC, fillDate, atebPatientId against pms-services response
3. Check channel config has correct `pmsStoreNumber` and `callPmsi=true`
4. Confirm campaign is active with INBOUND_IVR channel

**Sim data missing after restart?**
- PDX/McKesson: data persists in PVC (survives restarts)
- PDX275/RX30: legacy files are ephemeral until MR 34 merges
- Liberty/Epic: WireMock mappings persist in PVC
