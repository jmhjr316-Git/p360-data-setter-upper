#!/usr/bin/env python3
"""
Enhanced launcher that handles all dependencies automatically
"""
import subprocess
import sys
import os
import importlib.util

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 6):
        print("Error: Python 3.6 or higher is required")
        input("Press Enter to exit...")
        sys.exit(1)

def install_package(package):
    """Install a package using pip"""
    print(f"Installing {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", package])
        return True
    except subprocess.CalledProcessError:
        print(f"Failed to install {package}")
        return False

def check_and_install_dependencies():
    """Check and install required dependencies"""
    required_packages = {
        'requests': 'requests>=2.25.0',
        'tkcalendar': 'tkcalendar>=1.6.0', 
        'pymongo': 'pymongo>=4.0.0'
    }
    
    missing_packages = []
    
    for package, pip_name in required_packages.items():
        try:
            importlib.import_module(package)
            print(f"✓ {package} is available")
        except ImportError:
            print(f"✗ {package} is missing")
            missing_packages.append(pip_name)
    
    if missing_packages:
        print(f"\nInstalling missing packages: {', '.join(missing_packages)}")
        for package in missing_packages:
            if not install_package(package):
                print(f"Failed to install {package}. Please install manually:")
                print(f"  pip install {package}")
                input("Press Enter to continue anyway...")
    
    print("\nAll dependencies checked!")

def main():
    """Main launcher function"""
    print("PMSI Simulator Data Manager - Setup & Launch")
    print("=" * 50)
    
    # Check Python version
    check_python_version()
    
    # Check and install dependencies
    check_and_install_dependencies()
    
    # Launch the main application
    print("\nLaunching PMSI Data Manager...")
    try:
        import pmsi_data_ui
        pmsi_data_ui.main()
    except Exception as e:
        print(f"Error launching application: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()