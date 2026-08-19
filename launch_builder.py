#!/usr/bin/env python3
"""Launch the PMSI Data Builder UI.

Checks for required dependencies and installs them if missing,
then launches the GUI.

RUN FROM WINDOWS (PowerShell or cmd), not WSL:
    cd C:\Code\Data_setter_upper
    python launch_builder.py
"""

import subprocess
import sys


REQUIRED_PACKAGES = {
    "httpx": "httpx",
    "ttkbootstrap": "ttkbootstrap",
    "pymongo": "pymongo",
}


def check_and_install():
    """Check for required packages and install if missing."""
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--user", *missing],
            )
        except subprocess.CalledProcessError:
            # Try without --user (some environments don't support it)
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *missing],
            )
        print("Done.")


def main():
    check_and_install()

    from pmsi_data_builder_ui import main as ui_main
    ui_main()


if __name__ == "__main__":
    main()
