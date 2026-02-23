# PMSI Data Manager - User Guide

## Quick Start

### Installation

**Windows:**
1. Download `PMSI_Data_Manager.exe`
2. Double-click to run (no installation needed)
3. If Windows shows a security warning, click "More info" → "Run anyway"

**Mac:**
1. Download `PMSI_Data_Manager.dmg`
2. Double-click the DMG file to mount it
3. Drag the app to your Applications folder (or run directly from DMG)
4. **Important:** Right-click the app → "Open" (first time only)
   - Don't double-click! This bypasses Gatekeeper security
   - Click "Open" in the security dialog
5. For future launches, you can double-click normally

## Setting Up Your Client

### 1. Select Your Environment

At the top right of the window, choose your environment:
- **QA** - For testing in the QA environment
- **Staging** - For staging environment testing

The window title will update to show your current environment.

### 2. Configure Your Store (One-Time Setup)

On the first screen, enter your store information:

**Required Fields:**
- **Client ID** - Your client identifier (e.g., 1537)
- **Store ID** - Your store identifier (e.g., 13387)
- **PMSI Store ID** - Your PMSI store NPI (e.g., 1821516543)

💡 **Tip:** After entering these once, they'll be saved in a dropdown for quick reuse!

## Creating Test Data

### Step 1: Patient Information

Fill in the patient details:
- **First Name** - Patient's first name
- **Last Name** - Patient's last name
- **Date of Birth** - Format: YYYY-MM-DD (click 📅 for date picker)
- **Phone Number** - Patient's phone number

Click **Next** when done.

### Step 2: Add Prescriptions

Click **+ Add Prescription** to add each prescription:

**Prescription Fields:**
- **RX Number** - Leave blank for auto-generation
- **RX Status** - Choose from:
  - Active
  - Inactive
  - Pending
  - Expired
  - In Queue
  - Ready for Pickup
  - Picked Up
  - Shipped
  - Out of Refills
- **Medication Name** - Name of the medication
- **Strength** - Dosage strength (e.g., 10mg)
- **Units** - Unit type (e.g., tablet, capsule)
- **Last Fill Date** - When prescription was last filled (click 📅)
- **Expiration Date** - When prescription expires (click 📅)
- **Copay** - Dollar amount (e.g., 10.00)
- **PMSI Type** - Choose your PMSI system type:
  - PDX EPS
  - Liberty
  - McKesson
  - Epic
  - AtebGen100
  - PDX 275

Add as many prescriptions as needed, then click **Next**.

### Step 3: Review & Submit

Review all your data. Options:

**Save for Later:**
1. Enter a **Scenario Name**
2. Click **Save Scenario**
3. Reuse anytime from the dropdown!

**Personalization:**
- Check **"Enable Personalization"** to create DocumentDB entries for testing personalized features

Click **Submit** to upload your test data!

## Time-Saving Features

### Saved Store Configurations

After entering store info once, select from the **"Saved Stores"** dropdown to auto-fill:
- Client ID
- Store ID  
- PMSI Store ID

### Saved Scenarios

Save complete test scenarios (patient + prescriptions) for quick resubmission:

**To Save:**
1. On the Review screen, enter a scenario name
2. Click "Save Scenario"

**To Reuse:**
- **Load & Submit** - Instantly resubmit the same data
- **Load & Edit** - Load data, make changes, then submit

Scenarios are available on both the Patient Info and Review screens.

### Quick Scenario Submission

On the Patient Info screen:
1. Select a saved scenario from the dropdown
2. Click **"Load & Submit"** for instant submission
3. Or click **"Load & Edit"** to modify before submitting

## What Happens When You Submit?

1. **XML Files Generated** - Creates RefillResponse, RxResponse, and StatusResponse files
2. **Files Uploaded** - Uploads to PMSI simulator in the correct folder (PDX, Liberty, etc.)
3. **Personalization (Optional)** - Creates patient records in DocumentDB if enabled

You'll see a success message with all uploaded file paths!

## Testing Your Setup

Click the **"Test API"** button in the header to verify connectivity to the PMSI simulator.

## Common Scenarios

### Testing a Single Active Prescription
1. Enter patient info
2. Add one prescription with status "Active"
3. Leave RX Number blank (auto-generates)
4. Submit

### Testing Multiple Prescriptions for One Patient
1. Enter patient info once
2. Add multiple prescriptions (click + Add Prescription for each)
3. Each gets a unique RX number
4. All uploaded together

### Reusing Test Data
1. Create your test data once
2. Save as a scenario (e.g., "John Doe - 3 Active RX")
3. Next time: Load & Submit in seconds!

### Testing Personalization
1. Enable "Personalization" checkbox on Review screen
2. Submit
3. Patient record created in DocumentDB with all prescriptions
4. Test personalized IVR flows

## Tips & Tricks

✅ **Use the date picker** - Click 📅 instead of typing dates  
✅ **Save scenarios** - Reuse common test cases instantly  
✅ **Save stores** - Auto-fill store info for your clients  
✅ **Leave RX Number blank** - System generates unique numbers  
✅ **Test API first** - Verify connectivity before creating data  
✅ **Enable personalization** - For testing personalized features  

## Troubleshooting

**"Upload failed" error:**
- Click "Test API" to check connectivity
- Verify you're on the correct network/VPN
- Contact dev team if API is down

**"Validation Error":**
- Fill in all required fields (marked with *)
- Check date format: YYYY-MM-DD
- Ensure all prescription fields are complete

**App won't open (Mac):**

*"Can't be opened because Apple cannot check it for malicious software":*
1. **Right-click** (or Control+click) the app → "Open" (don't double-click!)
2. In the dialog, click "Open" again
3. If no "Open" button appears:
   - Go to System Settings → Privacy & Security
   - Scroll down to "Security" section
   - Click "Open Anyway" next to the app name
   - Try right-click → "Open" again

*"App is damaged and can't be opened":*
1. Open Terminal (Applications → Utilities → Terminal)
2. Type this command and press Enter:
   ```bash
   xattr -cr /Applications/PMSI_Data_Manager.app
   ```
3. Try opening the app again with right-click → "Open"

*"App is from an unidentified developer":*
1. System Settings → Privacy & Security
2. Under "Security" section, click "Open Anyway" next to the blocked app message
3. Try opening the app again with right-click → "Open"

*Still having issues?*
- Make sure you're running macOS 10.13 or later
- Check that you have admin privileges on your Mac
- Contact IT if corporate security policies are blocking the app

**App won't open (Windows):**
- Click "More info" → "Run anyway" on security warning
- Check with IT if antivirus is blocking

## Need Help?

Contact the development team or your QA lead for assistance.

---

**Version:** 2.0  
**Last Updated:** February 2025
