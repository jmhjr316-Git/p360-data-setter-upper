# PMSI Simulator Data Management UI

A cross-platform GUI application for managing PMSI simulator files and data. This tool provides an easy-to-use interface for POs and QA teams to set up test data without needing to manually craft API calls.

## Features

- **Cross-platform**: Works on Windows, Mac, and Linux
- **User-friendly GUI**: Simple form-based interface
- **Data validation**: Ensures required fields are filled and formats are correct
- **Save/Load functionality**: Save data configurations for reuse
- **Expandable design**: Easy to add new data fields as requirements evolve
- **Preview functionality**: Review data before processing

## Data Fields Supported

### Patient Information
- Patient First Name *
- Patient Last Name *
- Patient Date of Birth (YYYY-MM-DD) *
- Patient Phone Number *

### Prescription Information
- RX Status (Active/Inactive/Pending/Expired) *
- Medication Name *
- Strength *
- Units *
- Last Fill Date (YYYY-MM-DD) *
- Expiration Date (YYYY-MM-DD) *
- Copay ($) *

### Store Information
- Client ID *
- Store ID *
- PMSI Store ID *

*Required fields

## Installation & Setup

### Prerequisites
- Python 3.6 or higher
- Internet connection (for API calls)

### Quick Start
1. Download all files to a folder
2. Run the launcher:
   ```bash
   python launch.py
   ```
   The launcher will automatically install required dependencies if needed.

### Manual Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the application:
   ```bash
   python pmsi_data_ui.py
   ```

## Usage

1. **Fill out the form**: Enter all required data fields (marked with *)
2. **Generate Preview**: Click to validate data and see a formatted preview
3. **Save Data**: Save current form data to a JSON file for later use
4. **Load Data**: Load previously saved data configurations
5. **Clear All**: Reset all form fields

## File Structure

```
Data_setter_upper/
├── pmsi_data_ui.py          # Main UI application
├── launch.py                # Launcher script with dependency checking
├── requirements.txt         # Python dependencies
├── README.md               # This file
└── Data_setter_upper container config.txt  # API documentation
```

## Adding New Data Fields

The application is designed to be easily expandable. To add new fields:

1. Open `pmsi_data_ui.py`
2. Find the `self.data_fields` dictionary in the `__init__` method
3. Add new fields to existing sections or create new sections:

```python
"New Section": {
    "new_field": {
        "label": "New Field Label", 
        "type": "text",  # or "dropdown", "number", "date"
        "required": True,  # or False
        "options": ["Option1", "Option2"]  # only for dropdown type
    }
}
```

Supported field types:
- `text`: Regular text input
- `number`: Numeric input
- `date`: Date input (YYYY-MM-DD format)
- `dropdown`: Dropdown selection with predefined options

## API Integration

The application is configured to work with the PMSI simulator API documented in the container config file. The base URL is:
```
https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co
```

## Next Steps

This UI captures and validates the data. The next phase will involve:
1. Creating file templates with replaceable tokens
2. Implementing file generation functionality
3. Adding direct API integration for file upload/management
4. Adding batch processing capabilities

## Troubleshooting

### Common Issues

1. **"Module not found" errors**: Run `pip install -r requirements.txt`
2. **GUI doesn't appear**: Ensure you have a display/desktop environment
3. **API connection issues**: Check network connectivity and API availability

### Platform-Specific Notes

- **Windows**: Should work out of the box with Python installation
- **Mac**: May need to install tkinter: `brew install python-tk`
- **Linux**: May need to install tkinter: `sudo apt-get install python3-tk`

## Support

For issues or feature requests, please refer to the development team or create appropriate tickets in your project management system.