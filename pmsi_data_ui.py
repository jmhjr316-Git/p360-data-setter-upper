#!/usr/bin/env python3
"""
PMSI Simulator Data Management UI
A cross-platform GUI for managing PMSI simulator files and data.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
from datetime import datetime, date
from typing import Dict, Any
import requests
from urllib.parse import urlencode
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
            "Patient Information": {
                "patient_first_name": {"label": "Patient First Name", "type": "text", "required": True},
                "patient_last_name": {"label": "Patient Last Name", "type": "text", "required": True},
                "patient_dob": {"label": "Patient DOB (YYYY-MM-DD)", "type": "date", "required": True},
                "patient_phone": {"label": "Patient Phone", "type": "text", "required": True},
            },
            "Prescription Information": {
                "rx_status": {"label": "RX Status", "type": "dropdown", "options": ["Active", "Inactive", "Pending", "Expired"], "required": True},
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
        """Save current form data to JSON file"""
        data = self.get_form_data()
        is_valid, error_msg = self.validate_data(data)
        
        if not is_valid:
            messagebox.showerror("Validation Error", error_msg)
            return
        
        try:
            filename = f"pmsi_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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