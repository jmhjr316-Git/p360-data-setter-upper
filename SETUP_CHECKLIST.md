# Quick Setup Checklist

## GitHub Setup (for .exe and .dmg builds)

### 1. Create GitHub Repository
- [ ] Go to https://github.com/new
- [ ] Name: `pmsi-data-manager` (or your choice)
- [ ] Make it Private (recommended for corporate tools)
- [ ] Don't initialize with README (we already have files)

### 2. Push Code to GitHub
```bash
cd c:\Code\Data_setter_upper

# Add GitHub remote
git remote add github https://github.com/YOUR_USERNAME/pmsi-data-manager.git

# Push main branch
git checkout main
git push github main

# Push feature branch
git checkout feature/multi-rx-support
git push github feature/multi-rx-support
```

### 3. Trigger First Build
**Option A - Manual:**
1. Go to your repo on GitHub
2. Click "Actions" tab
3. Click "Build Executables"
4. Click "Run workflow" button
5. Select `feature/multi-rx-support` branch
6. Click green "Run workflow" button
7. Wait ~5-10 minutes for build
8. Download artifacts (Windows .exe and macOS .dmg)

**Option B - Tag Release:**
```bash
git tag v1.0.0
git push github v1.0.0
```
Then go to "Releases" tab on GitHub to download files.

---

## GitLab Setup (for corporate deployment)

### 1. Create GitLab Project
- [ ] Go to your corporate GitLab
- [ ] Create new project: `pmsi-data-manager`

### 2. Push Code to GitLab
```bash
# Add GitLab remote
git remote add gitlab https://gitlab.yourcompany.com/YOUR_USERNAME/pmsi-data-manager.git

# Push branches
git push gitlab main
git push gitlab feature/multi-rx-support
```

### 3. Configure Runners
Contact your GitLab admin to ensure:
- [ ] Windows runner with tag `windows` is available
- [ ] macOS runner with tag `macos` is available
- [ ] Runners have Python 3.11+ installed

### 4. Trigger Build
Push to branch or create tag:
```bash
git tag v1.0.0
git push gitlab v1.0.0
```

---

## What Gets Built

### Windows Build
- **File**: `PMSI_Data_Manager.exe`
- **Size**: ~50-100MB
- **Includes**: Python runtime, all dependencies, templates, config
- **Runs on**: Windows 10/11 (no Python needed)

### macOS Build
- **File**: `PMSI_Data_Manager.dmg`
- **Size**: ~50-100MB
- **Includes**: Python runtime, all dependencies, templates, config
- **Runs on**: macOS 10.15+ (no Python needed)

---

## Testing the Build

### Windows
1. Download `PMSI_Data_Manager.exe`
2. Double-click to run
3. Test all features:
   - [ ] Add patient info
   - [ ] Add multiple prescriptions
   - [ ] Upload to PMSI simulator
   - [ ] Enable personalization
   - [ ] Environment switching

### macOS
1. Download `PMSI_Data_Manager.dmg`
2. Open DMG and drag to Applications
3. Right-click app → Open (first time)
4. Test all features (same as Windows)

---

## Distribution to Team

### Internal Distribution
1. Download built files from GitHub/GitLab
2. Upload to shared drive or internal portal
3. Send email with download link and instructions

### Instructions for Users
**Windows:**
- Download the .exe file
- Save to Desktop or Documents
- Double-click to run
- No installation needed

**Mac:**
- Download the .dmg file
- Open the DMG
- Drag app to Applications folder
- First time: Right-click → Open

---

## Updating the App

### Make Changes
```bash
# Make your code changes
git add .
git commit -m "Description of changes"
git push github feature/multi-rx-support
```

### Create New Release
```bash
# Bump version
git tag v1.1.0
git push github v1.1.0
```

Builds automatically trigger and create new release!

---

## Notes
- GitHub Actions is FREE for public repos
- GitHub Actions has limited free minutes for private repos (2000 min/month)
- GitLab CI/CD depends on your corporate plan
- First build takes ~10 minutes (subsequent builds are faster)
- Both platforms cache dependencies to speed up builds
