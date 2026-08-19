# Deployment Guide

## Building Executables with GitHub Actions

### Setup
1. Create a GitHub repository (public or private)
2. Push your code to GitHub:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/pmsi-data-manager.git
   git push -u origin main
   git push origin feature/multi-rx-support
   ```

### Trigger a Build

#### Option 1: Manual Trigger (Recommended for Testing)
1. Go to your GitHub repository
2. Click "Actions" tab
3. Select "Build Executables" workflow
4. Click "Run workflow" button
5. Select branch (e.g., `feature/multi-rx-support`)
6. Click green "Run workflow" button
7. Wait ~5-10 minutes for build to complete
8. Download artifacts from the workflow run

#### Option 2: Tag-based Release (Recommended for Distribution)
```bash
# Create and push a tag
git tag v1.0.0
git push origin v1.0.0
```
This will:
- Build Windows .exe
- Build macOS .dmg
- Create a GitHub Release with both files attached
- Files are permanently available in Releases section

### Download Built Files

**From Workflow Run (Manual trigger):**
1. Go to "Actions" tab
2. Click on the workflow run
3. Scroll to "Artifacts" section
4. Download `PMSI_Data_Manager_Windows` and `PMSI_Data_Manager_macOS`

**From Release (Tag trigger):**
1. Go to "Releases" tab
2. Click on the release version
3. Download files from "Assets" section

---

## Local Build (Manual)

### Windows
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PMSI_Data_Manager" --add-data "templates;templates" --add-data "environment_config.json;." pmsi_data_ui_modern.py
```
Output: `dist/PMSI_Data_Manager.exe`

### macOS
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PMSI_Data_Manager" --add-data "templates:templates" --add-data "environment_config.json:." pmsi_data_ui_modern.py

# Create DMG
mkdir -p dist/dmg
cp -r dist/PMSI_Data_Manager.app dist/dmg/
hdiutil create -volname "PMSI Data Manager" -srcfolder dist/dmg -ov -format UDZO dist/PMSI_Data_Manager.dmg
```
Output: `dist/PMSI_Data_Manager.dmg`

---

## Distribution

### For End Users

**Windows Users:**
1. Download `PMSI_Data_Manager.exe`
2. Double-click to run
3. No Python installation required

**Mac Users:**
1. Download `PMSI_Data_Manager.dmg`
2. Open the DMG file
3. Drag app to Applications folder
4. Right-click → Open (first time only, to bypass Gatekeeper)

### Important Notes
- Templates folder and environment_config.json are bundled inside the executable
- Generated files (JSON, XML) are saved in the same directory as the executable
- First run may be slow (PyInstaller unpacking)

---

## Troubleshooting

### GitHub Actions Issues
- **No runners available**: GitHub provides free runners for public repos
- **Build fails**: Check Python version (3.11 recommended)
- **Missing dependencies**: Ensure requirements.txt is up to date

### Corporate GitLab
- GitLab doesn't provide free macOS runners
- Use GitHub for building, then upload artifacts to GitLab releases manually
- Or use GitHub as the distribution point

### Build Issues
- **Import errors**: Add missing packages to requirements.txt
- **File not found**: Check --add-data paths (use `;` for Windows, `:` for Mac/Linux)
- **Large file size**: Normal for PyInstaller (50-100MB)

---

## Version Management

### Semantic Versioning
Use tags like: `v1.0.0`, `v1.1.0`, `v2.0.0`

```bash
# Create a new version
git tag v1.0.0 -m "Initial release"
git push origin v1.0.0
git push gitlab v1.0.0
```

### Changelog
Update CHANGELOG.md before creating a release tag.
