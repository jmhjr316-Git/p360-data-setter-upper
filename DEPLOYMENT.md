# Deployment Guide

## Building Executables with GitHub Actions

### Setup
1. Create a GitHub repository
2. Push your code to GitHub:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/pmsi-data-manager.git
   git push -u origin main
   git push origin feature/multi-rx-support
   ```

### Trigger a Build

#### Option 1: Manual Trigger
1. Go to your GitHub repository
2. Click "Actions" tab
3. Select "Build Executables" workflow
4. Click "Run workflow"
5. Select branch and click "Run workflow"
6. Wait for build to complete
7. Download artifacts from the workflow run

#### Option 2: Tag-based Release
```bash
# Create and push a tag
git tag v1.0.0
git push origin v1.0.0
```
This will:
- Build Windows .exe
- Build macOS .dmg
- Create a GitHub Release with both files attached

### Download Built Files
- Go to "Actions" tab → Select workflow run → Download artifacts
- OR go to "Releases" tab (for tagged releases)

---

## Building Executables with GitLab CI/CD

### Setup
1. Push code to your corporate GitLab:
   ```bash
   git remote add gitlab https://gitlab.yourcompany.com/YOUR_USERNAME/pmsi-data-manager.git
   git push gitlab main
   git push gitlab feature/multi-rx-support
   ```

2. Ensure GitLab runners are available with tags:
   - `windows` - Windows runner
   - `macos` - macOS runner

### Trigger a Build

#### Option 1: Push to Branch
Builds automatically trigger on push to:
- `main`
- `feature/multi-rx-support`
- Any tag

#### Option 2: Create a Release Tag
```bash
git tag v1.0.0
git push gitlab v1.0.0
```

### Download Built Files
1. Go to CI/CD → Pipelines
2. Click on the pipeline
3. Click on job (build-windows or build-macos)
4. Click "Download" button for artifacts

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

### GitLab CI/CD Issues
- **No runners with required tags**: Contact GitLab admin to set up Windows/macOS runners
- **Permission denied**: Ensure runners have proper permissions
- **Build fails**: Check runner has Python installed

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
