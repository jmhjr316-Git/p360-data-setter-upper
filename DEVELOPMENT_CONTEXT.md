# PMSI Data Manager - Development Context

## Current Status (Last Updated: February 2025)

### What We Just Built
Created a **modern wizard-based UI** (`pmsi_data_ui_modern.py`) with full multi-RX support that:
- ✅ 3-step wizard: Patient Info → Prescriptions → Review & Submit
- ✅ Add multiple prescriptions per patient
- ✅ Environment switching (QA/Staging)
- ✅ XML file generation from templates
- ✅ Direct upload to PMSI simulator via API
- ✅ DocumentDB personalization integration
- ✅ Modern styling with ttkbootstrap (falls back to standard ttk)

### Branch Structure
- **master**: Stable single-RX version (`pmsi_data_ui.py`)
- **feature/multi-rx-support**: Modern multi-RX wizard (`pmsi_data_ui_modern.py`) ← YOU ARE HERE

### Files
- `pmsi_data_ui.py` - Original stable UI (single RX)
- `pmsi_data_ui_modern.py` - New wizard UI (multi-RX) **← ACTIVE DEVELOPMENT**
- `templates/` - XML templates and configuration
- `environment_config.json` - QA/Staging settings

---

## 🔴 KNOWN ISSUE - NEXT TASK

### Problem: DocumentDB Personalization Not Showing All RXs
**Symptom**: When creating a patient with multiple prescriptions and personalization enabled, both RXs upload to PMSI simulator successfully, but DocumentDB may not show all prescriptions properly.

**Hypothesis**: Need to randomize additional fields in the DocumentDB prescription objects to ensure uniqueness. Currently using mostly static values for:
- `gpi` (always "34000003100340")
- `ndc` (always "65162000850")
- `patientRxId` (simple increment)
- `prescriptionStoreNpi` (randomized but may need more variation)

**Where to Look**:
- File: `pmsi_data_ui_modern.py`
- Method: `create_personalization_entries()` (around line 550+)
- Specifically the prescription object creation loop

**What to Try**:
1. Randomize `gpi` and `ndc` values per prescription
2. Ensure `patientRxId` has more variation (not just ateb_patient_id + index)
3. Add more unique identifiers per prescription
4. Check if DocumentDB has uniqueness constraints we're violating

**Test Case**:
1. Run modern UI
2. Add patient info
3. Add 2+ prescriptions with different medications
4. Enable personalization
5. Submit
6. Check DocumentDB to see if all prescriptions appear

---

## How to Run

### Modern UI (Multi-RX)
```bash
python pmsi_data_ui_modern.py
```

### Original UI (Single-RX)
```bash
python pmsi_data_ui.py
```

### Quick Launcher
```bash
python setup_and_run.py
```

---

## Architecture Overview

### Data Flow
```
User Input → Wizard Steps → Template Variables → XML Generation → API Upload
                                                                    ↓
                                                            DocumentDB (optional)
```

### Key Methods in Modern UI

**Wizard Flow**:
- `show_step(step_num)` - Display current wizard step
- `validate_current_step()` - Validate before moving forward
- `go_next()` / `go_back()` - Navigation

**Data Processing**:
- `submit_data()` - Main submission orchestrator
- `prepare_template_variables()` - Convert form data to template tokens
- `upload_file_to_simulator()` - API call to PMSI simulator
- `create_personalization_entries()` - **← FIX THIS ONE** DocumentDB creation

**Prescription Management**:
- `add_prescription_dialog()` - Modal to add RX
- `refresh_prescription_list()` - Update RX display
- `remove_prescription()` - Delete RX from list

---

## Template System

### Files Generated Per RX
1. `RefillResponse{rx_number}.xml`
2. `RxResponse{rx_number}.xml`
3. `StatusResponse{rx_number}.xml`

### Template Variables
All defined in `prepare_template_variables()`:
- Patient: first_name, last_name, dob, phone
- RX: rx_number, medication_name, strength, units, copay
- Status: rx_status_code, rx_status_description, refillable
- Dates: last_fill_date, expiration_date (with smart logic)

### Status Mappings
Defined in `templates/template_config.json`:
- Active, Inactive, Pending, Expired
- In Queue, Ready for Pickup, Picked Up, Shipped
- Out of Refills

---

## Environment Configuration

### QA Environment
- API: `https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co`
- DocumentDB: `p360_daily_docker.patient`

### Staging Environment
- API: (configured in environment_config.json)
- DocumentDB: `p360.patient`

---

## DocumentDB Schema (Current)

### Patient Document
```json
{
  "atebPatientId": 12345.0,
  "dateOfBirth": "19900101",
  "testCase": "pmsi ui generated - modern",
  "clientId": 1537.0,
  "storeId": 13387.0,
  "storeNpi": "1821516543",
  "pharmacyPatientId": "1234567",
  "name": {
    "firstName": "John",
    "lastName": "Doe"
  },
  "phone": {
    "primary": "5551234567",
    "mobile": "5551234567",
    "alternate": ""
  },
  "firstName": "John",
  "lastName": "Doe",
  "prescriptions": [
    {
      "rxNum": "1234567",
      "rxStatus": "ACTIVE",
      "fillDate": "20250201",
      "soldDate": "20250201",
      "expireDate": "20260201",
      "medication": {
        "gpi": "34000003100340",  // ← STATIC - RANDOMIZE?
        "medicationName": "LISINOPRIL",
        "speakableMedName": "LISINOPRIL",
        "ndc": "65162000850"  // ← STATIC - RANDOMIZE?
      },
      "patientRxId": 12345.0,  // ← SIMPLE INCREMENT - MORE VARIATION?
      "medicationName": "LISINOPRIL",
      "gpi": "34000003100340",
      "ndc": "65162000850",
      "daysSupply": 30.0,
      "refillsRemaining": 7.0,
      "dispensedQuantity": 30.0,
      "originalDispensedQuantity": 30.0,
      "originalRefillsAuth": 7.0,
      "autofillProgram": false,
      "prescriptionStoreNpi": "1234567890"  // ← RANDOMIZED
    }
  ],
  "preferenceAttributes": []
}
```

---

## Testing Checklist

### Before You Left Off
- ✅ Wizard navigation works
- ✅ Patient data persists across steps
- ✅ Multiple prescriptions can be added
- ✅ Review step shows correct data
- ✅ Personalization checkbox works
- ✅ Files upload to PMSI simulator
- ❌ **All prescriptions appear in DocumentDB** ← FIX THIS

### When You Return
1. Test multi-RX DocumentDB creation
2. Verify all prescriptions appear in DocumentDB
3. Check for uniqueness constraint violations
4. Test with 2, 3, 5 prescriptions
5. Verify search functionality finds all RXs

---

## Quick Reference Commands

### Git
```bash
# Current branch
git branch

# Switch to master
git checkout master

# Switch back to feature branch
git checkout feature/multi-rx-support

# See changes
git status
git diff
```

### Testing
```bash
# Run modern UI
python pmsi_data_ui_modern.py

# Check DocumentDB (from UI)
Click "Search DocDB" button → Search by RX Number or Patient Name
```

---

## Dependencies
```
requests>=2.25.0
tkcalendar>=1.6.0
pymongo>=4.0.0
ttkbootstrap>=1.10.0  # Optional, falls back to standard ttk
```

---

## Next Steps (Priority Order)

1. **FIX**: Randomize DocumentDB prescription fields for uniqueness
2. **TEST**: Verify all multi-RX scenarios work with personalization
3. **ENHANCE**: Add edit prescription functionality
4. **ENHANCE**: Add duplicate prescription feature
5. **MERGE**: Merge feature branch to master when stable
6. **DEPLOY**: Create installer/distribution package

---

## Notes
- Modern UI is fully functional for PMSI simulator uploads
- DocumentDB integration works but needs field randomization
- Original UI (`pmsi_data_ui.py`) remains stable fallback
- All environment switching works correctly
- Template system handles all 9 RX statuses properly

---

**Remember**: The thread to tug on is in `create_personalization_entries()` method - randomize the static fields in the prescription objects!
