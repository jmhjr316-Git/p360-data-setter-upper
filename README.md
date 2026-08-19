# PMSI Simulator Data Management UI

A comprehensive cross-platform GUI application for managing PMSI simulator files and data with full environment support and personalization capabilities. This tool provides an easy-to-use interface for POs and QA teams to set up test data without needing to manually craft API calls.

## 🚀 Features

### Core Functionality
- **Cross-platform**: Works on Windows, Mac, and Linux
- **User-friendly GUI**: Simple form-based interface with intuitive controls
- **Environment Switching**: Toggle between QA and Staging environments seamlessly
- **Data validation**: Ensures required fields are filled and formats are correct
- **Save/Load functionality**: Save data configurations for reuse
- **Expandable design**: Easy to add new data fields as requirements evolve
- **Preview functionality**: Review data before processing

### Advanced Features
- **XML File Generation**: Creates RefillResponse, RxResponse, and StatusResponse files
- **Template System**: Token-based XML generation with smart date logic
- **Direct Upload**: Upload files directly to PMSI simulator via API
- **Personalization Integration**: Create DocumentDB entries for personalized testing
- **RX Number Management**: Auto-generation with conflict detection
- **Status Mapping**: 9 comprehensive RX statuses with proper PDX codes
- **Search Functionality**: Find records in DocumentDB by RX number or patient name

## 📋 Data Fields Supported

### Environment Configuration
- **Environment Selection** (QA/Staging) *

### Patient Information
- Patient First Name *
- Patient Last Name *
- Patient Date of Birth (YYYY-MM-DD) *
- Patient Phone Number *

### Prescription Information
- RX Number (auto-generated if blank)
- RX Status (Active/Inactive/Pending/Expired/In Queue/Ready for Pickup/Picked Up/Shipped/Out of Refills) *
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

### PMSI Configuration
- PMSI Type (PDX EPS/Liberty/McKesson/Epic/AtebGen100/PDX 275) *
- Enable Personalization (checkbox)

*Required fields

## 🛠 Installation & Setup

### Prerequisites
- Python 3.6 or higher
- Internet connection (for API calls and DocumentDB)

### Quick Start (Recommended)
1. Download all files to a folder
2. Run the enhanced launcher:
   ```bash
   python setup_and_run.py
   ```
   The launcher will automatically install required dependencies if needed.

### Windows Quick Start
1. Download all files to a folder
2. Double-click `run_pmsi_manager.bat`
   This will install dependencies and launch the application.

### Manual Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the application:
   ```bash
   python pmsi_data_ui.py
   ```

### Dependencies
- `requests>=2.25.0` - API communication
- `tkcalendar>=1.6.0` - Enhanced date picker
- `pymongo>=4.0.0` - DocumentDB connectivity

## 🎯 Usage Guide

### Basic Workflow
1. **Select Environment**: Choose QA or Staging from the dropdown
2. **Fill out the form**: Enter all required data fields (marked with *)
3. **Choose Action**:
   - **Generate Preview**: Validate data and see formatted preview
   - **Generate Files**: Create XML files locally
   - **Upload to Simulator**: Generate and upload files to PMSI simulator
4. **Optional**: Enable personalization to create DocumentDB entries

### Advanced Features

#### Environment Switching
- Use the Environment dropdown at the top of the form
- Window title shows current environment
- All API calls and database connections automatically switch

#### RX Number Management
- Leave RX Number blank for auto-generation
- System checks for conflicts and offers resolution options
- Consistent numbering across all operations

#### Status-Based Auto-Population
- Selecting different RX statuses automatically populates related date fields
- Smart date logic based on prescription lifecycle

#### Personalization (DocumentDB Integration)
- Check "Enable Personalization" to create patient records
- Supports both new patients and adding prescriptions to existing patients
- Local backup files created for all DocumentDB entries

#### Search & Verification
- **Search DocDB**: Find records by RX number or patient name
- **Check RX Exists**: Verify if RX number already exists in simulator

## 📁 File Structure

```
Data_setter_upper/
├── pmsi_data_ui.py                    # Main UI application
├── launch.py                          # Basic launcher (legacy)
├── setup_and_run.py                  # Enhanced launcher with dependency management
├── run_pmsi_manager.bat              # Windows batch launcher
├── requirements.txt                   # Python dependencies
├── environment_config.json            # Environment configuration
├── README.md                         # This file
├── templates/                        # XML template system
│   ├── template_config.json          # Status mappings and configurations
│   ├── RefillResponse_template.xml   # Refill response template
│   ├── RxResponse_template.xml       # RX response template
│   ├── StatusResponse_template.xml   # Status response template
│   └── PDXEpsConfig.json             # PDX configuration codes
├── samplePDX/                        # Sample XML files for reference
│   ├── RefillResponse1001000.xml
│   ├── RxResponse1001000.xml
│   └── StatusResponse1001000.xml
└── Data_setter_upper container config.txt  # API documentation
```

## 🔧 Configuration

### Environment Configuration
Edit `environment_config.json` to modify environment settings:

```json
{
  "environments": {
    "QA": {
      "name": "QA Environment",
      "pmsi_api_url": "https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co",
      "documentdb_connection": "mongodb://...",
      "documentdb_database": "p360_daily_docker"
    },
    "Staging": {
      "name": "Staging Environment",
      "pmsi_api_url": "https://staging-url-here",
      "documentdb_connection": "mongodb://...",
      "documentdb_database": "staging_db"
    }
  },
  "default_environment": "QA"
}
```

### Adding New Data Fields
The application is designed to be easily expandable. To add new fields:

1. Open `pmsi_data_ui.py`
2. Find the `self.data_fields` dictionary in the `__init__` method
3. Add new fields to existing sections or create new sections:

```python
"New Section": {
    "new_field": {
        "label": "New Field Label", 
        "type": "text",  # or "dropdown", "number", "date", "checkbox"
        "required": True,  # or False
        "options": ["Option1", "Option2"]  # only for dropdown type
    }
}
```

Supported field types:
- `text`: Regular text input
- `number`: Numeric input
- `date`: Date input (YYYY-MM-DD format) with calendar picker
- `dropdown`: Dropdown selection with predefined options
- `checkbox`: Boolean checkbox input

## 🏗 Creating Installers

### Option 1: PyInstaller (Single Executable)
Create a standalone executable that includes all dependencies:

```bash
# Install PyInstaller
pip install pyinstaller

# Create single executable
pyinstaller --onefile --windowed --add-data "templates;templates" --add-data "environment_config.json;." pmsi_data_ui.py

# Output will be in dist/pmsi_data_ui.exe
```

**Pros**: Single file, no Python installation needed, works on any Windows machine
**Cons**: Large file size (~50-100MB), slower startup

### Option 2: Distribution Package
Create a folder with all necessary files:

```
PMSI_Data_Manager_v1.0/
├── run_pmsi_manager.bat          # Windows users double-click this
├── setup_and_run.py              # Cross-platform launcher
├── pmsi_data_ui.py               # Main application
├── requirements.txt              # Dependencies
├── environment_config.json       # Environment settings
├── templates/                    # Template files
├── README.md                     # Instructions
└── INSTALL.txt                   # Simple setup guide
```

### Option 3: Advanced PyInstaller with Icon
```bash
# With custom icon and better optimization
pyinstaller --onefile --windowed --icon=app_icon.ico --add-data "templates;templates" --add-data "environment_config.json;." --name "PMSI_Data_Manager" pmsi_data_ui.py
```

## 🔌 API Integration

### PMSI Simulator API
The application integrates with the PMSI simulator API for file management:

**Base URLs:**
- QA: `https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co`
- Staging: `https://ivr-mock-svcs.pc.s.awscloud.private/`

**Endpoints:**
- File Upload: `/pms-manage?action=write&file_path={path}&content={content}`
- File List: `/pms-manage?action=list&file_path={path}`
- File Read: `/files/{path}`

### DocumentDB Integration
Supports personalization through DocumentDB connections:

**Databases:**
- QA: `p360_daily_docker.patient`
- Staging: `p360.patient`

**Operations:**
- Create new patient records
- Add prescriptions to existing patients
- Search by RX number or patient name
- Local backup of all entries

## 🐛 Troubleshooting

### Common Issues

1. **"Module not found" errors**: 
   ```bash
   pip install -r requirements.txt
   ```

2. **GUI doesn't appear**: 
   - Ensure you have a display/desktop environment
   - On Linux: `sudo apt-get install python3-tk`
   - On Mac: `brew install python-tk`

3. **API connection issues**: 
   - Check network connectivity
   - Verify environment URLs in `environment_config.json`
   - Check if PMSI simulator services are running

4. **DocumentDB connection issues**:
   - Verify connection strings in environment config
   - Check SSL certificate settings
   - Ensure database permissions

5. **Calendar picker not visible**:
   - Widen the application window
   - Install tkcalendar: `pip install tkcalendar`

### Platform-Specific Notes

- **Windows**: Should work out of the box with Python installation
- **Mac**: May need to install tkinter: `brew install python-tk`
- **Linux**: May need to install tkinter: `sudo apt-get install python3-tk`

### Debug Mode
Run with debug output:
```bash
python pmsi_data_ui.py --debug
```

## 🔄 Container Setup Integration

The application works with the container-based PMSI simulator setup. This section provides detailed instructions for setting up the required container infrastructure.

### Architecture Overview

The PMSI Data Management UI integrates with a multi-container setup:

```
[PMSI Data UI] → [IVR Mock Services] → [Python Proxy] → [PMSI Simulator]
     ↓                    ↓                 ↓              ↓
  GUI Client         WireMock           Port 8081      Tomcat JSP
                   (Port 8080)       Proxy Server    (Port 8181)
```

### Container Setup Instructions

#### 1. PMSI Simulator Container (pmssim)

**Create File Management Infrastructure:**

```bash
# Create symlink for file reads (from pmssim container)
rm -rf /pms-simulator/apache-tomcat-7.0.69/webapps/files
ln -s /pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/WEB-INF/rsp /pms-simulator/apache-tomcat-7.0.69/webapps/files
```

**Create File Management JSP:**

```bash
# Create manage.jsp for file operations (from pmssim container)
cat > /pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/manage.jsp << 'EOF'
<%@ page import="java.io.*,java.nio.file.*" %>
<%
String action = request.getParameter("action");
String filePath = request.getParameter("file_path");
String content = request.getParameter("content");
String basePath = "/pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/WEB-INF/rsp";

response.setContentType("application/json");

try {
    File fullPath = new File(basePath, filePath);

    if ("write".equals(action)) {
        fullPath.getParentFile().mkdirs();
        FileWriter writer = new FileWriter(fullPath);
        writer.write(content);
        writer.close();
        out.println("{\"status\":\"success\",\"message\":\"File written\"}");
    } else if ("delete".equals(action)) {
        fullPath.delete();
        out.println("{\"status\":\"success\",\"message\":\"File deleted\"}");
    } else if ("list".equals(action)) {
        if (fullPath.isDirectory()) {
            File[] files = fullPath.listFiles();
            out.print("{\"status\":\"success\",\"files\":[");
            for (int i = 0; i < files.length; i++) {
                out.print("\"" + files[i].getName() + "\"");
                if (i < files.length - 1) out.print(",");
            }
            out.println("]}");
        } else {
            out.println("{\"error\":\"Not a directory\"}");
        }
    }
} catch (Exception e) {
    response.setStatus(500);
    out.println("{\"error\":\"" + e.getMessage() + "\"}");
}
%>
EOF
```

#### 2. IVR Mock Services Container (ivr-mock-svcs)

**Create Proxy Script:**

```bash
# Create proxy script (from ivr-mock-svcs container)
cat > /tmp/pms_proxy.sh << 'EOF'
#!/bin/bash
ACTION="$1"
FILE_PATH="$2"
CONTENT="$3"

curl -s -X POST "http://pmssim:8181/FsiXmlSimulator/manage.jsp" \
  -d "action=${ACTION}&file_path=${FILE_PATH}&content=${CONTENT}"
EOF

chmod +x /tmp/pms_proxy.sh
```

**Create Python Proxy Server:**

```bash
# Create Python proxy server (from ivr-mock-svcs container)
cat > /tmp/simple_proxy.py << 'EOF'
#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess, urllib.parse

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        action = params.get('action', [''])[0]
        file_path = params.get('file_path', [''])[0]
        content = params.get('content', [''])[0]

        try:
            result = subprocess.run(['/tmp/pms_proxy.sh', action, file_path, content],
                                  capture_output=True, text=True)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(result.stdout.encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'{{"error": "{str(e)}"}}'.encode())

HTTPServer(('127.0.0.1', 8081), SimpleHandler).serve_forever()
EOF

# Start the proxy server
python3 /tmp/simple_proxy.py &
```

**Configure WireMock Mappings:**

```bash
# Configure WireMock mappings for file operations
curl -X POST http://localhost:8080/__admin/mappings \
  -H "Content-Type: application/json" \
  -d '{
    "request": {
      "method": "GET",
      "urlPathPattern": "/files/.*"
    },
    "response": {
      "proxyBaseUrl": "http://pmssim:8181"
    }
  }'

curl -X POST http://localhost:8080/__admin/mappings \
  -H "Content-Type: application/json" \
  -d '{
    "request": {
      "method": "GET",
      "urlPathPattern": "/pms-manage.*"
    },
    "response": {
      "proxyBaseUrl": "http://127.0.0.1:8081"
    }
  }'
```

### Container Deployment Integration

#### For pmssim container:
- Add the symlink and JSP creation to the container startup script
- Ensure the JSP file persists across deployments
- Verify Tomcat is running on port 8181

#### For ivr-mock-svcs container:
- Add the proxy script and Python server to the container startup script
- Add the WireMock mapping configuration to the startup process
- Ensure python3 is available in the container
- Verify WireMock is running on port 8080

### API Usage Examples

Once the containers are properly configured, you can test the API endpoints:

**Read Files:**
```bash
# Read any file
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/files/PDX/RefillResponse1001000.xml'
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/files/NYC/test.xml'
```

**List Files:**
```bash
# List files in PDX folder
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=list&file_path=PDX'

# List files in root directory
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=list&file_path='

# List files in any subfolder
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=list&file_path=NYC/subfolder'
```

**Write/Update Files:**
```bash
# Write to PDX folder
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=write&file_path=PDX/test.xml&content=<xml>test content</xml>'

# Write to any folder (creates folders automatically)
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=write&file_path=NYC/response.xml&content=<xml>NYC content</xml>'

# Update existing files (same command)
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=write&file_path=PDX/RefillResponse1001000.xml&content=<xml>updated</xml>'
```

**Delete Files:**
```bash
# Delete any file
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=delete&file_path=PDX/test.xml'
curl 'https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=delete&file_path=NYC/response.xml'
```

### Service Health Checks
- PMSI Simulator: `http://pmssim:8181/FsiXmlSimulator/`
- IVR Mock Services: `https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/pms-manage?action=list&file_path=`
- DocumentDB: Connection test via "Search DocDB" button

### Troubleshooting API Hangs

If list/write operations hang but read operations work:

```bash
# SSH into ivr-mock-svcs container
kubectl exec -it <ivr-mock-svcs-pod> -- /bin/bash

# Kill and restart the Python proxy
pkill -f simple_proxy.py
python3 /tmp/simple_proxy.py &

# Verify it's running
ps aux | grep simple_proxy.py
```

The Python proxy on port 8081 can get into a hung state and needs periodic restarts.

## 📈 Future Enhancements

### Planned Features
1. **Multi-RX Support**: Add multiple prescriptions per patient in a single session
2. **Batch Processing**: Upload multiple configurations at once
3. **Data Templates**: Pre-defined patient/prescription templates
4. **Audit Logging**: Track all operations and changes
5. **Export/Import**: Bulk data operations
6. **Advanced Search**: More sophisticated DocumentDB queries

### Multi-RX Implementation Options
- **Multi-Step Wizard**: Patient info → Multiple RXs → Review → Submit
- **Tabbed Interface**: Patient Tab → Prescriptions Tab → Submit Tab
- **Add Another RX**: Current form + "Add Another RX" button

## 📞 Support

For issues or feature requests:
1. Check the troubleshooting section above
2. Review error logs (automatically created in project folder)
3. Contact the development team
4. Create tickets in your project management system

## 📄 License

Internal tool for EnlivenHealth platform testing and development.

---

**Version**: 2.0  
**Last Updated**: February 2026  
**Compatibility**: Python 3.6+, Windows/Mac/Linux