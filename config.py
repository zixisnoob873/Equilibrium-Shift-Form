import os
from datetime import datetime

APP_NAME = "Gaming Zone Shift Management"
APP_VERSION = "2.0.0"

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

EMPLOYEES = [
    "Jahanzaib Khan", "Rafay"
]

INVENTORY_ITEMS = []

PACKAGES = []

SHIFTS = {
    "Morning":   (8, 16),
    "Evening":  (16, 24),
    "Night":    (0, 8)
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DATA_DIR = os.path.join(BASE_DIR, "local_data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
PANCAFE_SCREENSHOTS_DIR = os.path.join(SCREENSHOTS_DIR, "pancafe_screenshot")
FORM_SCREENSHOTS_DIR = os.path.join(SCREENSHOTS_DIR, "shift_form_screenshot")

DEFAULT_TOTAL_PCS = 27

DEFAULT_TOPUP_ACCOUNT = "Main Topup"

DEFAULT_PS5_PRICING = {
    "two_controllers_first_hour": 700,
    "one_controller_first_hour": 400,
    "two_controllers_extended": 500,
    "one_controller_extended": 300,
    "ps5_pc_rate": 250
}

def detect_shift():
    h = datetime.now().hour
    if 8 <= h < 16:
        return "Morning", "8:00 AM - 4:00 PM"
    elif 16 <= h < 24:
        return "Evening", "4:00 PM - 12:00 AM"
    else:
        return "Night", "12:00 AM - 8:00 AM"

def get_current_day():
    return datetime.now().strftime("%A")

def get_current_date():
    return datetime.now().strftime("%Y-%m-%d")
