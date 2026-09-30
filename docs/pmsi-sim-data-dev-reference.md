# PMSI Simulator Data — Developer Reference

A hands-on reference for setting up prescription test data in the PMS simulator and verifying it
through `pms-services`. Covers all four HTTP-based PMS adapters (PDX EPS, McKesson, Liberty, Epic),
the raw curl calls, the Python helper library, and the gotchas that will otherwise cost you an hour.

> Scope: the four adapters exercised by the IVR / Posting App flows. The socket adapters
> (PDX 275, RX30/AtebGen) are noted where relevant but not the focus.

---

## 1. The big picture

```
                         ┌─────────────────────────────────────────────┐
   your test  ─────────► │  pms-services  (the thing under test)        │
   (Rx Info or Refill)   │  /cxf/api/pms/v2/clients/{clientId}/rxs...   │
                         └───────────────┬─────────────────────────────┘
                                         │ picks adapter by client+store (ateb DB config)
                        ┌────────────────┴───────────────────┐
                        ▼                                     ▼
           manage.jsp (Tomcat sim)                WireMock (ivr-mock-svcs)
           PDX EPS  → PDX/*.xml                   Liberty → liberty/*.json
           McKesson → PerSe/*.xml                 Epic    → epic/2018/soap11/*.xml
```

- **pms-services** is the integration service. You call it; it calls the sim; it maps the sim's
  response into a normalized DTO and returns that to you.
- Which sim backend + store a given `clientId` uses is configured in the **ateb DB** (`pms.clientconfig`
  / `pms.storeconfig` / `pms.connectionconfig`). You normally don't touch this — the stores below are
  already configured in QA.
- **Two transaction types** matter: **Rx Info** (`requestType=INFO`, a GET) and **Refill submit**
  (a POST). They read *different* sim files.

### QA client/store cheat-sheet

| PMS | clientId | storeId | Sim backend | Files per rx |
|-----|----------|---------|-------------|--------------|
| PDX EPS | 9001 (or 8000) | 70050001 | manage.jsp `PDX/` | RxResponse, StatusResponse, RefillResponse |
| McKesson | 9001 | 125 | manage.jsp `PerSe/` | RxInfoRsp, SubmitIVROrderRsp |
| Liberty | 9001 | 8174884613 | WireMock `liberty/` | libertyquery, libertystatus, libertyrefill |
| Epic (SOAP 1.1) | 5014 | 9759001 | WireMock `epic/2018/soap11/` | GetPrescriptionInfoResponse, RequestFillsResponse |

### Base URLs (QA)

| Thing | URL |
|-------|-----|
| pms-services | `https://pms-services.pc.q.awscloud.private/cxf/api/pms` |
| manage.jsp (PDX/McKesson) | `https://pmssim.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp` |
| WireMock (Liberty/Epic) | `https://ivr-mock-svcs.pc.q.awscloud.private` |

Staging: pms-services `https://pms-services-ocp-sit.k8s.raleng.omnicell.com`; WireMock
`https://ivr-mock-svcs.pc.s.awscloud.private`; manage.jsp via IP `10.13.60.40` + header
`Host: pmssim-ocp-sit.k8s.raleng.omnicell.com` (DNS CNAME never created).

### Auth

All pms-services calls need `Authorization: Bearer <token>`. Easiest is the long-lived OMCL
super-admin token (RS256, env-agnostic, `iss: OMCL`, role `ope:clientId:*:storeId:*`). It's in
`~/.kiro/platform-tools.md` and in `messaging_service/.env.staging` (`AUTH_TOKEN`). The sim
(manage.jsp / WireMock admin) needs **no** auth.

---

## 2. The two calls you'll make against pms-services

### Rx Info (GET)
```bash
curl -sk "https://pms-services.pc.q.awscloud.private/cxf/api/pms/v2/clients/9001/rxs/{RX}\
?requestSource=IVR&requestType=INFO&storeId={STORE}&storeTzOffset=-04:00" \
  -H "Authorization: Bearer $TOKEN"
```
Returns the normalized rx (drug, patient, refills, status). 404 usually = store not configured or
rx file missing; `pms.connection.error` (503) usually = the sim response failed XSD validation.

### Refill submit (POST)
```bash
curl -sk -X POST "https://pms-services.pc.q.awscloud.private/cxf/api/pms/v2/clients/9001/rxs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "requestStoreNum":"{STORE}",
        "requestSource":"IVR",
        "storeTzOffset":"-04:00",
        "deliveryMethod":"PICKUP",
        "rxs":[{"rxNum":"{RX}","rxIdxInOrder":1,"lastFillStoreNum":"{STORE}",
                "authorizeAdditionalRefills":true,"allowGenericSubstitution":true}]
      }'
```
Returns `{"rxs":[{"refillAccepted":true|false,"details":{"rxStatus":...,"refillStatus":...}}]}`.

**Request-body requirements (bit me, will bite you):**
- `requestSource` and `storeTzOffset` are ALWAYS required (else HTTP 400).
- **Liberty ALSO requires** top-level `pickupDate` (YYYYMMDD, ≥8 chars) + `pickupTime` (HHMMSS,
  ≥6 chars) — otherwise the adapter throws `DataInvalidException`. PDX/McKesson/Epic do not.

---

## 3. Setting up sim data — raw calls

### manage.jsp (PDX EPS + McKesson)

5 actions: `write`, `append`, `delete`, `read`, `list`. GET with query params; content must be
URL-encoded on `write`.

```bash
SIM="https://pmssim.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp"

# list a directory
curl -sk "$SIM?action=list&file_path=PDX"

# read a file (text/plain, or {"error":"Not a file"})
curl -sk "$SIM?action=read&file_path=PDX/RxResponse9009401.xml"

# write a file (URL-encode the XML)
CONTENT=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(open('/tmp/rx.xml').read()))")
curl -sk "$SIM?action=write&file_path=PDX/RxResponse{RX}.xml&content=$CONTENT"

# delete
curl -sk "$SIM?action=delete&file_path=PDX/RxResponse{RX}.xml"
```
- **PDX** files: `PDX/RxResponse{RX}.xml`, `PDX/StatusResponse{RX}.xml`, `PDX/RefillResponse{RX}.xml`.
- **McKesson** files: `PerSe/RxInfoRsp{RX}.xml`, `PerSe/SubmitIVROrderRsp{RX}.xml`.
- PDX XML is validated against `EPS_ATEB_IVR.xsd`. Invalid XML → `pms.connection.error`. Check the sim
  log inside the pod: `/pms-simulator/apache-tomcat-7.0.69/logs/FsiXmlSimulator.log` for
  `[Invalid response document]`.

### WireMock (Liberty + Epic)

Files are managed via the admin API. **No auth.**

```bash
WM="https://ivr-mock-svcs.pc.q.awscloud.private"

# upload / overwrite
curl -sk -X PUT "$WM/__admin/files/liberty/libertyquery{RX}.json" \
  --data-binary @/tmp/query.json -H "Content-Type: application/octet-stream"

# delete
curl -sk -X DELETE "$WM/__admin/files/liberty/libertyquery{RX}.json"

# list all files
curl -sk "$WM/__admin/files"

# read a file's CONTENT — use the SERVED route, NOT /__admin/files/<path> (that GET is 404):
curl -sk "$WM/liberty/libertyquery{RX}.json"                 # static __files path
curl -sk "$WM/libertypms/prescription/{RX}"                  # served route
```

- **Liberty** files: `liberty/libertyquery{RX}.json`, `liberty/libertystatus{RX}.json`,
  `liberty/libertyrefill{RX}.json`.
- **Epic** files (names include rx AND store NCPDP):
  `epic/2018/soap11/GetPrescriptionInfoResponse-{RX}-{NCPDP}.xml`,
  `epic/2018/soap11/RequestFillsResponse-{RX}-{NCPDP}.xml`.
- **WireMock routing:**
  - `GET /libertypms/prescription/{RX}` → serves `libertyquery{RX}.json`
  - `GET /libertypms/refill/{RX}` → serves `libertystatus{RX}.json`
  - `POST /libertypms/refill` (body is a JSON array with `ScriptNumber`) → serves `libertyrefill{RX}.json`
- ⚠️ **WireMock caches templated response files.** The refill POST route templates its filename from
  the request body (`response-template` transformer). After you PUT an updated `libertyrefill` /
  `RequestFillsResponse`, you MUST reset or the OLD content is served:
  ```bash
  curl -sk -X POST "$WM/__admin/mappings/reset"
  ```
  Plain GET-by-path files (query/status/info) don't need this.

---

## 4. The Python helper library (recommended)

`tests/helpers_pms_sim.py` in this repo builds XSD-valid data for all PMS types from a desired status,
and (with `include_p360=True`) a matching P360 patient doc. This is the same code the automation and
the UI use.

```python
import sys, urllib3; urllib3.disable_warnings()
sys.path.insert(0, "/mnt/c/Code/Data_setter_upper")
from tests.helpers_pms_sim import (
    set_environment,
    build_scenario, upload_scenario, delete_rx, RxStatus,                    # PDX
    build_mckesson_scenario, upload_mckesson_scenario, McKessonStatus,
    build_liberty_scenario,  upload_liberty_scenario,  LibertyStatus,
    build_epic_scenario,     upload_epic_scenario,     EpicStatus,
)

set_environment("qa")            # or "staging"

# PDX — a refillable rx (Rx Info + Status + Refill all valid)
scenario = build_scenario(
    rx_status=RxStatus.REFILLABLE,
    rx_number="7249001",
    patient_first="JANE", patient_last="SMITH",
    patient_phone="7249143802", patient_dob="19850601",
    drug_name="METFORMIN 500MG TAB",
    store_number="70050001", client_id=9001,
    include_p360=True,           # also builds the matching P360 doc
)
upload_scenario(scenario)        # writes sim files (+ upserts P360 if include_p360)

# Liberty / McKesson / Epic — same shape, different builder:
s = build_liberty_scenario(status=LibertyStatus.REFILLABLE, rx_number="1000100",
                           store_number="8174884613", client_id=9001)
upload_liberty_scenario(s)
```

Notes:
- **Status-driven.** You pass the outcome you want (e.g. `READY_FOR_PICKUP`, `REFILLABLE`,
  `NOT_REFILLABLE`, `TOO_SOON`, `CONTROLLED_SUBSTANCE`) and the builder generates all the fields.
  Each PMS has its own status enum (`RxStatus`, `McKessonStatus`, `LibertyStatus`, `EpicStatus`).
- **P360 matching is critical for personalization.** `medication.ndc`, `fillDate`, `atebPatientId`,
  and `rxNum` must match between the P360 doc and what pms-services returns, or personalization
  silently no-ops. Always build with `include_p360=True` rather than hand-rolling the P360 doc.
  (PDX EPS returns no NDC, so NDC isn't part of the PDX match; the others do match NDC.)
- The Liberty/Epic uploaders auto-reset WireMock mappings for you.

---

## 5. Failed postings — making the refill SUBMIT reject

For testing the Posting App / IVR failure path where **Rx Info succeeds but the refill submit is
rejected by the PMS** (`refillAccepted=false`, which drives `COMPLETE_WITH_FAILURES`):

```python
# Uniform API — add refill_outcome="REJECTED" to any of the four builders.
build_scenario(rx_status=RxStatus.REFILL_REJECTED, rx_number=...)      # PDX shorthand
build_scenario(..., refill_outcome="REJECTED")                        # PDX
build_liberty_scenario(...,  refill_outcome="REJECTED")
build_mckesson_scenario(..., refill_outcome="REJECTED")
build_epic_scenario(...,     refill_outcome="REJECTED")
```
UI: Add/Edit Rx dialog → "Refill Submission" dropdown → *Rejected*.

**What each produces in the refill-submit file** (Rx Info/query stays valid):

| PMS | File | Rejection marker | pms-services result |
|-----|------|------------------|---------------------|
| PDX | `PDX/RefillResponse{RX}.xml` | root `<rxStatusResponse>` + `<msgStatusCode>900` | `refillAccepted:false`, UNKNOWN |
| Liberty | `liberty/libertyrefill{RX}.json` | `Status:"Invalid_Script_Number"` | `refillAccepted:false`, REJECTED |
| McKesson | `PerSe/SubmitIVROrderRsp{RX}.xml` | MsgHeader `MsgName="GenericFailureRsp"` | `refillAccepted:false`, REJECTED |
| Epic | `epic/2018/soap11/RequestFillsResponse-{RX}-{NCPDP}.xml` | `ErrorCode=35`, `WasUpdated=false` | `refillAccepted:false`, REJECTED + errorReason |

**Rule of thumb (from pms-service `RefillRxV2Mapper`):** `refillAccepted = (mapped status == OK)`;
any non-OK status → `false`.

**Traps when hand-crafting these:**
- **PDX:** the refill response root is `<rxStatusResponse>`, NOT `<refillRxResponse>` (that element
  isn't in the XSD → 503). `msgStatusCode=900` alone is enough to reject.
- **Liberty:** the failure `Status` must be a real enum value — use `Invalid_Script_Number`. Arbitrary
  strings (e.g. "Rejected") fail deserialization → HTTP 500, not a clean rejection.
- **McKesson:** `MsgName` must be one the adapter recognizes (`GenericSuccessRsp`, `GenericFailureRsp`,
  `SOAPFault`, `RxInfoRsp`). Any other name throws → 500. Use `GenericFailureRsp`.
- **Epic:** `ErrorCode` maps by value (0=OK, 31=DISCONTINUED, 32/39/44=NOT_REFILLABLE, 35=REJECTED,
  36/101=NOT_FOUND). Use 35 for a clean rejection.
- After updating a Liberty/Epic refill file by hand, `POST /__admin/mappings/reset` (see §3).

---

## 6. End-to-end smoke test (PDX example)

```bash
TOKEN=...   # OMCL super-admin bearer
SIM="https://pmssim.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp"
PMS="https://pms-services.pc.q.awscloud.private/cxf/api/pms/v2/clients/9001/rxs"

# 1. Seed a refillable rx (use the Python helper, or write the 3 PDX files by hand)
# 2. Rx Info should succeed:
curl -sk "$PMS/{RX}?requestSource=IVR&requestType=INFO&storeId=70050001&storeTzOffset=-04:00" \
  -H "Authorization: Bearer $TOKEN"
# 3. Refill submit:
curl -sk -X POST "$PMS" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"requestStoreNum":"70050001","requestSource":"IVR","storeTzOffset":"-04:00","deliveryMethod":"PICKUP","rxs":[{"rxNum":"{RX}","rxIdxInOrder":1,"lastFillStoreNum":"70050001","authorizeAdditionalRefills":true,"allowGenericSubstitution":true}]}'
# → refillAccepted:true for a normal rx; false for a REFILL_REJECTED one.
```

---

## 7. Gotchas index (quick)

- Sim data is **ephemeral** — lost on pod restart. Commit to the `pms-simulator` repo for persistent
  data; the tool is for on-demand test setup.
- **P360 ↔ PMS field mismatch = silent personalization failure.** Build the matched pair together.
- **`pms.connection.error` (503)** on Rx Info/refill = the sim response failed XSD validation. Check
  the sim log.
- **WireMock refill files are cached** — reset mappings after updating them.
- **Liberty refill submit** needs `pickupDate` + `pickupTime` in the request body.
- **McKesson = PerSe** in the sim (directory `PerSe/`, no `McKesson/` dir exists).
- Debugging pms-services behavior? Its request/response bodies are logged (Datadog
  `service:pms-services`, QA). Filter on the rx number + a unique field name to find the right line.

---

## 8. Source of truth

- Library + UI: this repo (`tests/helpers_pms_sim.py`, `pmsi_data_builder_ui.py`).
- Adapter mapping logic: `pms-service` repo (`.../service/adapters/{PDXEPS,McKesson,Liberty,Epic2018}.java`,
  `mappers/RefillRxV2Mapper.java`, `resources/pmsConfigs/pdxEPS.json`).
- Sim + XSDs: `pms-simulator` repo (`.../FsiXmlSimulator/schema/...`).
