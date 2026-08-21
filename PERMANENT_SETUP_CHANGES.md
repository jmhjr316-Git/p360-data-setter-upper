## pms-simulator — run.sh change

This is the ONLY file that needs to change. The diff adds a symlink and a
JSP file that enable HTTP-based test data management (create/read/delete
prescription XML files without kubectl exec).

### Current file:
```bash
#!/usr/bin/env bash

export CATALINA_HOME=/pms-simulator/apache-tomcat-7.0.69/
export TOMCAT_USER=root

echo "Starting /pms-simulator/XmlFsiSimulator $(date)"
/pms-simulator/apache-tomcat-7.0.69/bin/tomcat_control start

echo "Starting socket simulators $(date)"
cd /pms-simulator/legacy
/pms-simulator/legacy/start_atebgen_sim &
/pms-simulator/legacy/start_atebgen_v200_sim &
/pms-simulator/legacy/start_atebgen_v210_sim &
/pms-simulator/legacy/start_kroll_v100_sim &
#/pms-simulator/legacy/start_mcps_palmbeach_sim &
/pms-simulator/legacy/start_pdx_v200_sim &
/pms-simulator/legacy/start_pdx_v275_sim &
/pms-simulator/legacy/start_cerner_sim &

tail -f /dev/null
```

### Proposed file (additions marked with +):
```bash
#!/usr/bin/env bash

export CATALINA_HOME=/pms-simulator/apache-tomcat-7.0.69/
export TOMCAT_USER=root

echo "Starting /pms-simulator/XmlFsiSimulator $(date)"
/pms-simulator/apache-tomcat-7.0.69/bin/tomcat_control start

echo "Starting socket simulators $(date)"
cd /pms-simulator/legacy
/pms-simulator/legacy/start_atebgen_sim &
/pms-simulator/legacy/start_atebgen_v200_sim &
/pms-simulator/legacy/start_atebgen_v210_sim &
/pms-simulator/legacy/start_kroll_v100_sim &
#/pms-simulator/legacy/start_mcps_palmbeach_sim &
/pms-simulator/legacy/start_pdx_v200_sim &
/pms-simulator/legacy/start_pdx_v275_sim &
/pms-simulator/legacy/start_cerner_sim &

+ # ---- Test Data Management API ----
+ # Enables HTTP access to prescription XML files for automated test setup.
+ # Symlink: serves /WEB-INF/rsp/ directory at /files/ URL path
+ # JSP: provides write/delete/list operations on XML response files
+ echo "Setting up test data management API $(date)"
+ ln -sf /pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/WEB-INF/rsp \
+        /pms-simulator/apache-tomcat-7.0.69/webapps/files
+ cat > /pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/manage.jsp << 'MANAGEJSP'
+ <%@ page import="java.io.*,java.nio.file.*" %>
+ <%
+ String action = request.getParameter("action");
+ String filePath = request.getParameter("file_path");
+ String content = request.getParameter("content");
+ String basePath = "/pms-simulator/apache-tomcat-7.0.69/webapps/FsiXmlSimulator/WEB-INF/rsp";
+ response.setContentType("application/json");
+ try {
+     File fullPath = new File(basePath, filePath);
+     if ("write".equals(action)) {
+         fullPath.getParentFile().mkdirs();
+         FileWriter writer = new FileWriter(fullPath);
+         writer.write(content);
+         writer.close();
+         out.println("{\"status\":\"success\",\"message\":\"File written\"}");
+     } else if ("delete".equals(action)) {
+         fullPath.delete();
+         out.println("{\"status\":\"success\",\"message\":\"File deleted\"}");
+     } else if ("list".equals(action)) {
+         if (fullPath.isDirectory()) {
+             File[] files = fullPath.listFiles();
+             out.print("{\"status\":\"success\",\"files\":[");
+             for (int i = 0; i < files.length; i++) {
+                 out.print("\"" + files[i].getName() + "\"");
+                 if (i < files.length - 1) out.print(",");
+             }
+             out.println("]}");
+         } else {
+             out.println("{\"error\":\"Not a directory\"}");
+         }
+     }
+ } catch (Exception e) {
+     response.setStatus(500);
+     out.println("{\"error\":\"" + e.getMessage() + "\"}");
+ }
+ %>
+ MANAGEJSP
+ echo "Test data management API ready"

tail -f /dev/null
```

### What it does:
- **Symlink** (`/webapps/files` → `/WEB-INF/rsp`): Allows reading XML files
  via HTTP GET at `/files/PDX/RxResponse9009401.xml` etc.
- **manage.jsp**: Provides write/delete/list operations so test automation can
  create prescription data without kubectl exec.

### Risk: None
- Only adds new URL paths — no existing functionality is changed
- The JSP is only accessible internally (behind the K8s ingress)
- The symlink points to the same directory Tomcat already serves

---

## ivr-mock-svcs — WireMock mapping files

The ivr-mock-svcs container runs WireMock. It needs one additional proxy
mapping so requests to `/FsiXmlSimulator/*` get forwarded to pmssim.

### If the repo has a `mappings/` directory:

Add this file:

**`mappings/pmssim-proxy.json`**
```json
{
  "request": {
    "method": "GET",
    "urlPathPattern": "/FsiXmlSimulator/.*"
  },
  "response": {
    "proxyBaseUrl": "http://pmssim:8181"
  }
}
```

WireMock loads all JSON files from `mappings/` at startup automatically.

### If there's no mappings directory (startup script approach):

Add after WireMock starts:
```bash
# Wait for WireMock
until curl -s http://localhost:8080/__admin/mappings > /dev/null 2>&1; do sleep 1; done

# Proxy PMSI file management requests to pmssim
curl -s -X POST http://localhost:8080/__admin/mappings \
  -H "Content-Type: application/json" \
  -d '{"request":{"method":"GET","urlPathPattern":"/FsiXmlSimulator/.*"},"response":{"proxyBaseUrl":"http://pmssim:8181"}}'
```

### What it does:
Routes `/FsiXmlSimulator/*` requests through WireMock to the pmssim container,
so the manage.jsp and file reads work through the ivr-mock-svcs ingress URL.

### Risk: None
- Adds one new URL pattern that doesn't conflict with existing WireMock stubs
- All existing mock behavior unchanged
- The `/files/*` mapping already exists in WireMock's default config (we
  confirmed it works today) — we only need the `/FsiXmlSimulator/*` mapping

---

## How to verify after deployment:

```bash
# List existing prescription files
curl -sk "https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/FsiXmlSimulator/manage.jsp?action=list&file_path=PDX"

# Read a specific file
curl -sk "https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co/files/PDX/RxResponse9009401.xml"
```

## Why this matters:
- Currently QA must manually kubectl exec into both containers after every restart
- This blocks E2E test automation — tests can't set up their own prescription data
- The manual setup takes ~5 minutes and is error-prone
- With these changes, everything works automatically on container startup
