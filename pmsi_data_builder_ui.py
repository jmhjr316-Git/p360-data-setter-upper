#!/usr/bin/env python3
"""
PMSI Simulator Data Builder — Tkinter GUI

A modern wizard-style UI that wraps the helpers_pms_sim automation library.
Generates XSD-valid PDX EPS prescription data and uploads to the PMS simulator,
with optional P360 patient document creation.

KEY DESIGN DECISIONS:
- Uses helpers_pms_sim.build_scenario() as the backend (same code as automation)
- Status dropdown uses the RxStatus enum (READY_FOR_PICKUP, REFILLABLE, etc.)
- All XSD rules enforced by the library, not the UI
- Supports multi-Rx scenarios (one patient, many prescriptions)
- Supports QA and Staging environments

REQUIRES:
    pip install ttkbootstrap requests pymongo httpx

USAGE:
    python pmsi_data_builder_ui.py
    # or
    python -m pmsi_data_builder_ui
"""

import json
import logging
import os
import random
import sys
import tkinter as tk
from datetime import datetime, date, timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Any

import urllib3

# Disable SSL warnings for internal APIs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    HAS_BOOTSTRAP = True
except ImportError:
    import tkinter.ttk as ttk
    from tkinter import BOTH, YES, LEFT, RIGHT, X, Y, CENTER, DISABLED, NORMAL, END, TOP, BOTTOM, W, E, N, S
    HAS_BOOTSTRAP = False
    print("ttkbootstrap not available — using standard ttk (install: pip install ttkbootstrap)")

# ──────────────────────────────────────────────────────────────────────────────
# Import the automation library
# Add ace-tests to path so we can import helpers_pms_sim
# ──────────────────────────────────────────────────────────────────────────────

# When running from Data_setter_upper, the library lives in ace-tests.
# Support both Windows native and WSL paths.
# Also check local tests/ directory (for PyInstaller bundled exe).
_ACE_TESTS_CANDIDATES = [
    Path(__file__).parent,                                   # Local (bundled or same dir)
    Path("C:/Source/AI_IVR/New_AI_IVR/ace-tests"),          # Windows native
    Path("/mnt/c/Source/AI_IVR/New_AI_IVR/ace-tests"),      # WSL
    Path(__file__).parent.parent / "AI_IVR" / "New_AI_IVR" / "ace-tests",  # Relative fallback
]

_ACE_TESTS_PATH = None
for candidate in _ACE_TESTS_CANDIDATES:
    if (candidate / "tests" / "helpers_pms_sim.py").exists():
        _ACE_TESTS_PATH = candidate
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break

if _ACE_TESTS_PATH is None:
    # Last resort: try the Windows path even if Path.exists() fails (cross-OS)
    sys.path.insert(0, "C:/Source/AI_IVR/New_AI_IVR/ace-tests")

try:
    from tests.helpers_pms_sim import (
        RxStatus,
        SimScenario,
        build_scenario,
        upload_rx,
        delete_rx,
        _build_rx_response_xml,
        _build_status_response_xml,
        _build_refill_response_xml,
        RX_STATUS_DESCRIPTIONS,
        DEFAULT_STORE_NUMBER,
        DEFAULT_CLIENT_ID,
        DEFAULT_STORE_ID,
        DEFAULT_STORE_NPI,
        CLIENT_STORE_CONFIG,
        SIM_BASE_URL,
    )
    HAS_BUILDER = True
except ImportError as e:
    HAS_BUILDER = False
    _IMPORT_ERROR = str(e)
    print(f"WARNING: Could not import helpers_pms_sim: {e}")
    print(f"Ensure {_ACE_TESTS_PATH / 'tests' / 'helpers_pms_sim.py'} exists and httpx is installed")

try:
    from tests.helpers_p360 import ensure_patient, delete_patient, close as close_p360
    HAS_P360 = True
except ImportError:
    HAS_P360 = False

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

ENVIRONMENTS = {
    "QA": {
        "name": "QA Environment",
        "sim_base_url": "https://ivr-mock-svcs.pc.q.awscloud.private/FsiXmlSimulator/manage.jsp",
        "description": "QA (ivr-mock-svcs.pc.q)",
    },
    "Staging": {
        "name": "Staging Environment",
        "sim_base_url": "https://ivr-mock-svcs.pc.s.awscloud.private/FsiXmlSimulator/manage.jsp",
        "description": "Staging (ivr-mock-svcs.pc.s)",
    },
}

# Status descriptions for the UI
STATUS_INFO = {
    RxStatus.READY_FOR_PICKUP: "Filled, waiting for patient pickup (StatusResponse 206)",
    RxStatus.IN_QUEUE: "Being filled by pharmacy (StatusResponse 204)",
    RxStatus.WAITING_FOR_PRESCRIBER: "Needs prescriber authorization (StatusResponse 200)",
    RxStatus.REFILLABLE: "Available for refill — picked up > 5 days ago (StatusResponse 207)",
    RxStatus.RX_PICKED_UP: "Recently picked up — within 5 days (StatusResponse 207)",
    RxStatus.SHIPPED: "Mailed to patient (StatusResponse 208)",
    RxStatus.NOT_REFILLABLE: "Rejected — cannot be refilled (RxResponse 900 + reject code)",
    RxStatus.CONTROLLED_SUBSTANCE: "Schedule II controlled substance (drug schedule=2)",
    RxStatus.TOO_SOON: "Too early to refill (requires channel config minPercentageDaysSupply > 0)",
} if HAS_BUILDER else {}

# Statuses available in the dropdown (excludes non-testable ones)
AVAILABLE_STATUSES = [s for s in RxStatus if s not in (RxStatus.RX_CROSS_STORE, RxStatus.RX_DELIVERED)] if HAS_BUILDER else []

SAVED_SCENARIOS_FILE = BASE_DIR / "saved_scenarios_builder.json"
SAVED_STORES_FILE = BASE_DIR / "saved_stores.json"


# ──────────────────────────────────────────────────────────────────────────────
# Main UI Class
# ──────────────────────────────────────────────────────────────────────────────


class PMSIDataBuilderUI:
    """Wizard-style UI for the PMSI Simulator Data Builder."""

    def __init__(self, root):
        self.root = root
        self.root.title("PMSI Data Builder")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        # State
        self.current_step = 0
        self.patient_data: dict[str, str] = {}
        self.prescriptions: list[dict[str, Any]] = []
        self.scenarios: list[SimScenario] = []
        self.current_environment = "QA"
        self.enable_p360 = tk.BooleanVar(value=True)

        # Load saved data
        self.saved_stores = self._load_json(SAVED_STORES_FILE, [])
        self.saved_scenarios = self._load_json(SAVED_SCENARIOS_FILE, [])

        # Build UI
        self._setup_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # UI Setup
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        """Build the main UI frame."""
        # Check for missing library
        if not HAS_BUILDER:
            self._show_import_error()
            return

        main = ttk.Frame(self.root, padding=20)
        main.pack(fill=BOTH, expand=YES)

        # Header
        self._create_header(main)

        # Progress bar
        self._create_progress(main)

        # Content area
        self.content_frame = ttk.Frame(main)
        self.content_frame.pack(fill=BOTH, expand=YES, pady=10)

        # Navigation
        self._create_nav(main)

        # Show step 1
        self._show_step(0)

    def _show_import_error(self):
        """Show error if the builder library can't be imported."""
        frame = ttk.Frame(self.root, padding=40)
        frame.pack(fill=BOTH, expand=YES)

        ttk.Label(frame, text="⚠️  Builder Library Not Available", font=("Segoe UI", 18, "bold")).pack(pady=(0, 20))
        ttk.Label(
            frame,
            text=(
                f"Could not import helpers_pms_sim:\n\n{_IMPORT_ERROR}\n\n"
                f"Expected location:\n"
                f"  Windows: C:\\Source\\AI_IVR\\New_AI_IVR\\ace-tests\\tests\\helpers_pms_sim.py\n"
                f"  WSL:     /mnt/c/Source/AI_IVR/New_AI_IVR/ace-tests/tests/helpers_pms_sim.py\n\n"
                "Make sure:\n"
                "  1. The file exists at one of the paths above\n"
                "  2. httpx is installed: pip install httpx\n"
                "  3. You're running from the Data_setter_upper directory\n\n"
                "Run from Windows PowerShell:\n"
                "  cd C:\\Code\\Data_setter_upper\n"
                "  python launch_builder.py"
            ),
            font=("Consolas", 10),
            justify=LEFT,
            wraplength=700,
        ).pack()

    def _create_header(self, parent):
        """Header with title and environment selector."""
        header = ttk.Frame(parent)
        header.pack(fill=X, pady=(0, 15))

        ttk.Label(header, text="PMSI Data Builder", font=("Segoe UI", 22, "bold")).pack(side=LEFT)

        # Environment selector (right side)
        env_frame = ttk.Frame(header)
        env_frame.pack(side=RIGHT)

        ttk.Label(env_frame, text="Environment:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 8))
        self.env_combo = ttk.Combobox(env_frame, values=list(ENVIRONMENTS.keys()), state="readonly", width=12)
        self.env_combo.set(self.current_environment)
        self.env_combo.bind("<<ComboboxSelected>>", self._on_env_change)
        self.env_combo.pack(side=LEFT)

    def _create_progress(self, parent):
        """Wizard step progress indicator."""
        prog_frame = ttk.Frame(parent)
        prog_frame.pack(fill=X, pady=(0, 10))

        self.steps = ["Patient & Store", "Prescriptions", "Review & Submit"]
        self.step_labels = []

        for i, name in enumerate(self.steps):
            sf = ttk.Frame(prog_frame)
            sf.pack(side=LEFT, expand=YES, fill=X)

            num_lbl = ttk.Label(sf, text=str(i + 1), font=("Segoe UI", 12, "bold"), width=3, anchor=CENTER)
            num_lbl.pack()
            name_lbl = ttk.Label(sf, text=name, font=("Segoe UI", 9))
            name_lbl.pack()
            self.step_labels.append((num_lbl, name_lbl))

    def _create_nav(self, parent):
        """Back/Next navigation buttons."""
        nav = ttk.Frame(parent)
        nav.pack(fill=X, pady=(10, 0))

        self.btn_back = ttk.Button(nav, text="← Back", command=self._go_back, width=14)
        self.btn_back.pack(side=LEFT)

        self.btn_next = ttk.Button(nav, text="Next →", command=self._go_next, width=14)
        self.btn_next.pack(side=RIGHT)

    # ──────────────────────────────────────────────────────────────────────────
    # Step Navigation
    # ──────────────────────────────────────────────────────────────────────────

    def _show_step(self, step: int):
        self.current_step = step

        # Clear content
        for w in self.content_frame.winfo_children():
            w.destroy()

        # Update progress colors
        for i, (num_lbl, name_lbl) in enumerate(self.step_labels):
            if i < step:
                num_lbl.configure(foreground="#28a745")
                name_lbl.configure(font=("Segoe UI", 9))
            elif i == step:
                num_lbl.configure(foreground="#007bff")
                name_lbl.configure(font=("Segoe UI", 9, "bold"))
            else:
                num_lbl.configure(foreground="gray")
                name_lbl.configure(font=("Segoe UI", 9))

        # Show step content
        if step == 0:
            self._step_patient()
        elif step == 1:
            self._step_prescriptions()
        elif step == 2:
            self._step_review()

        # Update nav buttons
        self.btn_back.configure(state=DISABLED if step == 0 else NORMAL)
        self.btn_next.configure(text="🚀 Submit" if step == 2 else "Next →")

    def _go_back(self):
        if self.current_step > 0:
            self._show_step(self.current_step - 1)

    def _go_next(self):
        if self.current_step == 2:
            self._submit()
        elif self._validate_step():
            self._show_step(self.current_step + 1)

    def _validate_step(self) -> bool:
        if self.current_step == 0:
            return self._validate_patient()
        elif self.current_step == 1:
            if not self.prescriptions:
                messagebox.showerror("Validation", "Add at least one prescription.")
                return False
            return True
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1: Patient & Store
    # ──────────────────────────────────────────────────────────────────────────

    def _step_patient(self):
        """Patient information + store config."""
        # Quick load
        if self.saved_scenarios:
            load_frame = ttk.Frame(self.content_frame)
            load_frame.pack(fill=X, pady=(0, 10))
            ttk.Label(load_frame, text="Quick Load:", font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=(0, 8))
            names = [s["name"] for s in self.saved_scenarios]
            self._scenario_combo = ttk.Combobox(load_frame, values=names, state="readonly", width=30)
            self._scenario_combo.pack(side=LEFT, padx=(0, 8))
            ttk.Button(load_frame, text="Load", command=self._quick_load).pack(side=LEFT, padx=(0, 5))
            ttk.Button(load_frame, text="Load & Submit", command=self._quick_load_submit).pack(side=LEFT)

        # Patient fields
        card = ttk.LabelFrame(self.content_frame, text="Patient Information", padding=10)
        card.pack(fill=X, pady=(0, 10))

        self._patient_fields = {}
        fields = [
            ("first_name", "First Name *", "TESTPATIENT"),
            ("last_name", "Last Name *", "STATUS"),
            ("dob", "Date of Birth (YYYYMMDD) *", "19850101"),
            ("phone", "Phone Number *", "5550561001"),
        ]
        for key, label, default in fields:
            row = ttk.Frame(card)
            row.pack(fill=X, pady=3)
            ttk.Label(row, text=label, width=28, anchor=W).pack(side=LEFT)
            entry = ttk.Entry(row, width=30)
            entry.pack(side=LEFT, fill=X, expand=YES)
            # Pre-fill from saved data or default
            val = self.patient_data.get(key, default)
            entry.insert(0, val)
            self._patient_fields[key] = entry

        # Store config
        store_card = ttk.LabelFrame(self.content_frame, text="Store Configuration", padding=10)
        store_card.pack(fill=X, pady=(0, 10))

        # Saved stores dropdown
        if self.saved_stores:
            ss_frame = ttk.Frame(store_card)
            ss_frame.pack(fill=X, pady=(0, 8))
            ttk.Label(ss_frame, text="Saved Stores:", width=28, anchor=W).pack(side=LEFT)
            labels = [f"{s.get('client_id')} / {s.get('store_number', s.get('pmsi_store_id', ''))}" for s in self.saved_stores]
            self._store_combo = ttk.Combobox(ss_frame, values=labels, state="readonly", width=28)
            self._store_combo.pack(side=LEFT, fill=X, expand=YES)
            self._store_combo.bind("<<ComboboxSelected>>", self._on_store_selected)

        self._store_fields = {}
        store_defs = [
            ("client_id", "Client ID *", str(DEFAULT_CLIENT_ID)),
            ("store_number", "PMSI Store Number * (XML)", DEFAULT_STORE_NUMBER),
            ("store_id", "OPE Store ID (P360)", str(DEFAULT_STORE_ID)),
            ("store_npi", "Store NPI (P360)", DEFAULT_STORE_NPI),
        ]
        for key, label, default in store_defs:
            row = ttk.Frame(store_card)
            row.pack(fill=X, pady=3)
            ttk.Label(row, text=label, width=28, anchor=W).pack(side=LEFT)
            entry = ttk.Entry(row, width=30)
            entry.pack(side=LEFT, fill=X, expand=YES)
            val = self.patient_data.get(key, default)
            entry.insert(0, val)
            self._store_fields[key] = entry

        # Hint label
        ttk.Label(store_card, text="Store Number = pmsStoreNumber for XML sim.  Store ID = OPE org context (urn:OPE-STORE:{id}).  NPI = pharmacy NPI.",
                  font=("Segoe UI", 8, "italic"), foreground="gray", wraplength=600).pack(anchor=W, padx=10, pady=(2, 5))

    def _validate_patient(self) -> bool:
        """Validate and save patient/store data."""
        self.patient_data = {}
        for key, entry in self._patient_fields.items():
            val = entry.get().strip()
            if not val:
                messagebox.showerror("Validation", f"Please fill in: {key.replace('_', ' ').title()}")
                return False
            self.patient_data[key] = val

        for key, entry in self._store_fields.items():
            val = entry.get().strip()
            if not val:
                messagebox.showerror("Validation", f"Please fill in: {key.replace('_', ' ').title()}")
                return False
            self.patient_data[key] = val

        return True

    def _on_store_selected(self, event=None):
        idx = self._store_combo.current()
        if idx >= 0:
            store = self.saved_stores[idx]
            self._store_fields["client_id"].delete(0, END)
            self._store_fields["client_id"].insert(0, store.get("client_id", str(DEFAULT_CLIENT_ID)))
            self._store_fields["store_number"].delete(0, END)
            self._store_fields["store_number"].insert(0, store.get("store_number", store.get("pmsi_store_id", DEFAULT_STORE_NUMBER)))

    # ──────────────────────────────────────────────────────────────────────────
    # Step 2: Prescriptions
    # ──────────────────────────────────────────────────────────────────────────

    def _step_prescriptions(self):
        """Add/manage prescriptions."""
        header = ttk.Frame(self.content_frame)
        header.pack(fill=X, pady=(0, 10))
        ttk.Label(header, text="Prescriptions", font=("Segoe UI", 16, "bold")).pack(side=LEFT)
        ttk.Button(header, text="+ Add Prescription", command=self._add_rx_dialog).pack(side=RIGHT)

        # Scrollable list
        self._rx_list_frame = ttk.Frame(self.content_frame)
        self._rx_list_frame.pack(fill=BOTH, expand=YES)
        self._refresh_rx_list()

    def _refresh_rx_list(self):
        for w in self._rx_list_frame.winfo_children():
            w.destroy()

        if not self.prescriptions:
            ttk.Label(
                self._rx_list_frame,
                text="No prescriptions yet.\nClick '+ Add Prescription' to begin.",
                font=("Segoe UI", 11, "italic"),
                foreground="gray",
                justify=CENTER,
            ).pack(pady=60)
        else:
            for i, rx in enumerate(self.prescriptions):
                self._create_rx_card(i, rx)

    def _create_rx_card(self, idx: int, rx: dict):
        """Display a prescription as a card."""
        card = ttk.LabelFrame(self._rx_list_frame, text=f"RX #{rx['rx_number']}", padding=8)
        card.pack(fill=X, pady=4, padx=5)

        status_name = rx["rx_status"].value if isinstance(rx["rx_status"], RxStatus) else rx["rx_status"]
        info = f"{rx['drug_name']}  |  Status: {status_name}  |  Copay: ${rx.get('copay', 10.0):.2f}"
        ttk.Label(card, text=info, font=("Segoe UI", 10)).pack(side=LEFT)

        btn_frame = ttk.Frame(card)
        btn_frame.pack(side=RIGHT)
        ttk.Button(btn_frame, text="Edit", command=lambda i=idx: self._edit_rx_dialog(i), width=6).pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="Remove", command=lambda i=idx: self._remove_rx(i), width=8).pack(side=LEFT, padx=2)

    def _remove_rx(self, idx: int):
        if messagebox.askyesno("Confirm", "Remove this prescription?"):
            self.prescriptions.pop(idx)
            self._refresh_rx_list()

    def _add_rx_dialog(self, edit_idx: int | None = None):
        """Dialog to add or edit a prescription."""
        editing = edit_idx is not None
        existing = self.prescriptions[edit_idx] if editing else {}

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Prescription" if editing else "Add Prescription")
        dialog.geometry("650x520")
        dialog.transient(self.root)
        dialog.grab_set()

        content = ttk.Frame(dialog, padding=15)
        content.pack(fill=BOTH, expand=YES)

        fields = {}

        # RX Number
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="RX Number:", width=22, anchor=W).pack(side=LEFT)
        rx_num_entry = ttk.Entry(row, width=20)
        rx_num_entry.insert(0, existing.get("rx_number", str(random.randint(5610000, 5619999))))
        rx_num_entry.pack(side=LEFT)
        ttk.Label(row, text="(auto-generated if blank)", foreground="gray", font=("Segoe UI", 8)).pack(side=LEFT, padx=8)
        fields["rx_number"] = rx_num_entry

        # Status dropdown
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Desired Status: *", width=22, anchor=W).pack(side=LEFT)
        status_values = [s.value for s in AVAILABLE_STATUSES]
        status_combo = ttk.Combobox(row, values=status_values, state="readonly", width=28)
        current_status = existing.get("rx_status", RxStatus.REFILLABLE)
        status_combo.set(current_status.value if isinstance(current_status, RxStatus) else current_status)
        status_combo.pack(side=LEFT)
        status_combo.bind("<<ComboboxSelected>>", lambda e: self._update_status_info(status_combo, info_label))
        fields["rx_status"] = status_combo

        # Status info
        info_label = ttk.Label(content, text="", font=("Segoe UI", 9, "italic"), foreground="gray", wraplength=580)
        info_label.pack(fill=X, pady=(0, 8))
        self._update_status_info(status_combo, info_label)

        # Drug name
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Drug Name: *", width=22, anchor=W).pack(side=LEFT)
        drug_entry = ttk.Entry(row, width=30)
        drug_entry.insert(0, existing.get("drug_name", "LISINOPRIL 10MG TAB"))
        drug_entry.pack(side=LEFT)
        ttk.Label(row, text="(max 28 chars)", foreground="gray", font=("Segoe UI", 8)).pack(side=LEFT, padx=8)
        fields["drug_name"] = drug_entry

        # Copay
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Copay ($):", width=22, anchor=W).pack(side=LEFT)
        copay_entry = ttk.Entry(row, width=12)
        copay_entry.insert(0, str(existing.get("copay", "10.00")))
        copay_entry.pack(side=LEFT)
        fields["copay"] = copay_entry

        # Days Supply
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Days Supply:", width=22, anchor=W).pack(side=LEFT)
        days_entry = ttk.Entry(row, width=12)
        days_entry.insert(0, str(existing.get("days_supply", "30")))
        days_entry.pack(side=LEFT)
        fields["days_supply"] = days_entry

        # Refills Remaining
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Refills Remaining:", width=22, anchor=W).pack(side=LEFT)
        refills_entry = ttk.Entry(row, width=12)
        refills_entry.insert(0, str(existing.get("refills_remaining", "3")))
        refills_entry.pack(side=LEFT)
        fields["refills_remaining"] = refills_entry

        # Authorized Refills
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Authorized Refills:", width=22, anchor=W).pack(side=LEFT)
        auth_entry = ttk.Entry(row, width=12)
        auth_entry.insert(0, str(existing.get("authorized_refills", "5")))
        auth_entry.pack(side=LEFT)
        fields["authorized_refills"] = auth_entry

        # Sig Text
        row = ttk.Frame(content)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text="Sig Text:", width=22, anchor=W).pack(side=LEFT)
        sig_entry = ttk.Entry(row, width=40)
        sig_entry.insert(0, existing.get("sig_text", "Take one tablet by mouth every day"))
        sig_entry.pack(side=LEFT, fill=X, expand=YES)
        fields["sig_text"] = sig_entry

        # Buttons
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill=X, pady=(15, 0))

        def save():
            rx_data = {
                "rx_number": fields["rx_number"].get().strip() or str(random.randint(5610000, 5619999)),
                "rx_status": RxStatus(fields["rx_status"].get()),
                "drug_name": fields["drug_name"].get().strip()[:28],
                "copay": float(fields["copay"].get() or "10.0"),
                "days_supply": int(fields["days_supply"].get() or "30"),
                "refills_remaining": int(fields["refills_remaining"].get() or "3"),
                "authorized_refills": int(fields["authorized_refills"].get() or "5"),
                "sig_text": fields["sig_text"].get().strip(),
            }

            if not rx_data["drug_name"]:
                messagebox.showerror("Validation", "Drug name is required.")
                return

            if editing:
                self.prescriptions[edit_idx] = rx_data
            else:
                self.prescriptions.append(rx_data)

            self._refresh_rx_list()
            dialog.destroy()

        ttk.Button(btn_frame, text="Save" if editing else "Add", command=save, width=12).pack(side=RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=12).pack(side=RIGHT)

    def _edit_rx_dialog(self, idx: int):
        self._add_rx_dialog(edit_idx=idx)

    def _update_status_info(self, combo, label):
        """Update the info label when status changes."""
        try:
            status = RxStatus(combo.get())
            label.configure(text=STATUS_INFO.get(status, ""))
        except (ValueError, KeyError):
            label.configure(text="")

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3: Review & Submit
    # ──────────────────────────────────────────────────────────────────────────

    def _step_review(self):
        """Review all data and submit."""
        # Scenario save/load
        scenario_frame = ttk.Frame(self.content_frame)
        scenario_frame.pack(fill=X, pady=(0, 8))
        ttk.Label(scenario_frame, text="Scenario Name:", width=14).pack(side=LEFT)
        self._scenario_name = ttk.Entry(scenario_frame, width=25)
        self._scenario_name.pack(side=LEFT, padx=(0, 8))
        ttk.Button(scenario_frame, text="Save Scenario", command=self._save_scenario, width=14).pack(side=LEFT)

        # Options
        opts_frame = ttk.LabelFrame(self.content_frame, text="Options", padding=8)
        opts_frame.pack(fill=X, pady=(0, 8))

        p360_check = ttk.Checkbutton(opts_frame, text="Create P360 patient document (DocumentDB)", variable=self.enable_p360)
        p360_check.pack(anchor=W)
        if not HAS_P360:
            p360_check.configure(state=DISABLED)
            ttk.Label(opts_frame, text="(pymongo not installed — P360 disabled)", foreground="orange", font=("Segoe UI", 8)).pack(anchor=W)

        # Preview
        preview_frame = ttk.LabelFrame(self.content_frame, text="Preview", padding=5)
        preview_frame.pack(fill=BOTH, expand=YES)

        self._preview_text = scrolledtext.ScrolledText(preview_frame, font=("Consolas", 9), wrap=tk.WORD)
        self._preview_text.pack(fill=BOTH, expand=YES)

        # Generate preview
        self._generate_preview()

    def _generate_preview(self):
        """Build preview content showing what will be uploaded."""
        self._preview_text.configure(state=NORMAL)
        self._preview_text.delete("1.0", END)

        lines = []
        lines.append(f"═══ PATIENT ═══")
        lines.append(f"  Name:  {self.patient_data.get('first_name', '')} {self.patient_data.get('last_name', '')}")
        lines.append(f"  DOB:   {self.patient_data.get('dob', '')}")
        lines.append(f"  Phone: {self.patient_data.get('phone', '')}")
        lines.append(f"  Store: {self.patient_data.get('store_number', DEFAULT_STORE_NUMBER)}")
        lines.append(f"  Client: {self.patient_data.get('client_id', DEFAULT_CLIENT_ID)}")
        lines.append(f"  Env:   {self.current_environment}")
        lines.append("")

        lines.append(f"═══ PRESCRIPTIONS ({len(self.prescriptions)}) ═══")
        for i, rx in enumerate(self.prescriptions, 1):
            status = rx["rx_status"]
            lines.append(f"\n  [{i}] RX# {rx['rx_number']}")
            lines.append(f"      Drug:    {rx['drug_name']}")
            lines.append(f"      Status:  {status.value}")
            lines.append(f"      Copay:   ${rx.get('copay', 10.0):.2f}")
            lines.append(f"      Supply:  {rx.get('days_supply', 30)} days")
            lines.append(f"      Refills: {rx.get('refills_remaining', 3)} remaining")

            # Show what the builder will produce
            try:
                scenario = build_scenario(
                    rx_status=status,
                    rx_number=rx["rx_number"],
                    patient_first=self.patient_data.get("first_name", "STATUS"),
                    patient_last=self.patient_data.get("last_name", "TESTPATIENT"),
                    patient_phone=self.patient_data.get("phone", "5550561001"),
                    patient_dob=self.patient_data.get("dob", "19850101"),
                    drug_name=rx["drug_name"],
                    store_number=self.patient_data.get("store_number", DEFAULT_STORE_NUMBER),
                    client_id=int(self.patient_data.get("client_id", DEFAULT_CLIENT_ID)),
                    store_id=int(self.patient_data.get("store_id", DEFAULT_STORE_ID)),
                    store_npi=self.patient_data.get("store_npi", DEFAULT_STORE_NPI),
                    copay=rx.get("copay", 10.0),
                    days_supply=rx.get("days_supply", 30),
                    refills_remaining=rx.get("refills_remaining", 3),
                    authorized_refills=rx.get("authorized_refills", 5),
                    include_p360=False,
                )
                lines.append(f"      ─── Will produce: ───")
                lines.append(f"      RxResponse code:     {scenario.rx.rx_response_status_code:03d} ({scenario.rx.rx_response_status_description})")
                lines.append(f"      StatusResponse code: {scenario.rx.status_code} ({scenario.rx.status_description})")
                lines.append(f"      Drug schedule:       {scenario.rx.drug_schedule}")
                lines.append(f"      Delivered days ago:  {scenario.rx.delivered_days_ago}")
                if scenario.rx.reject_code:
                    lines.append(f"      Reject code:         {scenario.rx.reject_code}")
                if scenario.notes:
                    lines.append(f"      Note: {scenario.notes}")
            except ValueError as e:
                lines.append(f"      ⚠️  {e}")

        lines.append("")
        lines.append(f"═══ FILES TO UPLOAD ═══")
        for rx in self.prescriptions:
            lines.append(f"  PDX/RxResponse{rx['rx_number']}.xml")
            lines.append(f"  PDX/StatusResponse{rx['rx_number']}.xml")
            lines.append(f"  PDX/RefillResponse{rx['rx_number']}.xml")

        if self.enable_p360.get() and HAS_P360:
            lines.append("")
            lines.append(f"═══ P360 PATIENT DOCUMENT ═══")
            lines.append(f"  DB:         p360_daily_docker.patient")
            lines.append(f"  Operation:  replace_one (upsert=True)")
            lines.append(f"  Match on:   clientId + phone + firstName + lastName")

        self._preview_text.insert("1.0", "\n".join(lines))
        self._preview_text.configure(state=DISABLED)

    # ──────────────────────────────────────────────────────────────────────────
    # Submit
    # ──────────────────────────────────────────────────────────────────────────

    def _submit(self):
        """Build scenarios and upload everything."""
        results = []
        errors = []

        for rx_data in self.prescriptions:
            try:
                scenario = build_scenario(
                    rx_status=rx_data["rx_status"],
                    rx_number=rx_data["rx_number"],
                    patient_first=self.patient_data.get("first_name", "STATUS"),
                    patient_last=self.patient_data.get("last_name", "TESTPATIENT"),
                    patient_phone=self.patient_data.get("phone", "5550561001"),
                    patient_dob=self.patient_data.get("dob", "19850101"),
                    drug_name=rx_data["drug_name"],
                    store_number=self.patient_data.get("store_number", DEFAULT_STORE_NUMBER),
                    client_id=int(self.patient_data.get("client_id", DEFAULT_CLIENT_ID)),
                    store_id=int(self.patient_data.get("store_id", DEFAULT_STORE_ID)),
                    store_npi=self.patient_data.get("store_npi", DEFAULT_STORE_NPI),
                    copay=rx_data.get("copay", 10.0),
                    days_supply=rx_data.get("days_supply", 30),
                    refills_remaining=rx_data.get("refills_remaining", 3),
                    authorized_refills=rx_data.get("authorized_refills", 5),
                    include_p360=self.enable_p360.get() and HAS_P360,
                    sig_text=rx_data.get("sig_text", "Take one tablet by mouth every day"),
                )

                # Upload XML to simulator
                upload_rx(scenario.rx)
                results.append(f"✅ RX# {rx_data['rx_number']} → {rx_data['rx_status'].value}")

                # Upload P360 if enabled
                if self.enable_p360.get() and HAS_P360 and scenario.p360_patient:
                    ensure_patient(scenario.p360_patient)
                    results.append(f"   ✅ P360 patient upserted")

                self.scenarios.append(scenario)

            except Exception as e:
                errors.append(f"❌ RX# {rx_data['rx_number']}: {e}")
                logger.exception("Failed to upload rx %s", rx_data["rx_number"])

        # Show results
        msg = "\n".join(results + errors)
        if errors:
            messagebox.showwarning(
                "Partial Success" if results else "Failed",
                f"Results:\n\n{msg}",
            )
        else:
            messagebox.showinfo(
                "Success!",
                f"All {len(self.prescriptions)} prescription(s) uploaded!\n\n{msg}",
            )

        # Ask to reset
        if results and messagebox.askyesno("Continue?", "Create another patient?"):
            self._reset()

    def _reset(self):
        """Reset wizard state."""
        self.patient_data = {}
        self.prescriptions = []
        self.scenarios = []
        self._show_step(0)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario Save/Load
    # ──────────────────────────────────────────────────────────────────────────

    def _save_scenario(self):
        name = self._scenario_name.get().strip()
        if not name:
            messagebox.showerror("Error", "Enter a scenario name.")
            return

        # Serialize prescriptions (RxStatus enum → string)
        serialized_rxs = []
        for rx in self.prescriptions:
            rx_copy = dict(rx)
            rx_copy["rx_status"] = rx["rx_status"].value if isinstance(rx["rx_status"], RxStatus) else rx["rx_status"]
            serialized_rxs.append(rx_copy)

        scenario_data = {
            "name": name,
            "patient_data": self.patient_data,
            "prescriptions": serialized_rxs,
            "p360_enabled": self.enable_p360.get(),
            "environment": self.current_environment,
            "timestamp": datetime.now().isoformat(),
        }

        # Check for existing
        existing_idx = next((i for i, s in enumerate(self.saved_scenarios) if s["name"] == name), None)
        if existing_idx is not None:
            if not messagebox.askyesno("Overwrite?", f"Scenario '{name}' exists. Overwrite?"):
                return
            self.saved_scenarios[existing_idx] = scenario_data
        else:
            self.saved_scenarios.append(scenario_data)

        self._save_json(SAVED_SCENARIOS_FILE, self.saved_scenarios)
        messagebox.showinfo("Saved", f"Scenario '{name}' saved!")

    def _quick_load(self):
        idx = self._scenario_combo.current()
        if idx < 0:
            return
        self._load_scenario_data(self.saved_scenarios[idx])
        self._show_step(0)

    def _quick_load_submit(self):
        idx = self._scenario_combo.current()
        if idx < 0:
            return
        self._load_scenario_data(self.saved_scenarios[idx])
        self._submit()

    def _load_scenario_data(self, scenario: dict):
        self.patient_data = scenario.get("patient_data", {})
        self.prescriptions = []
        for rx in scenario.get("prescriptions", []):
            rx_copy = dict(rx)
            # Deserialize status string → enum
            if isinstance(rx_copy.get("rx_status"), str):
                try:
                    rx_copy["rx_status"] = RxStatus(rx_copy["rx_status"])
                except ValueError:
                    rx_copy["rx_status"] = RxStatus.REFILLABLE
            self.prescriptions.append(rx_copy)
        self.enable_p360.set(scenario.get("p360_enabled", True))

    # ──────────────────────────────────────────────────────────────────────────
    # Environment
    # ──────────────────────────────────────────────────────────────────────────

    def _on_env_change(self, event=None):
        new_env = self.env_combo.get()
        if new_env != self.current_environment:
            self.current_environment = new_env
            # The builder library uses a module-level SIM_BASE_URL;
            # for environment switching, we'd need to update it.
            # For now, show a note:
            import tests.helpers_pms_sim as pms_mod
            env_url = ENVIRONMENTS[new_env]["sim_base_url"]
            pms_mod.SIM_BASE_URL = env_url
            self.root.title(f"PMSI Data Builder — {new_env}")
            logger.info("Switched to %s: %s", new_env, env_url)

    # ──────────────────────────────────────────────────────────────────────────
    # Utils
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    @staticmethod
    def _save_json(path: Path, data):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────


def main():
    if HAS_BOOTSTRAP:
        root = ttk.Window(themename="cosmo")
    else:
        root = tk.Tk()

    PMSIDataBuilderUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
