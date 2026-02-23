#!/usr/bin/env python3
"""
PMSI Simulator Data Management UI - Modern Version
Multi-step wizard with modern styling and multi-RX support
"""

import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, filedialog
import json
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
import requests
import os
import sys
import random

try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    HAS_BOOTSTRAP = True
except ImportError:
    import tkinter.ttk as ttk
    from tkinter import BOTH, YES, LEFT, RIGHT, X, CENTER, DISABLED, NORMAL
    HAS_BOOTSTRAP = False
    print("ttkbootstrap not available, using standard ttk")

# Don't use tkcalendar - causes conflicts in PyInstaller
HAS_CALENDAR = False

try:
    from pymongo import MongoClient
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False

class ModernPMSIUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PMSI Data Manager - Modern")
        self.root.geometry("1200x800")
        
        # Get base path for resources (works in both dev and frozen)
        if getattr(sys, 'frozen', False):
            self.base_path = sys._MEIPASS
        else:
            self.base_path = os.path.dirname(os.path.abspath(__file__))
        
        # Load environment configuration
        self.environments = self.load_environment_config()
        self.current_environment = self.environments.get("default_environment", "QA")
        self.apply_environment_config()
        
        # Wizard state
        self.current_step = 0
        self.patient_data = {}
        self.prescriptions = []  # List of prescription dictionaries
        self.enable_personalization = tk.BooleanVar(value=False)  # Initialize early
        
        # Setup modern UI
        self.setup_modern_ui()
    
    def load_environment_config(self) -> Dict:
        """Load environment configuration from file"""
        try:
            config_path = os.path.join(self.base_path, "environment_config.json")
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load environment config: {e}")
            return {
                "environments": {
                    "QA": {
                        "name": "QA Environment",
                        "pmsi_api_url": "https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co",
                        "documentdb_connection": "mongodb://docdb_admin:P360DocumentDockerCopy0507@p360-document-db-dev.cluster-ccmb0vzyiebh.us-east-2.docdb.amazonaws.com:27017/?ssl=true&retryWrites=false&loadBalanced=false&connectTimeoutMS=10000&authSource=admin&authMechanism=SCRAM-SHA-1",
                        "documentdb_database": "p360_daily_docker"
                    }
                },
                "default_environment": "QA"
            }
    
    def apply_environment_config(self):
        """Apply the current environment configuration"""
        env_config = self.environments.get("environments", {}).get(self.current_environment, {})
        
        if env_config:
            self.api_base_url = env_config.get("pmsi_api_url", "")
            self.docdb_connection_string = env_config.get("documentdb_connection", "")
            self.docdb_database = env_config.get("documentdb_database", "p360_daily_docker")
    
    def setup_modern_ui(self):
        """Setup the modern UI with wizard steps"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=BOTH, expand=YES, padx=20, pady=20)
        
        # Header with environment selector
        self.create_header(main_frame)
        
        # Progress indicator
        self.create_progress_indicator(main_frame)
        
        # Content area (will change based on step)
        self.content_frame = ttk.Frame(main_frame)
        self.content_frame.pack(fill=BOTH, expand=YES, pady=20)
        
        # Navigation buttons
        self.create_navigation(main_frame)
        
        # Show first step
        self.show_step(0)
    
    def create_header(self, parent):
        """Create modern header with environment selector"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=X, pady=(0, 20))
        
        # Title
        title = ttk.Label(header_frame, text="PMSI Data Manager", 
                         font=("Segoe UI", 24, "bold"))
        title.pack(side=LEFT)
        
        # Environment selector
        env_frame = ttk.Frame(header_frame)
        env_frame.pack(side=RIGHT)
        
        ttk.Label(env_frame, text="Environment:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 10))
        
        env_names = list(self.environments.get("environments", {}).keys())
        self.env_selector = ttk.Combobox(env_frame, values=env_names, state="readonly", width=15)
        self.env_selector.set(self.current_environment)
        self.env_selector.bind("<<ComboboxSelected>>", self.on_environment_change)
        self.env_selector.pack(side=LEFT)
    
    def create_progress_indicator(self, parent):
        """Create progress indicator showing wizard steps"""
        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill=X, pady=(0, 20))
        
        self.steps = [
            "Patient Info",
            "Prescriptions", 
            "Review & Submit"
        ]
        
        self.step_labels = []
        for i, step_name in enumerate(self.steps):
            # Step circle
            step_frame = ttk.Frame(progress_frame)
            step_frame.pack(side=LEFT, expand=YES, fill=X)
            
            # Circle with number
            circle_label = ttk.Label(step_frame, text=str(i+1), 
                                    font=("Segoe UI", 12, "bold"),
                                    width=3, anchor=CENTER)
            circle_label.pack()
            
            # Step name
            name_label = ttk.Label(step_frame, text=step_name, 
                                  font=("Segoe UI", 9))
            name_label.pack()
            
            self.step_labels.append((circle_label, name_label))
    
    def create_navigation(self, parent):
        """Create navigation buttons"""
        nav_frame = ttk.Frame(parent)
        nav_frame.pack(fill=X, pady=(20, 0))
        
        self.btn_back = ttk.Button(nav_frame, text="← Back", 
                                   command=self.go_back, width=15)
        self.btn_back.pack(side=LEFT)
        
        self.btn_next = ttk.Button(nav_frame, text="Next →", 
                                   command=self.go_next, width=15)
        self.btn_next.pack(side=RIGHT)
    
    def show_step(self, step_num):
        """Show the specified wizard step"""
        self.current_step = step_num
        
        # Clear content frame
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # Update progress indicator
        self.update_progress_indicator()
        
        # Show appropriate step
        if step_num == 0:
            self.show_patient_step()
        elif step_num == 1:
            self.show_prescriptions_step()
        elif step_num == 2:
            self.show_review_step()
        
        # Update navigation buttons
        self.update_navigation_buttons()
    
    def update_progress_indicator(self):
        """Update progress indicator styling"""
        for i, (circle, name) in enumerate(self.step_labels):
            if i == self.current_step:
                # Current step - highlighted
                circle.configure(foreground="white", background="#007bff")
                name.configure(font=("Segoe UI", 9, "bold"))
            elif i < self.current_step:
                # Completed step
                circle.configure(foreground="white", background="#28a745")
                name.configure(font=("Segoe UI", 9))
            else:
                # Future step
                circle.configure(foreground="gray", background="lightgray")
                name.configure(font=("Segoe UI", 9))
    
    def update_navigation_buttons(self):
        """Update navigation button states"""
        # Back button
        if self.current_step == 0:
            self.btn_back.configure(state=DISABLED)
        else:
            self.btn_back.configure(state=NORMAL)
        
        # Next button text
        if self.current_step == len(self.steps) - 1:
            self.btn_next.configure(text="Submit")
        else:
            self.btn_next.configure(text="Next →")
    
    def show_patient_step(self):
        """Show patient information step"""
        # Create card-style container
        card = ttk.LabelFrame(self.content_frame, text="Patient Information")
        card.pack(fill=BOTH, expand=YES, padx=20, pady=20)
        
        # Patient fields
        self.patient_fields = {}
        
        fields = [
            ("first_name", "First Name", "text", True),
            ("last_name", "Last Name", "text", True),
            ("dob", "Date of Birth (YYYY-MM-DD)", "date", True),
            ("phone", "Phone Number", "text", True),
            ("client_id", "Client ID", "text", True),
            ("store_id", "Store ID", "text", True),
            ("pmsi_store_id", "PMSI Store ID", "text", True),
        ]
        
        for field_name, label, field_type, required in fields:
            self.create_field(card, field_name, label, field_type, required, self.patient_fields)
        
        # Load existing patient data if available
        for field_name, widget in self.patient_fields.items():
            if field_name in self.patient_data:
                widget.delete(0, tk.END)
                widget.insert(0, self.patient_data[field_name])
    
    def show_prescriptions_step(self):
        """Show prescriptions management step"""
        # Header with add button
        header = ttk.Frame(self.content_frame)
        header.pack(fill=X, pady=(0, 10))
        
        ttk.Label(header, text="Prescriptions", font=("Segoe UI", 16, "bold")).pack(side=LEFT)
        ttk.Button(header, text="+ Add Prescription", 
                  command=self.add_prescription_dialog).pack(side=RIGHT)
        
        # List of prescriptions
        self.rx_list_frame = ttk.Frame(self.content_frame)
        self.rx_list_frame.pack(fill=BOTH, expand=YES)
        
        self.refresh_prescription_list()
    
    def show_review_step(self):
        """Show review and submit step"""
        # Review card
        card = ttk.LabelFrame(self.content_frame, text="Review Your Data")
        card.pack(fill=BOTH, expand=YES, padx=20, pady=20)
        
        # Scrolled text for review
        review_text = scrolledtext.ScrolledText(card, height=20, width=80, 
                                               font=("Consolas", 10))
        review_text.pack(fill=BOTH, expand=YES)
        
        # Build review content
        review_content = self.build_review_content()
        review_text.insert(1.0, review_content)
        review_text.configure(state=DISABLED)
        
        # Options
        options_frame = ttk.LabelFrame(card, text="Submission Options")
        options_frame.pack(fill=X, pady=(10, 0), padx=10)
        
        # Personalization toggle (use existing variable)
        ttk.Checkbutton(options_frame, text="Enable Personalization (Create DocumentDB entries)", 
                       variable=self.enable_personalization).pack(anchor='w', pady=5)
        
        ttk.Label(options_frame, text="Note: Personalization creates patient records in DocumentDB for testing.",
                 font=("Segoe UI", 8, "italic"), foreground="gray").pack(anchor='w')
    
    def create_field(self, parent, field_name, label, field_type, required, field_dict):
        """Create a form field"""
        field_frame = ttk.Frame(parent)
        field_frame.pack(fill=X, pady=5)
        
        # Label
        label_text = f"{label}{'*' if required else ''}"
        ttk.Label(field_frame, text=label_text, width=25).pack(side=LEFT, padx=(0, 10))
        
        # Input widget with calendar button for dates
        if field_type == "date":
            entry_frame = ttk.Frame(field_frame)
            entry_frame.pack(side=LEFT, fill=X, expand=YES)
            
            widget = ttk.Entry(entry_frame, width=35)
            widget.pack(side=LEFT, fill=X, expand=YES)
            
            cal_btn = ttk.Button(entry_frame, text="📅", width=3,
                               command=lambda: self.show_date_picker(widget))
            cal_btn.pack(side=LEFT, padx=(5, 0))
        else:
            widget = ttk.Entry(field_frame, width=40)
            widget.pack(side=LEFT, fill=X, expand=YES)
        
        field_dict[field_name] = widget
    
    def show_date_picker(self, entry_widget):
        """Show simple date picker dialog"""
        picker = tk.Toplevel(self.root)
        picker.title("Select Date")
        picker.geometry("300x200")
        picker.transient(self.root)
        picker.grab_set()
        
        today = date.today()
        
        ttk.Label(picker, text="Year:").pack(pady=5)
        year_var = tk.StringVar(value=str(today.year))
        year_spin = ttk.Spinbox(picker, from_=1900, to=2100, textvariable=year_var, width=10)
        year_spin.pack()
        
        ttk.Label(picker, text="Month:").pack(pady=5)
        month_var = tk.StringVar(value=str(today.month))
        month_spin = ttk.Spinbox(picker, from_=1, to=12, textvariable=month_var, width=10)
        month_spin.pack()
        
        ttk.Label(picker, text="Day:").pack(pady=5)
        day_var = tk.StringVar(value=str(today.day))
        day_spin = ttk.Spinbox(picker, from_=1, to=31, textvariable=day_var, width=10)
        day_spin.pack()
        
        def set_date():
            try:
                selected = f"{year_var.get()}-{month_var.get().zfill(2)}-{day_var.get().zfill(2)}"
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, selected)
                picker.destroy()
            except:
                messagebox.showerror("Invalid Date", "Please enter a valid date")
        
        ttk.Button(picker, text="Set Date", command=set_date).pack(pady=10)
        ttk.Button(picker, text="Cancel", command=picker.destroy).pack()
    
    def add_prescription_dialog(self):
        """Show dialog to add a prescription"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Prescription")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Add padding frame
        content = ttk.Frame(dialog)
        content.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Prescription fields
        rx_fields = {}
        
        fields = [
            ("rx_number", "RX Number (leave blank for auto)", "text", False),
            ("rx_status", "RX Status", "dropdown", True),
            ("medication_name", "Medication Name", "text", True),
            ("strength", "Strength", "text", True),
            ("units", "Units", "text", True),
            ("last_fill_date", "Last Fill Date", "date", True),
            ("expiration_date", "Expiration Date", "date", True),
            ("copay", "Copay ($)", "text", True),
            ("pmsi_type", "PMSI Type", "dropdown", True),
        ]
        
        for field_name, label, field_type, required in fields:
            field_frame = ttk.Frame(content)
            field_frame.pack(fill=X, pady=5)
            
            ttk.Label(field_frame, text=f"{label}{'*' if required else ''}", 
                     width=25).pack(side=LEFT)
            
            if field_type == "dropdown":
                if field_name == "rx_status":
                    options = ["Active", "Inactive", "Pending", "Expired", "In Queue", 
                             "Ready for Pickup", "Picked Up", "Shipped", "Out of Refills"]
                else:  # pmsi_type
                    options = ["PDX EPS", "Liberty", "McKesson", "Epic", "AtebGen100", "PDX 275"]
                widget = ttk.Combobox(field_frame, values=options, state="readonly", width=37)
                widget.set(options[0])
            elif field_type == "date":
                entry_frame = ttk.Frame(field_frame)
                entry_frame.pack(side=LEFT, fill=X, expand=YES)
                
                widget = ttk.Entry(entry_frame, width=32)
                widget.pack(side=LEFT, fill=X, expand=YES)
                
                cal_btn = ttk.Button(entry_frame, text="📅", width=3,
                                   command=lambda w=widget: self.show_date_picker(w))
                cal_btn.pack(side=LEFT, padx=(5, 0))
            else:
                widget = ttk.Entry(field_frame, width=40)
            
            widget.pack(side=LEFT, fill=X, expand=YES)
            rx_fields[field_name] = widget
        
        # Buttons
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=X, padx=10, pady=10)
        
        def save_rx():
            rx_data = {}
            for field_name, widget in rx_fields.items():
                if isinstance(widget, ttk.Combobox):
                    rx_data[field_name] = widget.get()
                else:
                    rx_data[field_name] = widget.get().strip()
            
            # Generate RX number if blank
            if not rx_data.get("rx_number"):
                rx_data["rx_number"] = str(random.randint(1000000, 9999999))
            
            self.prescriptions.append(rx_data)
            self.refresh_prescription_list()
            dialog.destroy()
        
        ttk.Button(btn_frame, text="Add Prescription", command=save_rx).pack(side=RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=RIGHT)
    
    def refresh_prescription_list(self):
        """Refresh the prescription list display"""
        for widget in self.rx_list_frame.winfo_children():
            widget.destroy()
        
        if not self.prescriptions:
            ttk.Label(self.rx_list_frame, text="No prescriptions added yet. Click 'Add Prescription' to begin.",
                     font=("Segoe UI", 10, "italic")).pack(pady=50)
        else:
            for i, rx in enumerate(self.prescriptions):
                self.create_prescription_card(self.rx_list_frame, i, rx)
    
    def create_prescription_card(self, parent, index, rx_data):
        """Create a card for a prescription"""
        card = ttk.LabelFrame(parent, text=f"RX #{rx_data.get('rx_number', 'N/A')}")
        card.pack(fill=X, pady=5, padx=10)
        
        # RX details
        details = f"Medication: {rx_data.get('medication_name', 'N/A')} | " \
                 f"Status: {rx_data.get('rx_status', 'N/A')} | " \
                 f"Type: {rx_data.get('pmsi_type', 'N/A')}"
        ttk.Label(card, text=details).pack(side=LEFT)
        
        # Remove button
        ttk.Button(card, text="Remove", 
                  command=lambda: self.remove_prescription(index)).pack(side=RIGHT)
    
    def remove_prescription(self, index):
        """Remove a prescription from the list"""
        if messagebox.askyesno("Confirm", "Remove this prescription?"):
            self.prescriptions.pop(index)
            self.refresh_prescription_list()
    
    def build_review_content(self):
        """Build review content string"""
        content = "=== PATIENT INFORMATION ===\n\n"
        for field_name, value in self.patient_data.items():
            content += f"{field_name.replace('_', ' ').title()}: {value}\n"
        
        content += f"\n=== PRESCRIPTIONS ({len(self.prescriptions)}) ===\n\n"
        for i, rx in enumerate(self.prescriptions, 1):
            content += f"Prescription {i}:\n"
            for key, value in rx.items():
                content += f"  {key.replace('_', ' ').title()}: {value}\n"
            content += "\n"
        
        content += f"=== OPTIONS ===\n\n"
        content += f"Environment: {self.current_environment}\n"
        # Get the actual checkbox state
        personalization_enabled = self.enable_personalization.get()
        content += f"Personalization: {'Enabled' if personalization_enabled else 'Disabled'}\n"
        
        return content
    
    def go_back(self):
        """Go to previous step"""
        if self.current_step > 0:
            self.show_step(self.current_step - 1)
    
    def go_next(self):
        """Go to next step or submit"""
        if self.current_step == len(self.steps) - 1:
            # Submit
            self.submit_data()
        else:
            # Validate current step
            if self.validate_current_step():
                self.show_step(self.current_step + 1)
    
    def validate_current_step(self):
        """Validate current step data"""
        if self.current_step == 0:
            # Save and validate patient info
            self.patient_data = {}
            for field_name, widget in self.patient_fields.items():
                value = widget.get() if hasattr(widget, 'get') else ""
                
                if not value:
                    messagebox.showerror("Validation Error", f"Please fill in {field_name.replace('_', ' ')}")
                    return False
                self.patient_data[field_name] = value
            return True
        elif self.current_step == 1:
            # Validate prescriptions
            if not self.prescriptions:
                messagebox.showerror("Validation Error", "Please add at least one prescription")
                return False
            return True
        return True
    
    def submit_data(self):
        """Submit all data - generate and upload files for all prescriptions"""
        try:
            # Load template configuration
            config_path = os.path.join(self.base_path, "templates", "template_config.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            all_uploaded_files = []
            
            # Process each prescription
            for rx in self.prescriptions:
                rx_number = rx.get("rx_number", "").strip()
                
                # Prepare combined data (patient + prescription)
                combined_data = {**self.patient_data, **rx}
                
                # Prepare template variables
                template_vars = self.prepare_template_variables(combined_data, rx_number, config)
                
                # Get PMSI type for folder path
                pmsi_type = rx.get("pmsi_type", "PDX EPS")
                folder_path = "PDX" if "PDX" in pmsi_type else pmsi_type.replace(" ", "")
                
                # Generate and upload files for this prescription
                for file_config in config["required_files"]:
                    template_path = os.path.join(self.base_path, "templates", file_config["template"])
                    output_filename = file_config["output_pattern"].format(rx_number=rx_number)
                    
                    # Read template
                    with open(template_path, 'r') as f:
                        template_content = f.read()
                    
                    # Replace tokens
                    for key, value in template_vars.items():
                        template_content = template_content.replace(f"{{{{{key}}}}}", str(value))
                    
                    # Upload to simulator
                    file_path = f"{folder_path}/{output_filename}"
                    success = self.upload_file_to_simulator(file_path, template_content)
                    
                    if success:
                        all_uploaded_files.append(file_path)
                    else:
                        messagebox.showerror("Upload Error", f"Failed to upload {file_path}")
                        return
            
            # Handle personalization if enabled
            personalization_msg = ""
            if self.enable_personalization.get():
                if self.create_personalization_entries():
                    personalization_msg = "\n\nPersonalization entries created in DocumentDB."
                else:
                    personalization_msg = "\n\nWarning: Failed to create personalization entries."
            
            # Show success message
            files_list = "\n".join(all_uploaded_files)
            success_msg = f"Successfully uploaded {len(all_uploaded_files)} files for {len(self.prescriptions)} prescription(s)!\n\n"
            success_msg += f"Files:\n{files_list}"
            success_msg += personalization_msg
            
            messagebox.showinfo("Success", success_msg)
            
            # Ask if user wants to start over
            if messagebox.askyesno("Continue?", "Would you like to create another patient?"):
                self.reset_wizard()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to submit data: {str(e)}")
    
    def on_environment_change(self, event=None):
        """Handle environment change"""
        new_env = self.env_selector.get()
        if new_env != self.current_environment:
            self.current_environment = new_env
            self.apply_environment_config()
            env_name = self.environments.get("environments", {}).get(new_env, {}).get("name", new_env)
            self.root.title(f"PMSI Data Manager - {env_name}")
            messagebox.showinfo("Environment Changed", f"Switched to {env_name}")
    
    def reset_wizard(self):
        """Reset wizard to start over"""
        self.patient_data = {}
        self.prescriptions = []
        self.enable_personalization.set(False)
        self.show_step(0)
    
    def prepare_template_variables(self, data: Dict[str, Any], rx_number: str, config: Dict) -> Dict[str, str]:
        """Prepare variables for template replacement"""
        # Get RX status mapping
        rx_status = data.get("rx_status", "Active")
        status_mapping = config["template_mappings"].get(rx_status, config["template_mappings"]["Active"])
        
        # Current datetime
        current_dt = datetime.now()
        promise_dt = current_dt + timedelta(days=2)
        
        # Prepare all template variables
        template_vars = {
            "rx_number": rx_number,
            "current_datetime": current_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            "promise_datetime": promise_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "pmsi_store_id": data.get("pmsi_store_id", "70050001"),
            "patient_first_name": data.get("first_name", "").upper(),
            "patient_last_name": data.get("last_name", "").upper(),
            "patient_dob": data.get("dob", ""),
            "patient_phone": data.get("phone", ""),
            "medication_name": data.get("medication_name", "").upper(),
            "strength": data.get("strength", ""),
            "units": data.get("units", "").upper(),
            "last_fill_date": data.get("last_fill_date", ""),
            "expiration_date": data.get("expiration_date", ""),
            "copay": data.get("copay", "0.00"),
            "refillable": status_mapping["refillable"],
            "prescription_status": status_mapping["prescription_status"],
            "rx_status_code": status_mapping["rx_status_code"],
            "rx_status_description": status_mapping["rx_status_description"],
            "refills_remaining": status_mapping["refills_remaining"],
            "remaining_quantity": status_mapping["remaining_quantity"]
        }
        
        # Handle date logic based on scenario
        date_logic = status_mapping.get("date_logic", "use_form_data")
        if date_logic == "past_expiration":
            past_date = current_dt - timedelta(days=30)
            template_vars["expiration_date"] = past_date.strftime("%Y-%m-%d")
        elif date_logic == "future_expiration":
            future_date = current_dt + timedelta(days=365)
            template_vars["expiration_date"] = future_date.strftime("%Y-%m-%d")
        elif date_logic == "within_5_days":
            fill_date = current_dt - timedelta(days=2)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_pickup":
            fill_date = current_dt - timedelta(days=1)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_ship":
            fill_date = current_dt - timedelta(days=3)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_fill":
            template_vars["last_fill_date"] = current_dt.strftime("%Y-%m-%d")
        elif date_logic == "out_of_refills":
            fill_date = current_dt - timedelta(days=7)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        
        return template_vars
    
    def upload_file_to_simulator(self, file_path: str, content: str) -> bool:
        """Upload a single file to the PMSI simulator via API"""
        try:
            url = f"{self.api_base_url}/pms-manage"
            params = {
                "action": "write",
                "file_path": file_path,
                "content": content
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    return result.get("status") == "success"
                except:
                    if "Connection refused" in response.text or "127.0.0.1:8081" in response.text:
                        messagebox.showerror("Service Unavailable", 
                                           "PMSI Simulator service is currently unavailable.\n\n" +
                                           "Please contact the development team to restart the service.")
                    return False
            else:
                return False
                
        except Exception as e:
            print(f"Upload error for {file_path}: {e}")
            return False
    
    def create_personalization_entries(self) -> bool:
        """Create personalization entries in DocumentDB for all prescriptions"""
        if not HAS_PYMONGO:
            messagebox.showerror("Missing Dependency", 
                               "pymongo is required for personalization.\n\n" +
                               "Install with: pip install pymongo")
            return False
        
        try:
            client = MongoClient(self.docdb_connection_string, 
                               serverSelectionTimeoutMS=5000,
                               tlsAllowInvalidCertificates=True)
            client.admin.command('ping')
            
            db = client[self.docdb_database]
            collection = db['patient']
            
            # Generate patient ID
            ateb_patient_id = random.randint(20000, 99999)
            
            # Convert dates
            dob_formatted = self.patient_data.get("dob", "").replace("-", "")
            
            # Create prescription objects
            prescriptions = []
            for rx in self.prescriptions:
                fill_date_formatted = rx.get("last_fill_date", "").replace("-", "")
                expire_date_formatted = rx.get("expiration_date", "").replace("-", "")
                
                # Generate unique GPI for each prescription
                unique_gpi = f"34000003100340{random.randint(0, 9)}"
                
                prescription = {
                    "fillDate": fill_date_formatted,
                    "soldDate": fill_date_formatted,
                    "expireDate": expire_date_formatted,
                    "originalRefillsAuth": 7.0,
                    "medication": {
                        "gpi": unique_gpi,
                        "medicationName": rx.get("medication_name", "").upper(),
                        "speakableMedName": rx.get("medication_name", "").upper(),
                        "ndc": "65162000850"
                    },
                    "rxNum": rx.get("rx_number", ""),
                    "rxStatus": self.map_rx_status_to_docdb(rx.get("rx_status", "Active")),
                    "daysSupply": 30.0,
                    "refillsRemaining": 7.0,
                    "dispensedQuantity": 30.0,
                    "originalDispensedQuantity": 30.0,
                    "autofillProgram": False,
                    "patientRxId": float(ateb_patient_id + len(prescriptions)),
                    "medicationName": rx.get("medication_name", "").upper(),
                    "gpi": unique_gpi,
                    "ndc": "65162000850",
                    "prescriptionStoreNpi": str(random.randint(1000000000, 9999999999))
                }
                prescriptions.append(prescription)
            
            # Create patient document
            personalization_doc = {
                "atebPatientId": float(ateb_patient_id),
                "dateOfBirth": dob_formatted,
                "testCase": "pmsi ui generated - modern",
                "prescriptions": prescriptions,
                "clientId": float(self.patient_data.get("client_id", "1537")),
                "storeId": float(self.patient_data.get("store_id", "13387")),
                "storeNpi": self.patient_data.get("pmsi_store_id", "1821516543"),
                "pharmacyPatientId": prescriptions[0]["rxNum"] if prescriptions else "",
                "name": {
                    "firstName": self.patient_data.get("first_name", ""),
                    "lastName": self.patient_data.get("last_name", "")
                },
                "phone": {
                    "primary": self.patient_data.get("phone", ""),
                    "mobile": self.patient_data.get("phone", ""),
                    "alternate": ""
                },
                "firstName": self.patient_data.get("first_name", ""),
                "lastName": self.patient_data.get("last_name", ""),
                "preferenceAttributes": []
            }
            
            result = collection.insert_one(personalization_doc)
            client.close()
            
            # Save locally
            if result.inserted_id:
                self.save_docdb_entry_locally(personalization_doc)
            
            return result.inserted_id is not None
            
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to create personalization: {str(e)}")
            return False
    
    def map_rx_status_to_docdb(self, rx_status: str) -> str:
        """Map UI RX status to DocumentDB format"""
        status_mapping = {
            "Active": "ACTIVE",
            "Inactive": "INACTIVE", 
            "Pending": "PENDING",
            "Expired": "EXPIRED",
            "In Queue": "IN_QUEUE",
            "Ready for Pickup": "READY",
            "Picked Up": "SOLD",
            "Shipped": "SHIPPED",
            "Out of Refills": "NO_REFILLS"
        }
        return status_mapping.get(rx_status, "ACTIVE")
    
    def save_docdb_entry_locally(self, patient_doc: Dict):
        """Save DocumentDB entry locally for reference"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            rx_numbers = "_".join([p["rxNum"] for p in patient_doc.get("prescriptions", [])[:3]])
            filename = f"docdb_patient_{rx_numbers}_{timestamp}.json"
            
            local_doc = {
                "type": "new_patient_created",
                "patient_document": patient_doc,
                "timestamp": timestamp
            }
            
            with open(filename, 'w') as f:
                json.dump(local_doc, f, indent=2)
            
            print(f"DocumentDB entry saved locally: {filename}")
            
        except Exception as e:
            print(f"Failed to save DocumentDB entry locally: {e}")



def main():
    if HAS_BOOTSTRAP:
        root = ttk.Window(themename="cosmo")  # Modern theme
    else:
        root = tk.Tk()
    
    app = ModernPMSIUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
