# PMSI Simulator Data Tools

Two tools for managing PMS simulator test data for the ACE QA team.

## Tools

### 1. PMSI Data Builder (NEW — recommended)

**Status-driven** tool: pick a desired Rx status outcome and it generates all the correct XML automatically.

- **Executable:** Download from [Confluence](https://enlivenhealth.atlassian.net/wiki/spaces/QE/pages/2824634369) or GitHub Actions artifacts
- **From source:** `python launch_builder.py`
- **Entry point:** `pmsi_data_builder_ui.py`
- **Backend library:** `tests/helpers_pms_sim.py`

### 2. PMSI Data Manager (Legacy)

Template-based tool with token replacement. Still works, but requires more manual knowledge of XML fields.

- **Entry point:** `pmsi_data_ui_modern.py`
- **Templates:** `templates/` directory

## Running from Source

```bash
cd C:\Code\Data_setter_upper
python launch_builder.py          # New builder (auto-installs deps)
# or
python pmsi_data_ui_modern.py     # Legacy UI
```

**Requirements:** Python 3.10+, VPN connected to QA environment.

## Architecture

```
p360-and-sim-data-setup/           ← This repo (UI + bundled library)
├── pmsi_data_builder_ui.py        ← New status-driven UI
├── launch_builder.py              ← Launcher (installs deps)
├── run_data_builder.bat           ← Windows double-click launcher
├── tests/
│   ├── helpers_pms_sim.py         ← Data builder library (BUNDLED COPY)
│   └── helpers_p360.py            ← P360 DocumentDB helper (BUNDLED COPY)
├── pmsi_data_ui_modern.py         ← Legacy template-based UI
├── templates/                     ← XML templates for legacy UI
├── .github/workflows/build.yml    ← GitHub Actions → builds .exe/.dmg
└── requirements.txt

ace-functional-tests/              ← Separate repo (SOURCE OF TRUTH for library)
└── tests/
    ├── helpers_pms_sim.py         ← Source of truth — automation tests use this
    └── helpers_p360.py
```

**Key point:** `tests/helpers_pms_sim.py` exists in BOTH repos:
- **ace-functional-tests** = source of truth (automation tests import from here)
- **This repo** = bundled copy (so PyInstaller can build the exe without cross-repo access)

If you update the library, update it in ace-functional-tests first, then copy to this repo.

## Building Executables

Executables are built automatically by GitHub Actions on push to `master`.

**GitHub repo:** https://github.com/jmhjr316-Git/p360-data-setter-upper

**What triggers a build:**
- Push to `master`
- Push a tag like `v5.0.0`
- Manual trigger (Actions → "Run workflow")

**What it produces:**
- `PMSI_Data_Builder.exe` (Windows) — the new tool
- `PMSI_Data_Manager.exe` (Windows) — the legacy tool
- `PMSI_Tools.dmg` (macOS) — both tools

**To download:** Go to Actions tab → latest successful run → download artifacts.

**To create a release with download links:** Tag a commit:
```bash
git tag v5.0.0
git push origin v5.0.0
```
This creates a GitHub Release with the executables attached.

## Making Changes

### Changing the UI only (layout, fields, behavior)

Edit `pmsi_data_builder_ui.py` in this repo. Push to master → new exe builds automatically.

### Changing the data generation logic (XML, statuses, XSD rules)

1. Edit `tests/helpers_pms_sim.py` in **ace-functional-tests** (the source of truth)
2. Test: `cd ace-tests && python -m pytest tests/ -m smoke`
3. Push to ace-functional-tests `main`
4. Copy the updated file to this repo: `cp ace-tests/tests/helpers_pms_sim.py tests/`
5. Commit and push to this repo → new exe builds

### Adding a new status

1. In `tests/helpers_pms_sim.py`:
   - Add to the `RxStatus` enum
   - Add a `_dates_xxx()` function
   - Add entry to `_STATUS_RECIPES`
2. In `pmsi_data_builder_ui.py`:
   - Add to `STATUS_INFO` dict (description for the dropdown)
   - If it's testable, it auto-appears in the UI dropdown (reads from `AVAILABLE_STATUSES`)

### Updating P360 patient document structure

Edit `_build_p360_patient()` in `tests/helpers_pms_sim.py`. The fields must match what the personalization engine expects (search fields, orgs, mdfcode, patientStatus).

## Git Remotes

This repo has two remotes:

| Remote | URL | Purpose |
|--------|-----|---------|
| `origin` | git@github.com:jmhjr316-Git/p360-data-setter-upper.git | Builds executables (GitHub Actions) |
| `gitlab` | git@gitlab.com:enlivenhealth/.../load/p360-and-sim-data-setup.git | Team source of truth |

Push to both: `git push origin master && git push gitlab master`

## Related Resources

- **Confluence:** https://enlivenhealth.atlassian.net/wiki/spaces/QE/pages/2824634369
- **XSD rules doc:** ace-functional-tests/docs/pms-simulator-quick-reference.md
- **RxStatusUtils.java:** Bot/pms-rx-utils (the status resolution logic the builder mirrors)
- **pdxEPS.json:** Bot/pms-service/src/main/resources/pmsConfigs/ (adapter field mappings)
