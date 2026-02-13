#!/usr/bin/env python3
"""
PMSI Data UI Launcher
Simple launcher script for the PMSI Simulator Data Management UI
"""

import sys
import subprocess
import os

def check_requirements():
    """Check if required packages are installed"""
    try:
        import requests
        return True
    except ImportError:
        return False

def install_requirements():
    """Install required packages"""
    print("Installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        return True
    except subprocess.CalledProcessError:
        print("Failed to install requirements. Please install manually:")
        print("pip install requests")
        return False

def main():
    print("PMSI Simulator Data Management UI")
    print("=" * 40)
    
    # Check if requirements are met
    if not check_requirements():
        print("Missing required packages.")
        if input("Install automatically? (y/n): ").lower().startswith('y'):
            if not install_requirements():
                return
        else:
            print("Please install requirements manually and try again.")
            return
    
    # Launch the UI
    print("Starting PMSI Data UI...")
    try:
        from pmsi_data_ui import main as ui_main
        ui_main()
    except ImportError:
        print("Error: pmsi_data_ui.py not found in current directory")
    except Exception as e:
        print(f"Error starting UI: {e}")

if __name__ == "__main__":
    main()