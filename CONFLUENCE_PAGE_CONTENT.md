# PMSI Data Builder — User Guide

## What Is This?

The PMSI Data Builder is a desktop tool for the ACE QA team that generates test prescription data and uploads it to the PMS Simulator. Instead of manually crafting XML files and worrying about XSD validation rules, you pick a **desired status outcome** (like "READY_FOR_PICKUP" or "CONTROLLED_SUBSTANCE") and the tool generates all the correct XML automatically.

It also creates matching patient records in P360 (DocumentDB) so personalization flows work end-to-end.

## Downloads

| Platform | File | Notes |
|----------|------|-------|
| Windows | PMSI_Tools_Windows.zip (attached) | Extract and run `PMSI_Data_Builder.exe` |
| macOS | PMSI_Tools_macOS.zip (attached) | Extract DMG, drag to Applications |

**Requirements:** VPN connection to QA environment (ivr-mock-svcs.pc.q.awscloud.private must be reachable).

## Quick Start

1. Download and extract the zip for your platform
2. Run `PMSI_Data_Builder.exe` (Windows) or open the app (Mac)
3. Follow the 3-step wizard:
   - **Step 1:** Enter patient info + store number
   - **Step 2:** Add one or more prescriptions with desired status
   - **Step 3:** Review and submit

## Supported Statuses

| Status | What It Produces | When the Bot Sees This |
|--------|-----------------|----------------------|
| READY_FOR_PICKUP | StatusResponse code 206 | "Your prescription is ready for pickup" |
| IN_QUEUE | StatusResponse code 204 | "Your prescription is being filled" |
| WAITING_FOR_PRESCRIBER | StatusResponse code 200 | "We're waiting to hear from your prescriber" |
| REFILLABLE | StatusResponse 207, picked up > 5 days ago | Eligible for refill |
| RX_PICKED_UP | StatusResponse 207, picked up ≤ 5 days ago | "You recently picked up this prescription" |
| SHIPPED | StatusResponse code 208 | "Your prescription has been shipped" |
| NOT_REFILLABLE | RxResponse code 900 + reject code | "This prescription cannot be refilled" |
| CONTROLLED_SUBSTANCE | Drug schedule = 2 | "This is a controlled substance" |
| TOO_SOON | Recent fill, low % consumed | "It's too early to refill" (requires channel config) |

## Step-by-Step

### Step 1: Patient & Store

| Field | Description | Default |
|-------|-------------|---------|
| First Name | Patient first name (uppercased automatically) | TESTPATIENT |
| Last Name | Patient last name | STATUS |
| Date of Birth | Format: YYYYMMDD (e.g., 19850101) | 19850101 |
| Phone Number | 10-digit phone (no dashes) | 5550561001 |
| Client ID | Client ID for the channel | 8000 |
| PMSI Store Number | Must match channel config `pmsStoreNumber` | 70050001 |

### Step 2: Prescriptions

Click **+ Add Prescription** to add Rx entries. For each:

| Field | Description | Notes |
|-------|-------------|-------|
| RX Number | Prescription number | Auto-generated if blank (5610000-5619999) |
| Desired Status | The outcome you want | See status table above |
| Drug Name | Medication name | Max 28 characters (XSD rule) |
| Copay | Dollar amount | e.g., 10.00 |
| Days Supply | Days of medication | Affects TOO_SOON calculation |
| Refills Remaining | Remaining refills | |
| Authorized Refills | Originally authorized | |
| Sig Text | Prescription directions | |

You can add multiple prescriptions for the same patient.

### Step 3: Review & Submit

- Review the preview showing exactly what XML codes will be generated
- Toggle P360 patient document creation (on by default)
- Click **Submit** to upload everything
- Save scenarios for re-use

## What Gets Created

For each prescription, the tool uploads **3 XML files** to the simulator:

```
PDX/RxResponse{rx_number}.xml      — Drug, patient, refill info
PDX/StatusResponse{rx_number}.xml  — Current fill status
PDX/RefillResponse{rx_number}.xml  — Refill request response
```

If P360 is enabled, it also upserts a patient document in DocumentDB (`p360_daily_docker.patient`) with:
- Patient demographics matching the XML
- Prescription array with matching rx numbers and fill dates
- Search fields (lastNameUpper, firstNameUpper, dob, phoneNumber)
- Organization mapping (e360OrgId, e360StoreId)

## Environment Support

Use the dropdown in the top-right to switch between:
- **QA** — ivr-mock-svcs.pc.q.awscloud.private
- **Staging** — ivr-mock-svcs.pc.s.awscloud.private

## Saved Scenarios

Save frequently-used test setups with the "Save Scenario" button on Step 3. Load them instantly from Step 1's "Quick Load" dropdown.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Builder Library Not Available" | Ensure the exe was built correctly. If running from source, check that `tests/helpers_pms_sim.py` exists in the same directory. |
| Upload fails / timeout | Check VPN connection. The sim API must be reachable. |
| Rx not found after upload | Check sim logs for XSD validation errors. The tool enforces XSD rules, but if you override fields manually, validation can fail. |
| P360 patient not found | Verify clientId and phone match what the bot is searching for. Check that you're looking at `p360_daily_docker.patient` (not `p360.patients`). |
| TOO_SOON not working | Requires channel config `minPercentageDaysSupply > 0`. Default is 0 (disabled). Contact platform team to set this. |

## For Developers — Running from Source

```bash
cd C:\Code\Data_setter_upper
python launch_builder.py
```

Or directly:
```bash
pip install httpx ttkbootstrap pymongo
python pmsi_data_builder_ui.py
```

## For Test Automation (Headless)

The same library powers the UI and can be used directly in pytest:

```python
from tests.helpers_pms_sim import build_scenario, upload_scenario, RxStatus

scenario = build_scenario(
    rx_status=RxStatus.READY_FOR_PICKUP,
    rx_number="5610001",
    patient_first="Jane",
    patient_last="Smith",
    patient_phone="5559876543",
    patient_dob="19850101",
    drug_name="LISINOPRIL 10MG TAB",
)
upload_scenario(scenario)
```

## Source Code

- **UI:** https://gitlab.com/enlivenhealth/engineering/omnichannel-communications-platform/load/p360-and-sim-data-setup
- **Library:** https://gitlab.com/enlivenhealth/engineering/omnichannel-communications-platform/ace/ace-functional-tests (tests/helpers_pms_sim.py)
