#!/usr/bin/env python3
"""
PMSI Simulator Data Management UI
A cross-platform GUI for managing PMSI simulator files and data.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import json
from datetime import datetime, date, timedelta
from typing import Dict, Any
import requests
from urllib.parse import urlencode
import os
import random
try:
    from tkcalendar import DateEntry
    HAS_CALENDAR = True
except ImportError:
    HAS_CALENDAR = False

class PMSIDataUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PMSI Simulator Data Manager")
        self.root.geometry("800x700")
        
        # API base URL - configurable
        self.api_base_url = "https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co"
        
        # Data fields configuration - easily expandable
        self.data_fields = {
            "PMSI Configuration": {
                "pmsi_type": {"label": "PMSI Type", "type": "dropdown", 
                             "options": ["PDX EPS", "Liberty", "McKesson", "Epic", "AtebGen100", "PDX 275"], 
                             "required": True, "default": "PDX EPS"},
            },
            "Patient Information": {
                "patient_first_name": {"label": "Patient First Name", "type": "text", "required": True},
                "patient_last_name": {"label": "Patient Last Name", "type": "text", "required": True},
                "patient_dob": {"label": "Patient DOB (YYYY-MM-DD)", "type": "date", "required": True},
                "patient_phone": {"label": "Patient Phone", "type": "text", "required": True},
            },
            "Prescription Information": {
                "rx_number": {"label": "RX Number", "type": "text", "required": False, "tooltip": "Leave blank to auto-generate a random 7-digit number"},
                "rx_status": {"label": "RX Status", "type": "dropdown", "options": ["Active", "Inactive", "Pending", "Expired", "In Queue", "Ready for Pickup", "Picked Up", "Shipped", "Out of Refills"], "required": True},
                "medication_name": {"label": "Medication Name", "type": "text", "required": True},
                "strength": {"label": "Strength", "type": "text", "required": True},
                "units": {"label": "Units", "type": "text", "required": True},
                "last_fill_date": {"label": "Last Fill Date (YYYY-MM-DD)", "type": "date", "required": True},
                "expiration_date": {"label": "Expiration Date (YYYY-MM-DD)", "type": "date", "required": True},
                "copay": {"label": "Copay ($)", "type": "number", "required": True},
            },
            "Store Information": {
                "client_id": {"label": "Client ID", "type": "text", "required": True},
                "store_id": {"label": "Store ID", "type": "text", "required": True},
                "pmsi_store_id": {"label": "PMSI Store ID", "type": "text", "required": True},
            }
        }
        
        self.field_widgets = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the main UI components"""
        # Create main frame with scrollbar
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Canvas and scrollbar for scrolling
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Title
        title_label = ttk.Label(scrollable_frame, text="PMSI Simulator Data Manager", 
                               font=("Arial", 16, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Create form sections
        self.create_form_sections(scrollable_frame)
        
        # Buttons frame
        buttons_frame = ttk.Frame(scrollable_frame)
        buttons_frame.pack(fill=tk.X, pady=20)
        
        # Action buttons
        ttk.Button(buttons_frame, text="Generate Preview", 
                  command=self.generate_preview).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Generate Files", 
                  command=self.generate_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Upload to Simulator", 
                  command=self.upload_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Check RX Exists", 
                  command=self.check_rx_number).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Save Data", 
                  command=self.save_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Load Data", 
                  command=self.load_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Clear All", 
                  command=self.clear_all).pack(side=tk.LEFT, padx=5)
        
        # Preview area
        preview_label = ttk.Label(scrollable_frame, text="Data Preview:", font=("Arial", 12, "bold"))
        preview_label.pack(anchor=tk.W, pady=(20, 5))
        
        self.preview_text = scrolledtext.ScrolledText(scrollable_frame, height=10, width=80)
        self.preview_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    def create_form_sections(self, parent):
        """Create form sections based on data_fields configuration"""
        for section_name, fields in self.data_fields.items():
            # Section frame
            section_frame = ttk.LabelFrame(parent, text=section_name, padding=10)
            section_frame.pack(fill=tk.X, pady=10)
            
            # Create fields in this section
            for field_name, field_config in fields.items():
                self.create_field(section_frame, field_name, field_config)
    
    def create_field(self, parent, field_name, config):
        """Create a single form field"""
        field_frame = ttk.Frame(parent)
        field_frame.pack(fill=tk.X, pady=5)
        
        # Label
        label_text = config["label"]
        if config.get("required", False):
            label_text += " *"
        
        label = ttk.Label(field_frame, text=label_text, width=25)
        label.pack(side=tk.LEFT, padx=(0, 10))
        
        # Input widget based on type
        if config["type"] == "dropdown":
            widget = ttk.Combobox(field_frame, values=config["options"], state="readonly")
            # Set default value if specified
            if config.get("default"):
                widget.set(config["default"])
            # Add status change handler for rx_status
            if field_name == "rx_status":
                widget.bind("<<ComboboxSelected>>", self.on_status_change)
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        elif config["type"] == "date":
            # Create frame for date entry and button
            date_frame = ttk.Frame(field_frame)
            date_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            if HAS_CALENDAR:
                # Use DateEntry if tkcalendar is available
                widget = DateEntry(date_frame, width=12, background='darkblue',
                                 foreground='white', borderwidth=2, date_pattern='yyyy-mm-dd')
                widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            else:
                # Fallback to regular entry with calendar button
                widget = ttk.Entry(date_frame)
                widget.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
                
                # Add calendar button
                cal_btn = ttk.Button(date_frame, text="📅", width=3,
                                   command=lambda: self.open_calendar(widget))
                cal_btn.pack(side=tk.RIGHT)
        else:  # text, number
            widget = ttk.Entry(field_frame)
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Add tooltip if specified
        if config.get("tooltip"):
            def show_tooltip(event):
                tooltip = tk.Toplevel()
                tooltip.wm_overrideredirect(True)
                tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                ttk.Label(tooltip, text=config["tooltip"], background="lightyellow", 
                         relief="solid", borderwidth=1, font=("Arial", 8)).pack()
                tooltip.after(3000, tooltip.destroy)
            
            def hide_tooltip(event):
                pass
            
            widget.bind("<Enter>", show_tooltip)
            widget.bind("<Leave>", hide_tooltip)
        
        self.field_widgets[field_name] = widget
    
    def get_form_data(self) -> Dict[str, Any]:
        """Get all form data as a dictionary"""
        data = {}
        for field_name, widget in self.field_widgets.items():
            if isinstance(widget, ttk.Combobox):
                data[field_name] = widget.get()
            elif HAS_CALENDAR and hasattr(widget, 'get_date'):
                # DateEntry widget
                try:
                    date_val = widget.get_date()
                    data[field_name] = date_val.strftime('%Y-%m-%d') if date_val else ''
                except:
                    data[field_name] = widget.get().strip()
            else:
                data[field_name] = widget.get().strip()
        return data
    
    def validate_data(self, data: Dict[str, Any]) -> tuple[bool, str]:
        """Validate form data"""
        errors = []
        
        # Check required fields
        for section_name, fields in self.data_fields.items():
            for field_name, config in fields.items():
                if config.get("required", False) and not data.get(field_name):
                    errors.append(f"{config['label']} is required")
        
        # Validate date formats
        date_fields = ["patient_dob", "last_fill_date", "expiration_date"]
        for field in date_fields:
            if data.get(field):
                try:
                    datetime.strptime(data[field], "%Y-%m-%d")
                except ValueError:
                    errors.append(f"{field.replace('_', ' ').title()} must be in YYYY-MM-DD format")
        
        # Validate copay is numeric
        if data.get("copay"):
            try:
                float(data["copay"])
            except ValueError:
                errors.append("Copay must be a valid number")
        
        return len(errors) == 0, "\n".join(errors)
    
    def generate_preview(self):
        """Generate and display data preview"""
        data = self.get_form_data()
        is_valid, error_msg = self.validate_data(data)
        
        if not is_valid:
            messagebox.showerror("Validation Error", error_msg)
            return
        
        # Generate RX number if blank
        rx_number = data.get("rx_number", "").strip()
        if not rx_number:
            rx_number = str(random.randint(1000000, 9999999))
            self.field_widgets["rx_number"].delete(0, tk.END)
            self.field_widgets["rx_number"].insert(0, rx_number)
            data["rx_number"] = rx_number
        
        # Format data for preview
        preview = "=== PMSI Simulator Data ===\n\n"
        for section_name, fields in self.data_fields.items():
            preview += f"{section_name}:\n"
            for field_name, config in fields.items():
                value = data.get(field_name, "")
                preview += f"  {config['label']}: {value}\n"
            preview += "\n"
        
        preview += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(1.0, preview)
    
    def save_data(self):
        """Save current form data to JSON file with custom name"""
        data = self.get_form_data()
        is_valid, error_msg = self.validate_data(data)
        
        if not is_valid:
            messagebox.showerror("Validation Error", error_msg)
            return
        
        # Get scenario name from user
        scenario_name = tk.simpledialog.askstring(
            "Save Configuration", 
            "Enter scenario name:\n(e.g., 'Active_RX_Test', 'Expired_Medication')",
            parent=self.root
        )
        
        if not scenario_name:
            return
        
        # Clean filename
        clean_name = "".join(c for c in scenario_name if c.isalnum() or c in (' ', '-', '_')).strip()
        clean_name = clean_name.replace(' ', '_')
        
        if not clean_name:
            messagebox.showerror("Error", "Please enter a valid scenario name.")
            return
        
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"pmsi_{clean_name}_{timestamp}.json"
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Success", f"Data saved to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save data: {str(e)}")
    
    def load_data(self):
        """Load data from JSON file"""
        from tkinter import filedialog
        
        filename = filedialog.askopenfilename(
            title="Load PMSI Data",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            # Populate form fields
            for field_name, value in data.items():
                if field_name in self.field_widgets:
                    widget = self.field_widgets[field_name]
                    if isinstance(widget, ttk.Combobox):
                        widget.set(value)
                    elif HAS_CALENDAR and hasattr(widget, 'set_date'):
                        # DateEntry widget
                        try:
                            if value:
                                date_obj = datetime.strptime(value, '%Y-%m-%d').date()
                                widget.set_date(date_obj)
                        except:
                            pass
                    else:
                        widget.delete(0, tk.END)
                        widget.insert(0, str(value))
            
            messagebox.showinfo("Success", f"Data loaded from {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {str(e)}")
    
    def clear_all(self):
        """Clear all form fields"""
        if messagebox.askyesno("Confirm", "Clear all fields?"):
            for widget in self.field_widgets.values():
                if isinstance(widget, ttk.Combobox):
                    widget.set("")
                elif HAS_CALENDAR and hasattr(widget, 'set_date'):
                    widget.set_date(date.today())
                else:
                    widget.delete(0, tk.END)
            self.preview_text.delete(1.0, tk.END)
    
    def generate_files(self):
        """Generate XML files from templates based on form data"""
        data = self.get_form_data()
        is_valid, error_msg = self.validate_data(data)
        
        if not is_valid:
            messagebox.showerror("Validation Error", error_msg)
            return
        
        try:
            # Load template configuration
            config_path = os.path.join("templates", "template_config.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Get RX number from form data or create one
            rx_number = data.get("rx_number", "").strip()
            if not rx_number:
                rx_number = str(random.randint(1000000, 9999999))
                # Update the form field with the generated number
                self.field_widgets["rx_number"].delete(0, tk.END)
                self.field_widgets["rx_number"].insert(0, rx_number)
            
            # Prepare template variables
            template_vars = self.prepare_template_variables(data, rx_number, config)
            
            # Generate files
            generated_files = []
            for file_config in config["required_files"]:
                template_path = os.path.join("templates", file_config["template"])
                output_filename = file_config["output_pattern"].format(rx_number=rx_number)
                
                # Read template
                with open(template_path, 'r') as f:
                    template_content = f.read()
                
                # Replace tokens
                for key, value in template_vars.items():
                    template_content = template_content.replace(f"{{{{{key}}}}}", str(value))
                
                # Write output file
                with open(output_filename, 'w') as f:
                    f.write(template_content)
                
                generated_files.append(output_filename)
            
            # Show success message
            files_list = "\n".join(generated_files)
            messagebox.showinfo("Success", f"Generated files:\n{files_list}\n\nRX Number: {rx_number}")
            
            # Update preview with file info
            preview = f"=== Generated Files ===\n\nRX Number: {rx_number}\n\nFiles created:\n"
            for filename in generated_files:
                preview += f"  - {filename}\n"
            preview += f"\nGenerated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, preview)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate files: {str(e)}")
    
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
            "patient_first_name": data.get("patient_first_name", "").upper(),
            "patient_last_name": data.get("patient_last_name", "").upper(),
            "patient_dob": data.get("patient_dob", ""),
            "patient_phone": data.get("patient_phone", ""),
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
            # Set expiration date to past for expired scenarios
            past_date = current_dt - timedelta(days=30)
            template_vars["expiration_date"] = past_date.strftime("%Y-%m-%d")
        elif date_logic == "future_expiration":
            # Set expiration date to future for active scenarios
            future_date = current_dt + timedelta(days=365)
            template_vars["expiration_date"] = future_date.strftime("%Y-%m-%d")
        elif date_logic == "within_5_days":
            # Set last fill date within last 5 days for Ready for Pickup
            fill_date = current_dt - timedelta(days=2)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_pickup":
            # Set last fill date to yesterday for Picked Up
            fill_date = current_dt - timedelta(days=1)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_ship":
            # Set last fill date to 3 days ago for Shipped
            fill_date = current_dt - timedelta(days=3)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        elif date_logic == "recent_fill":
            # Set last fill date to today for In Queue
            template_vars["last_fill_date"] = current_dt.strftime("%Y-%m-%d")
        elif date_logic == "out_of_refills":
            # Set last fill date to 1 week ago for Out of Refills
            fill_date = current_dt - timedelta(days=7)
            template_vars["last_fill_date"] = fill_date.strftime("%Y-%m-%d")
        # else use form data as-is
        
        return template_vars
    
    def upload_files(self):
        """Generate and upload XML files to PMSI simulator"""
        data = self.get_form_data()
        is_valid, error_msg = self.validate_data(data)
        
        if not is_valid:
            messagebox.showerror("Validation Error", error_msg)
            return
        
        try:
            # Load template configuration
            config_path = os.path.join("templates", "template_config.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Get RX number from form data or create one
            rx_number = data.get("rx_number", "").strip()
            if not rx_number:
                rx_number = str(random.randint(1000000, 9999999))
                # Update the form field with the generated number
                self.field_widgets["rx_number"].delete(0, tk.END)
                self.field_widgets["rx_number"].insert(0, rx_number)
            
            # Check if RX number already exists
            pmsi_type = data.get("pmsi_type", "PDX EPS")
            folder_path = "PDX" if "PDX" in pmsi_type else pmsi_type.replace(" ", "")
            
            if self.check_rx_exists(folder_path, rx_number):
                response = messagebox.askyesnocancel(
                    "RX Number Exists", 
                    f"RX Number {rx_number} already exists in {folder_path}.\n\n" +
                    "Yes = Overwrite existing files\n" +
                    "No = Generate new RX number\n" +
                    "Cancel = Abort upload"
                )
                
                if response is None:  # Cancel
                    return
                elif response is False:  # No - generate new number
                    rx_number = str(random.randint(1000000, 9999999))
                    # Update the form field with the new generated number
                    self.field_widgets["rx_number"].delete(0, tk.END)
                    self.field_widgets["rx_number"].insert(0, rx_number)
                    messagebox.showinfo("New RX Number", f"Generated new RX Number: {rx_number}")
                # If Yes (True), continue with existing number to overwrite
            
            # Prepare template variables
            template_vars = self.prepare_template_variables(data, rx_number, config)
            
            # Get PMSI type for folder path
            
            # Generate and upload files
            uploaded_files = []
            for file_config in config["required_files"]:
                template_path = os.path.join("templates", file_config["template"])
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
                    uploaded_files.append(file_path)
                else:
                    messagebox.showerror("Upload Error", f"Failed to upload {file_path}")
                    return
            
            # Show success message
            files_list = "\n".join(uploaded_files)
            messagebox.showinfo("Success", f"Uploaded files to simulator:\n{files_list}\n\nRX Number: {rx_number}")
            
            # Update preview
            preview = f"=== Files Uploaded to Simulator ===\n\nRX Number: {rx_number}\nPMSI Type: {pmsi_type}\nFolder: {folder_path}\n\nUploaded files:\n"
            for filepath in uploaded_files:
                preview += f"  - {filepath}\n"
            preview += f"\nUploaded on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, preview)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload files: {str(e)}")
    
    def on_status_change(self, event=None):
        """Handle RX status change and auto-populate related fields"""
        rx_status = self.field_widgets["rx_status"].get()
        current_dt = datetime.now()
        
        # Auto-populate dates based on status
        if rx_status == "Active":
            # Set expiration date to future
            future_date = current_dt + timedelta(days=365)
            self.set_date_field("expiration_date", future_date)
        elif rx_status == "Expired":
            # Set expiration date to past
            past_date = current_dt - timedelta(days=30)
            self.set_date_field("expiration_date", past_date)
        elif rx_status == "Ready for Pickup":
            # Set last fill date to 2 days ago (within 5 days)
            fill_date = current_dt - timedelta(days=2)
            self.set_date_field("last_fill_date", fill_date)
        elif rx_status == "Picked Up":
            # Set last fill date to 1 day ago
            fill_date = current_dt - timedelta(days=1)
            self.set_date_field("last_fill_date", fill_date)
        elif rx_status == "Shipped":
            # Set last fill date to 3 days ago
            fill_date = current_dt - timedelta(days=3)
            self.set_date_field("last_fill_date", fill_date)
        elif rx_status == "In Queue":
            # Set last fill date to today (just filled)
            self.set_date_field("last_fill_date", current_dt)
        elif rx_status == "Out of Refills":
            # Set last fill date to 1 week ago
            fill_date = current_dt - timedelta(days=7)
            self.set_date_field("last_fill_date", fill_date)
    
    def set_date_field(self, field_name: str, date_value: datetime):
        """Set a date field value"""
        if field_name in self.field_widgets:
            widget = self.field_widgets[field_name]
            date_str = date_value.strftime('%Y-%m-%d')
            
            if HAS_CALENDAR and hasattr(widget, 'set_date'):
                widget.set_date(date_value.date())
            else:
                widget.delete(0, tk.END)
                widget.insert(0, date_str)
    
    def check_rx_exists(self, folder_path: str, rx_number: str) -> bool:
        """Check if RX number already exists in the simulator"""
        try:
            test_filename = f"RxResponse{rx_number}.xml"
            file_path = f"{folder_path}/{test_filename}"
            url = f"{self.api_base_url}/files/{file_path}"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def check_rx_number(self):
        """Check if the current RX number exists in the simulator"""
        data = self.get_form_data()
        rx_number = data.get("rx_number", "").strip()
        
        if not rx_number:
            messagebox.showwarning("No RX Number", "Please enter an RX Number to check.")
            return
        
        pmsi_type = data.get("pmsi_type", "PDX EPS")
        folder_path = "PDX" if "PDX" in pmsi_type else pmsi_type.replace(" ", "")
        
        if self.check_rx_exists(folder_path, rx_number):
            messagebox.showwarning("RX Exists", f"RX Number {rx_number} already exists in {folder_path} folder.")
        else:
            messagebox.showinfo("RX Available", f"RX Number {rx_number} is available in {folder_path} folder.")
    
    def upload_file_to_simulator(self, file_path: str, content: str) -> bool:
        """Upload a single file to the PMSI simulator via API"""
        try:
            # Make API call
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
                    # Check if response contains service unavailable message
                    if "Connection refused" in response.text or "127.0.0.1:8081" in response.text:
                        messagebox.showerror("Service Unavailable", 
                                           "PMSI Simulator service is currently unavailable.\n\n" +
                                           "Please contact the development team to restart the service,\n" +
                                           "or use 'Generate Files' to create files locally.")
                    return False
            else:
                return False
                
        except Exception as e:
            print(f"Upload error for {file_path}: {e}")
            return False
    
    def open_calendar(self, entry_widget):
        """Open a simple calendar popup for date selection"""
        cal_window = tk.Toplevel(self.root)
        cal_window.title("Select Date")
        cal_window.geometry("300x250")
        cal_window.resizable(False, False)
        
        # Center the window
        cal_window.transient(self.root)
        cal_window.grab_set()
        
        # Simple date selection
        today = date.today()
        
        # Year selection
        year_frame = ttk.Frame(cal_window)
        year_frame.pack(pady=10)
        ttk.Label(year_frame, text="Year:").pack(side=tk.LEFT)
        year_var = tk.StringVar(value=str(today.year))
        year_spin = ttk.Spinbox(year_frame, from_=1900, to=2100, textvariable=year_var, width=10)
        year_spin.pack(side=tk.LEFT, padx=5)
        
        # Month selection
        month_frame = ttk.Frame(cal_window)
        month_frame.pack(pady=5)
        ttk.Label(month_frame, text="Month:").pack(side=tk.LEFT)
        months = ['January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December']
        month_var = tk.StringVar(value=months[today.month-1])
        month_combo = ttk.Combobox(month_frame, values=months, textvariable=month_var, state="readonly", width=12)
        month_combo.pack(side=tk.LEFT, padx=5)
        
        # Day selection
        day_frame = ttk.Frame(cal_window)
        day_frame.pack(pady=5)
        ttk.Label(day_frame, text="Day:").pack(side=tk.LEFT)
        day_var = tk.StringVar(value=str(today.day))
        day_spin = ttk.Spinbox(day_frame, from_=1, to=31, textvariable=day_var, width=10)
        day_spin.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        btn_frame = ttk.Frame(cal_window)
        btn_frame.pack(pady=20)
        
        def set_date():
            try:
                year = int(year_var.get())
                month = months.index(month_var.get()) + 1
                day = int(day_var.get())
                selected_date = date(year, month, day)
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, selected_date.strftime('%Y-%m-%d'))
                cal_window.destroy()
            except ValueError:
                messagebox.showerror("Invalid Date", "Please select a valid date.")
        
        def set_today():
            today = date.today()
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, today.strftime('%Y-%m-%d'))
            cal_window.destroy()
        
        ttk.Button(btn_frame, text="Set Date", command=set_date).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Today", command=set_today).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=cal_window.destroy).pack(side=tk.LEFT, padx=5)
    
    def test_api_connection(self):
        """Test connection to PMSI API"""
        try:
            response = requests.get(f"{self.api_base_url}/pms-manage?action=list&file_path=", timeout=5)
            return response.status_code == 200
        except:
            return False

def main():
    root = tk.Tk()
    app = PMSIDataUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()