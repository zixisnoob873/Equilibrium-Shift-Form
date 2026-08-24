import sys
import os
import json
import hashlib
import secrets
import time
import logging
import re
from shutil import copy2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_talisman import Talisman
import threading
from datetime import datetime, timedelta
from config import APP_NAME, APP_VERSION, EMPLOYEES as DEFAULT_EMPLOYEES, INVENTORY_ITEMS as DEFAULT_INVENTORY, PACKAGES as DEFAULT_PACKAGES, DEFAULT_PS5_PRICING, DEFAULT_TOTAL_PCS, LOCAL_DATA_DIR, UPLOAD_DIR, SCREENSHOTS_DIR, PANCAFE_SCREENSHOTS_DIR, FORM_SCREENSHOTS_DIR, SHIFTS, detect_shift, get_current_date, get_current_day
from core.models import ShiftData, PackageEntry, PS5Session, InventoryItem, ExpenseEntry
from core.shift_manager import ShiftManager
from core.local_cache import save_shift, get_last_closed_shift, get_last_shift, get_last_active_shift, get_all_shifts, load_shift, log_shift_access, get_shift_access_logs, get_recent_closed_shift_ids
from core.google_sheets import SUMMARY_SHEET_NAME, TRANSACTIONS_SHEET_NAME
from core.analytics import compute_financial_stats

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]
app.config["WTF_CSRF_TIME_LIMIT"] = None
csrf = CSRFProtect(app)
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5000"]}})

csp = {
    "default-src": "'self'",
    "script-src": "'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net",
    "style-src": "'self' 'unsafe-inline' fonts.googleapis.com",
    "font-src": "fonts.gstatic.com",
    "img-src": "'self' data:",
    "connect-src": "'self'"
}
Talisman(app, content_security_policy=csp, force_https=False, strict_transport_security=False, session_cookie_secure=False)

# Quiet down werkzeug access logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Clean app logging — warnings only, no request noise
app.logger.handlers.clear()
app.logger.setLevel(logging.WARNING)

shift_manager = ShiftManager()

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

DEFAULT_ADMIN_USERS = ["Rafay", "Jahanzaib Khan"]
ADMIN_SESSION_TTL = 3600  # 1 hour
ADMIN_SESSIONS = {}  # token -> {"name": str, "created_at": float}

FAILED_ATTEMPTS = {}  # ip -> [timestamp, ...]
MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW = 900  # 15 minutes


def _check_rate_limit(ip):
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(ip, [])
    attempts = [t for t in attempts if now - t < FAILED_WINDOW]
    FAILED_ATTEMPTS[ip] = attempts
    return len(attempts) < MAX_FAILED_ATTEMPTS


def _record_failed_attempt(ip):
    FAILED_ATTEMPTS.setdefault(ip, []).append(time.time())


def _constant_time_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def _hash_pin(pin: str) -> str:
    return generate_password_hash(pin, method="pbkdf2:sha256")


def _verify_pin(pin: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        return check_password_hash(stored, pin)
    except ValueError:
        return False


def _values_equal(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _get_admin_token():
    return request.headers.get("X-Admin-Token", "")


def _require_admin():
    token = _get_admin_token()
    if not token or token not in ADMIN_SESSIONS:
        return None
    session = ADMIN_SESSIONS[token]
    if time.time() - session["created_at"] > ADMIN_SESSION_TTL:
        del ADMIN_SESSIONS[token]
        return None
    return session["name"]


def _create_admin_session(name):
    for t in list(ADMIN_SESSIONS.keys()):
        if ADMIN_SESSIONS[t]["name"] == name:
            del ADMIN_SESSIONS[t]
    token = secrets.token_hex(32)
    ADMIN_SESSIONS[token] = {"name": name, "created_at": time.time()}
    return token


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Warning: settings.json corrupted ({e}), using defaults")
            return {"employees": DEFAULT_EMPLOYEES[:], "inventory_items": DEFAULT_INVENTORY[:], "packages": DEFAULT_PACKAGES[:], "ps5_pricing": DEFAULT_PS5_PRICING.copy(), "ps5_numbers": ["Left", "Right", "PC"], "total_pcs": DEFAULT_TOTAL_PCS, "employee_pins": {}}
        if "packages" not in data:
            data["packages"] = DEFAULT_PACKAGES[:]
            save_settings(data)
        if "ps5_pricing" not in data:
            data["ps5_pricing"] = DEFAULT_PS5_PRICING.copy()
            save_settings(data)
        else:
            # Ensure all default keys exist (for new keys like ps5_pc_rate)
            merged = DEFAULT_PS5_PRICING.copy()
            merged.update(data["ps5_pricing"])
            if merged != data["ps5_pricing"]:
                data["ps5_pricing"] = merged
                save_settings(data)
        if "ps5_numbers" not in data:
            data["ps5_numbers"] = ["Left", "Right", "PC"]
            save_settings(data)
        if "employee_pins" not in data:
            data["employee_pins"] = {}
            save_settings(data)
        if "total_pcs" not in data:
            data["total_pcs"] = DEFAULT_TOTAL_PCS
            save_settings(data)
        return data
    return {"employees": DEFAULT_EMPLOYEES[:], "inventory_items": DEFAULT_INVENTORY[:], "packages": DEFAULT_PACKAGES[:], "ps5_pricing": DEFAULT_PS5_PRICING.copy(), "ps5_numbers": ["Left", "Right", "PC"], "total_pcs": DEFAULT_TOTAL_PCS, "employee_pins": {}}


def get_admin_users():
    settings = load_settings()
    return settings.get("admin_users", DEFAULT_ADMIN_USERS[:])


def save_settings(data):
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(SETTINGS_FILE))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except:
        os.unlink(tmp)
        raise


def _lookup_package_by_amount(amount):
    """Look up package hz/hrs from settings by matching price."""
    settings = load_settings()
    for pkg in settings.get("packages", []):
        if pkg.get("price") == amount:
            return pkg.get("hz", ""), pkg.get("hrs", "")
    return "", ""


def get_effective_config():
    settings = load_settings()
    return {
        "employees": settings["employees"],
        "inventory_items": settings["inventory_items"],
        "packages": settings.get("packages", DEFAULT_PACKAGES[:]),
        "ps5_pricing": settings.get("ps5_pricing", DEFAULT_PS5_PRICING.copy()),
        "ps5_numbers": settings.get("ps5_numbers", ["Left", "Right", "PC"]),
        "total_pcs": settings.get("total_pcs", DEFAULT_TOTAL_PCS)
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    from config import APP_VERSION
    return jsonify({"status": "ok", "version": APP_VERSION})


@app.route("/api/config")
def get_config():
    shift_name, shift_timing = detect_shift()
    cfg = get_effective_config()
    return jsonify({
        "employees": cfg["employees"],
        "inventory_items": cfg["inventory_items"],
        "packages": cfg["packages"],
        "ps5_pricing": cfg["ps5_pricing"],
        "ps5_numbers": cfg["ps5_numbers"],
        "total_pcs": cfg["total_pcs"],
        "shifts": {k: f"{v[0]}:00 - {v[1]}:00" for k, v in SHIFTS.items()},
        "current_shift": shift_name,
        "current_timing": shift_timing,
        "current_date": get_current_date(),
        "current_day": get_current_day()
    })


@app.route("/api/session")
def get_session():
    last_closed = get_last_closed_shift()
    last = get_last_shift()
    active = shift_manager.current_shift
    orphaned = None
    if active is None:
        orphaned = get_last_active_shift()
    session_info = {
        "has_active_session": active is not None,
        "active_shift": active.to_dict() if active else None,
        "orphaned_shift": orphaned.to_dict() if orphaned else None,
        "last_closed_shift": last_closed.to_dict() if last_closed else None,
        "last_shift": last.to_dict() if last else None,

    }
    return jsonify(session_info)


@app.route("/api/shift/start", methods=["POST"])
def start_shift():
    data = request.get_json()
    employee_name = data.get("employee_name", "").strip()
    if not employee_name:
        return jsonify({"success": False, "error": "Employee name required"}), 400

    existing = shift_manager.current_shift or get_last_active_shift()
    if existing:
        return jsonify({
            "success": False,
            "error": f"A shift by {existing.employee_name} is already active. Close it before starting a new one."
        }), 409

    cfg = get_effective_config()
    shift = shift_manager.start_new_shift(employee_name)
    shift.inventory_items_snapshot = cfg["inventory_items"][:]

    last = get_last_closed_shift()
    closing_map = {}
    if last and last.inventory:
        for item in last.inventory:
            if isinstance(item, InventoryItem):
                closing_map[item.name] = item.closing_stock
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                closing_map[item[0]] = int(item[3]) if item[3] is not None else 0
            elif isinstance(item, dict):
                closing_map[item.get("name", "")] = int(item.get("closing_stock", 0))

    shift.inventory = [
        InventoryItem(
            name=item_name,
            opening_stock=closing_map.get(item_name, 0),
            restock_qty=0,
            closing_stock=0
        )
        for item_name in shift.inventory_items_snapshot
    ]

    save_shift(shift)
    return jsonify({"success": True, "shift": shift.to_dict(), "last_shift": last.to_dict() if last else None})





@app.route("/api/shift/close", methods=["POST"])
def close_shift():
    data = request.get_json()
    shift_data = data.get("shift", {})
    if not shift_data:
        return jsonify({"success": False, "error": "No shift data provided"}), 400

    shift_id = shift_data.get("shift_id", "")
    if not shift_id:
        return jsonify({"success": False, "error": "Shift ID is required. Start a shift first."}), 400
    employee_name = shift_data.get("employee_name", "")
    if not employee_name:
        return jsonify({"success": False, "error": "Employee name is required"}), 400

    # Verify this is the currently active shift
    active = shift_manager.current_shift or get_last_active_shift()
    if not active or active.shift_id != shift_id:
        return jsonify({"success": False, "error": "Cannot close this shift. No active shift found with this ID."}), 409

    # Idempotency check — don't close if already closed
    existing = load_shift(shift_id)
    if existing and existing.status in ("closed",):
        return jsonify({"success": False, "error": "Shift already closed"}), 409

    # Double-close race prevention
    if shift_manager.is_closing(shift_id):
        return jsonify({"success": False, "error": "Shift is already being closed"}), 429
    shift_manager.mark_closing(shift_id)

    try:
        shift = ShiftData()
        shift.shift_id = shift_id
        shift.employee_name = shift_data.get("employee_name", "")
        shift.date = shift_data.get("date", get_current_date())
        shift.day = shift_data.get("day", get_current_day())
        shift.shift_name = shift_data.get("shift_name", "")
        shift.shift_timing = shift_data.get("shift_timing", "")

        fin = shift_data.get("financial_summary", {})
        shift.topup_sale = max(0, float(fin.get("topup", 0)))
        shift.cafeteria_sale = max(0, float(fin.get("cafeteria", 0)))
        shift.morning_pkg_total = max(0, float(fin.get("morning_pkg", 0)))
        shift.nighter_pkg_total = max(0, float(fin.get("nighter_pkg", 0)))
        shift.ps5_total = max(0, float(fin.get("ps_sale", 0)))
        shift.total_expenses = max(0, float(fin.get("total_expenses", 0)))
        shift.grand_total = max(0, float(fin.get("grand_total", 0)))
        shift.cash_received = max(0, float(fin.get("cash_received", 0)))
        shift.online_payments = max(0, float(fin.get("online_payments", 0)))
        shift.actual_pos_amount = max(0, float(fin.get("actual_pos_amount", 0)))
        shift.total_tax_amount = max(0, float(fin.get("total_tax_amount", 0)))

        for pkg in shift_data.get("morning_packages", []):
            amt = float(pkg.get("amount", 0))
            hz = pkg.get("hz", "")
            hrs = pkg.get("hrs", "")
            if not hz or not hrs:
                hz, hrs = _lookup_package_by_amount(amt)
            shift.morning_packages.append(PackageEntry(pkg.get("pc_name", ""), amt, hz, hrs))
        for pkg in shift_data.get("nighter_packages", []):
            amt = float(pkg.get("amount", 0))
            hz = pkg.get("hz", "")
            hrs = pkg.get("hrs", "")
            if not hz or not hrs:
                hz, hrs = _lookup_package_by_amount(amt)
            shift.nighter_packages.append(PackageEntry(pkg.get("pc_name", ""), amt, hz, hrs))
        for ses in shift_data.get("ps5_sessions", []):
            shift.ps5_sessions.append(PS5Session(
                ses.get("ps_number", ""), int(ses.get("controllers", 2)),
                ses.get("start_time", ""), ses.get("end_time", ""), float(ses.get("amount", 0)),
                int(ses.get("duration_hours", 1)),
                bool(ses.get("is_extended", False))
            ))
        for inv in shift_data.get("inventory", []):
            shift.inventory.append(InventoryItem(
                inv.get("name", ""),
                int(inv.get("opening_stock", 0)),
                int(inv.get("restock_qty", 0)),
                int(inv.get("closing_stock", 0))
            ))
        for exp in shift_data.get("expenses", []):
            shift.expenses.append(ExpenseEntry(exp.get("description", ""), float(exp.get("amount", 0))))

        shift.opened_at = shift_data.get("opened_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        shift.inventory_items_snapshot = shift_data.get("inventory_items_snapshot", [])
        shift.form_screenshot_filename = shift_data.get("form_screenshot_filename", shift.form_screenshot_filename)
        shift.pancafe_screenshot_filename = shift_data.get("pancafe_screenshot_filename", shift.pancafe_screenshot_filename)

        # Validate split payments match grand total minus expenses (net collectable)
        net_target = shift.grand_total - shift.total_expenses
        total_payment = shift.cash_received + shift.online_payments + shift.actual_pos_amount
        if abs(total_payment - net_target) > 0.01:
            return jsonify({
                "success": False,
                "error": f"Payment mismatch: Cash (PKR {shift.cash_received:,.2f}) + Online (PKR {shift.online_payments:,.2f}) + POS (PKR {shift.actual_pos_amount:,.2f}) = PKR {total_payment:,.2f} must equal Grand Total minus Expenses PKR {net_target:,.2f}"
            }), 400

        close_ok, sync_success, sync_message = shift_manager.close_shift(shift)
        shift_manager.current_shift = None

        response = {
            "success": True,
            "shift": shift.to_dict(),
            "sync_success": sync_success,
            "sync_message": sync_message,
            "message": f"Shift closed! Grand Total: PKR {shift.grand_total:,.2f}"
        }
        if not sync_success:
            response["warning"] = f"Saved locally but Google Sheets sync failed: {sync_message}"
        return jsonify(response)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shift_manager.unmark_closing(shift_id)


@app.route("/api/shift/auto-save", methods=["POST"])
def auto_save_shift():
    data = request.get_json()
    shift_data = data.get("shift", {})
    shift_id = shift_data.get("shift_id", "")
    if not shift_id:
        return jsonify({"success": False, "error": "No shift_id"}), 400

    shift = load_shift(shift_id)
    if not shift:
        return jsonify({"success": False, "error": "Shift not found"}), 404

    if shift.status != "active":
        return jsonify({"success": False, "error": "Shift is no longer active"}), 409

    # Reject stale data: client last_modified must be >= server value
    client_modified = float(shift_data.get("last_modified", 0))
    if client_modified < shift.last_modified:
        return jsonify({
            "success": False,
            "error": "Stale data rejected. Another tab has more recent changes."
        }), 409

    try:
        fin = shift_data.get("financial_summary", {})
        shift.topup_sale = float(fin.get("topup", shift.topup_sale))
        shift.cafeteria_sale = float(fin.get("cafeteria", shift.cafeteria_sale))
        shift.morning_pkg_total = float(fin.get("morning_pkg", shift.morning_pkg_total))
        shift.nighter_pkg_total = float(fin.get("nighter_pkg", shift.nighter_pkg_total))
        shift.ps5_total = float(fin.get("ps_sale", shift.ps5_total))
        shift.total_expenses = float(fin.get("total_expenses", shift.total_expenses))
        shift.grand_total = float(fin.get("grand_total", shift.grand_total))
        shift.cash_received = float(fin.get("cash_received", shift.cash_received))
        shift.online_payments = float(fin.get("online_payments", shift.online_payments))
        shift.actual_pos_amount = float(fin.get("actual_pos_amount", shift.actual_pos_amount))
        shift.total_tax_amount = float(fin.get("total_tax_amount", shift.total_tax_amount))
        shift.morning_packages = []
        for pkg in shift_data.get("morning_packages", []):
            amt = float(pkg.get("amount", 0))
            hz = pkg.get("hz", "")
            hrs = pkg.get("hrs", "")
            if not hz or not hrs:
                hz, hrs = _lookup_package_by_amount(amt)
            shift.morning_packages.append(PackageEntry(pkg.get("pc_name", ""), amt, hz, hrs))
        shift.nighter_packages = []
        for pkg in shift_data.get("nighter_packages", []):
            amt = float(pkg.get("amount", 0))
            hz = pkg.get("hz", "")
            hrs = pkg.get("hrs", "")
            if not hz or not hrs:
                hz, hrs = _lookup_package_by_amount(amt)
            shift.nighter_packages.append(PackageEntry(pkg.get("pc_name", ""), amt, hz, hrs))
        shift.ps5_sessions = [PS5Session(ses.get("ps_number", ""), int(ses.get("controllers", 2)), ses.get("start_time", ""), ses.get("end_time", ""), float(ses.get("amount", 0)), int(ses.get("duration_hours", 1)), bool(ses.get("is_extended", False))) for ses in shift_data.get("ps5_sessions", [])]
        shift.inventory = [InventoryItem(inv.get("name", ""), int(inv.get("opening_stock", 0)), int(inv.get("restock_qty", 0)), int(inv.get("closing_stock", 0))) for inv in shift_data.get("inventory", [])]
        shift.expenses = [ExpenseEntry(exp.get("description", ""), float(exp.get("amount", 0))) for exp in shift_data.get("expenses", [])]
        shift.opened_at = shift_data.get("opened_at", shift.opened_at)
        shift.inventory_items_snapshot = shift_data.get("inventory_items_snapshot", shift.inventory_items_snapshot)
        shift.form_screenshot_filename = shift_data.get("form_screenshot_filename", shift.form_screenshot_filename)
        shift.pancafe_screenshot_filename = shift_data.get("pancafe_screenshot_filename", shift.pancafe_screenshot_filename)
        save_shift(shift)
        if shift_manager.current_shift and shift_manager.current_shift.shift_id == shift.shift_id:
            for field in ("topup_sale", "cafeteria_sale", "morning_pkg_total", "nighter_pkg_total", "ps5_total", "total_expenses", "grand_total", "cash_received", "online_payments", "actual_pos_amount", "total_tax_amount", "form_screenshot_filename", "pancafe_screenshot_filename"):
                setattr(shift_manager.current_shift, field, getattr(shift, field))
            shift_manager.current_shift.morning_packages = shift.morning_packages
            shift_manager.current_shift.nighter_packages = shift.nighter_packages
            shift_manager.current_shift.ps5_sessions = shift.ps5_sessions
            shift_manager.current_shift.inventory = shift.inventory
            shift_manager.current_shift.expenses = shift.expenses
            shift_manager.current_shift.inventory_items_snapshot = shift.inventory_items_snapshot
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/shift/last-closed")
def last_closed():
    shift = get_last_closed_shift()
    if shift:
        return jsonify({"success": True, "shift": shift.to_dict()})
    return jsonify({"success": False, "error": "No previous shifts found"})


@app.route("/api/shifts/history")
def shifts_history():
    all_shifts = get_all_shifts()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    total = len(all_shifts)
    start = (page - 1) * per_page
    end = start + per_page
    page_shifts = all_shifts[start:end]
    return jsonify({
        "success": True,
        "shifts": [s.to_dict() for s in page_shifts],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": end < total
    })


@app.route("/api/shifts/<shift_id>")
def get_shift(shift_id):
    try:
        shift = load_shift(shift_id)
        if not shift:
            return jsonify({"success": False, "error": "Shift not found"}), 404
        if shift.status == "closed" and _require_admin() is None:
            return jsonify({"success": False, "error": "Admin auth required"}), 401
        return jsonify({"success": True, "shift": shift.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to load shift: {str(e)}"}), 500


@app.route("/api/shifts/<shift_id>/view", methods=["POST"])
def view_shift_detail(shift_id):
    try:
        shift = load_shift(shift_id)
        if not shift:
            return jsonify({"success": False, "error": "Shift not found"}), 404

        if shift.status != "closed":
            return jsonify({"success": True, "shift": shift.to_dict()})

        ip = request.remote_addr or "unknown"
        admin_user = _require_admin()
        data = request.get_json(silent=True) or {}
        user_name = data.get("user_name", "").strip()
        pin = data.get("pin", "")

        # 1. Authenticated admin via active token
        if admin_user:
            log_shift_access(
                shift_id=shift.shift_id,
                accessor_name=admin_user,
                role="admin",
                shift_date=shift.date or "",
                shift_employee=shift.employee_name or "",
                ip=ip,
            )
            return jsonify({"success": True, "shift": shift.to_dict(), "role": "admin"})

        if not user_name:
            return jsonify({"success": False, "error": "Name required"}), 400

        if not pin:
            return jsonify({"success": False, "error": "PIN required"}), 400

        if not _check_rate_limit(ip):
            return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429

        settings = load_settings()

        # 2. Admin logging in via PIN
        if user_name in get_admin_users():
            pins = settings.get("admin_pins", {})
            stored = pins.get(user_name, "")
            if not stored or not _verify_pin(pin, stored):
                _record_failed_attempt(ip)
                return jsonify({"success": False, "error": "Invalid Admin PIN"}), 401
            token = _create_admin_session(user_name)
            log_shift_access(
                shift_id=shift.shift_id,
                accessor_name=user_name,
                role="admin",
                shift_date=shift.date or "",
                shift_employee=shift.employee_name or "",
                ip=ip,
            )
            return jsonify({
                "success": True,
                "shift": shift.to_dict(),
                "role": "admin",
                "token": token,
                "user_name": user_name,
            })

        # 3. Employee logging in via PIN
        employees = settings.get("employees", [])
        if user_name not in employees:
            return jsonify({"success": False, "error": "User not recognized"}), 403

        # Enforce 2 recent closed shifts restriction for employees
        recent_2 = get_recent_closed_shift_ids(limit=2)
        if shift.shift_id not in recent_2:
            return jsonify({
                "success": False,
                "error": "Only the 2 most recent shifts can be viewed by employees. Admin authorization required."
            }), 403

        pins = settings.get("employee_pins", {})
        stored = pins.get(user_name, "")
        if not stored or not _verify_pin(pin, stored):
            _record_failed_attempt(ip)
            return jsonify({"success": False, "error": "Invalid Employee PIN"}), 401

        log_shift_access(
            shift_id=shift.shift_id,
            accessor_name=user_name,
            role="employee",
            shift_date=shift.date or "",
            shift_employee=shift.employee_name or "",
            ip=ip,
        )
        return jsonify({"success": True, "shift": shift.to_dict(), "role": "employee", "user_name": user_name})

    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to load shift: {str(e)}"}), 500


@app.route("/api/admin/audit-logs", methods=["GET"])
def admin_audit_logs():
    admin = _require_admin()
    if admin is None:
        return jsonify({"success": False, "error": "Admin auth required"}), 401
    if admin not in get_admin_users():
        return jsonify({"success": False, "error": "Access restricted to owners"}), 403
    return jsonify({"success": True, "logs": get_shift_access_logs(limit=100)})


@app.route("/api/admin/financial-stats", methods=["GET"])
def admin_financial_stats():
    admin = _require_admin()
    if admin is None:
        return jsonify({"success": False, "error": "Admin auth required"}), 401

    start_date = request.args.get("start_date", "").strip() or None
    end_date = request.args.get("end_date", "").strip() or None
    shift_name = request.args.get("shift_name", "").strip() or None
    employee_name = request.args.get("employee_name", "").strip() or None

    all_shifts = get_all_shifts()
    settings = load_settings()
    ps5_numbers = settings.get("ps5_numbers", ["1", "2", "3", "PC"])

    stats = compute_financial_stats(
        all_shifts,
        start_date=start_date,
        end_date=end_date,
        shift_name=shift_name,
        employee_name=employee_name,
        valid_ps_numbers=ps5_numbers
    )
    return jsonify({"success": True, "admin": admin, "stats": stats})



def _values_equal(val_a, val_b):
    if val_a == val_b:
        return True
    if val_a is None or val_b is None:
        return False
    if isinstance(val_a, dict) and isinstance(val_b, dict):
        all_keys = set(val_a.keys()) | set(val_b.keys())
        for k in all_keys:
            va = val_a.get(k)
            vb = val_b.get(k)
            try:
                if float(va) != float(vb):
                    return False
            except (TypeError, ValueError):
                if va != vb:
                    return False
        return True
    if isinstance(val_a, list) and isinstance(val_b, list):
        if len(val_a) != len(val_b):
            return False
        for item_a, item_b in zip(val_a, val_b):
            if not _values_equal(item_a, item_b):
                return False
        return True
    try:
        if float(val_a) == float(val_b):
            return True
    except (TypeError, ValueError):
        pass
    return False

RESTRICTED_KEYS = {"employees", "packages", "ps5_pricing", "ps5_numbers", "total_pcs"}

@app.route("/api/settings", methods=["GET", "POST"])
def handle_settings():
    if request.method == "GET":
        data = load_settings()
        data.pop("admin_pins", None)
        data.pop("employee_pins", None)
        return jsonify(data)
    data = request.get_json() or {}
    current = load_settings()
    restricted_changed = any(
        k in data and not _values_equal(data[k], current.get(k))
        for k in RESTRICTED_KEYS
    )
    if restricted_changed and _require_admin() is None:
        return jsonify({"success": False, "error": "Admin auth required"}), 401
    employees = data.get("employees", DEFAULT_EMPLOYEES)
    if not isinstance(employees, list) or not all(isinstance(e, str) for e in employees):
        return jsonify({"success": False, "error": "employees must be a list of strings"}), 400
    inventory_items = data.get("inventory_items", DEFAULT_INVENTORY)
    if not isinstance(inventory_items, list) or not all(isinstance(i, str) for i in inventory_items):
        return jsonify({"success": False, "error": "inventory_items must be a list of strings"}), 400
    packages = data.get("packages", DEFAULT_PACKAGES)
    if not isinstance(packages, list) or not all(isinstance(p, dict) and "hz" in p and "hrs" in p and "price" in p for p in packages):
        return jsonify({"success": False, "error": "packages must be a list of {hz, hrs, price} objects"}), 400
    ps5_pricing = data.get("ps5_pricing", DEFAULT_PS5_PRICING.copy())
    if not isinstance(ps5_pricing, dict):
        return jsonify({"success": False, "error": "ps5_pricing must be an object"}), 400
    required_keys = ["two_controllers_first_hour", "one_controller_first_hour", "two_controllers_extended", "one_controller_extended", "ps5_pc_rate"]
    if not all(k in ps5_pricing for k in required_keys):
        return jsonify({"success": False, "error": "ps5_pricing must contain all rate fields"}), 400
    for k in required_keys:
        try:
            ps5_pricing[k] = max(0, float(ps5_pricing[k]))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": f"ps5_pricing.{k} must be a number"}), 400
    ps5_numbers = data.get("ps5_numbers", [])
    if not isinstance(ps5_numbers, list) or not all(isinstance(n, str) for n in ps5_numbers):
        return jsonify({"success": False, "error": "ps5_numbers must be a list of strings"}), 400
    total_pcs = data.get("total_pcs", DEFAULT_TOTAL_PCS)
    try:
        total_pcs = int(float(total_pcs))
        total_pcs = max(1, min(500, total_pcs))
    except (TypeError, ValueError):
        total_pcs = DEFAULT_TOTAL_PCS
    current["employees"] = employees
    current["inventory_items"] = inventory_items
    current["packages"] = packages
    current["ps5_pricing"] = ps5_pricing
    current["ps5_numbers"] = ps5_numbers
    current["total_pcs"] = total_pcs
    save_settings(current)
    return jsonify({"success": True, "employees": employees, "inventory_items": inventory_items, "packages": packages, "ps5_pricing": ps5_pricing, "ps5_numbers": ps5_numbers, "total_pcs": total_pcs})


@app.route("/api/admin/pin-status", methods=["POST"])
def admin_pin_status():
    data = request.get_json()
    name = data.get("employee_name", "").strip()
    if name not in get_admin_users():
        return jsonify({"success": False, "error": "Not an admin user"}), 403
    settings = load_settings()
    pins = settings.get("admin_pins", {})
    return jsonify({"success": True, "has_pin": name in pins})


@app.route("/api/admin/set-pin", methods=["POST"])
def admin_set_pin():
    data = request.get_json()
    name = data.get("employee_name", "").strip()
    pin = data.get("pin", "")
    if name not in get_admin_users():
        return jsonify({"success": False, "error": "Not an admin user"}), 403
    if len(pin) < 4 or len(pin) > 20 or not pin.isdigit():
        return jsonify({"success": False, "error": "PIN must be 4-20 digits"}), 400
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429
    settings = load_settings()
    pins = settings.get("admin_pins", {})
    if name in pins:
        return jsonify({"success": False, "error": "PIN already set. Use verify instead."}), 409
    pins[name] = _hash_pin(pin)
    settings["admin_pins"] = pins
    save_settings(settings)
    token = _create_admin_session(name)
    return jsonify({"success": True, "token": token, "employee_name": name})


@app.route("/api/admin/session", methods=["GET"])
def admin_session():
    admin = _require_admin()
    if admin is None:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    return jsonify({"success": True, "employee_name": admin, "authenticated": True})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    token = _get_admin_token()
    if token and token in ADMIN_SESSIONS:
        del ADMIN_SESSIONS[token]
    return jsonify({"success": True, "message": "Admin session logged out"})


@app.route("/api/admin/verify-pin", methods=["POST"])
def admin_verify_pin():
    data = request.get_json()
    name = data.get("employee_name", "").strip()
    pin = data.get("pin", "")
    if name not in get_admin_users():
        return jsonify({"success": False, "error": "Not an admin user"}), 403
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429
    settings = load_settings()
    pins = settings.get("admin_pins", {})
    stored = pins.get(name, "")
    if not _verify_pin(pin, stored):
        _record_failed_attempt(ip)
        return jsonify({"success": False, "error": "Invalid PIN"}), 401
    token = _create_admin_session(name)
    return jsonify({"success": True, "token": token, "employee_name": name})


@app.route("/api/employee/pin-status", methods=["GET"])
def employee_pin_status():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "error": "Employee name required"}), 400
    settings = load_settings()
    pins = settings.get("employee_pins", {})
    return jsonify({"success": True, "has_pin": name in pins})


@app.route("/api/employee/set-pin", methods=["POST"])
def employee_set_pin():
    data = request.get_json()
    name = data.get("employee_name", "").strip()
    pin = data.get("pin", "")
    if not name:
        return jsonify({"success": False, "error": "Employee name required"}), 400
    settings = load_settings()
    if name not in settings.get("employees", []):
        return jsonify({"success": False, "error": "Employee not found"}), 404
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429
    if len(pin) < 4 or len(pin) > 20 or not pin.isdigit():
        return jsonify({"success": False, "error": "PIN must be 4-20 digits"}), 400
    pins = settings.get("employee_pins", {})
    if name in pins:
        return jsonify({"success": False, "error": "PIN already set"}), 409
    pins[name] = _hash_pin(pin)
    settings["employee_pins"] = pins
    save_settings(settings)
    return jsonify({"success": True, "message": "PIN set successfully"})


@app.route("/api/employee/verify-pin", methods=["POST"])
def employee_verify_pin():
    data = request.get_json()
    name = data.get("employee_name", "").strip()
    pin = data.get("pin", "")
    if not name:
        return jsonify({"success": False, "error": "Employee name required"}), 400
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429
    settings = load_settings()
    pins = settings.get("employee_pins", {})
    stored = pins.get(name, "")
    if not _verify_pin(pin, stored):
        _record_failed_attempt(ip)
        return jsonify({"success": False, "error": "Invalid PIN"}), 401
    return jsonify({"success": True, "message": "PIN verified"})


@app.route("/api/admin/reset-employee-pin", methods=["POST"])
def admin_reset_employee_pin():
    data = request.get_json()
    admin_name = data.get("admin_name", "").strip()
    admin_pin = data.get("admin_pin", "")
    employee_name = data.get("employee_name", "").strip()
    new_pin = data.get("new_pin", "")

    if admin_name not in get_admin_users():
        return jsonify({"success": False, "error": "Not an admin user"}), 403
    if not employee_name:
        return jsonify({"success": False, "error": "Employee name required"}), 400
    if len(new_pin) < 4 or len(new_pin) > 20 or not new_pin.isdigit():
        return jsonify({"success": False, "error": "New PIN must be 4-20 digits"}), 400

    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429

    settings = load_settings()
    admin_pins = settings.get("admin_pins", {})
    if not _verify_pin(admin_pin, admin_pins.get(admin_name, "")):
        _record_failed_attempt(ip)
        return jsonify({"success": False, "error": "Invalid admin PIN"}), 401

    employee_pins = settings.get("employee_pins", {})
    employee_pins[employee_name] = _hash_pin(new_pin)
    settings["employee_pins"] = employee_pins
    save_settings(settings)
    return jsonify({"success": True, "message": f"PIN for {employee_name} has been reset"})


@app.route("/api/upload-screenshot", methods=["POST"])
def upload_screenshot():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file provided"}), 400
    file = request.files["image"]
    if not file.filename:
        return jsonify({"success": False, "error": "Empty filename"}), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    MAX_SIZE = 20 * 1024 * 1024
    if size > MAX_SIZE:
        return jsonify({"success": False, "error": "File too large. Maximum 20MB."}), 400
    if size < 4:
        return jsonify({"success": False, "error": "File too small"}), 400
    header = file.read(12)
    file.seek(0)
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        ext = ".png"
    elif header[:2] in (b'\xff\xd8',):
        ext = ".jpg"
    elif header[:6] in (b'GIF87a', b'GIF89a'):
        ext = ".gif"
    elif header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        ext = ".webp"
    elif header[:2] == b'BM':
        ext = ".bmp"
    else:
        return jsonify({"success": False, "error": "Invalid image format. Only PNG, JPEG, GIF, WebP, BMP accepted."}), 400
    img_type = request.form.get("type", "pancafe")
    shift_id = request.form.get("shift_id", "").strip()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{shift_id}_{uuid.uuid4().hex}{ext}" if shift_id else f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            img.verify()
    except Exception:
        os.remove(filepath)
        return jsonify({"success": False, "error": "Invalid or corrupted image file"}), 400

    try:
        dest_dir = PANCAFE_SCREENSHOTS_DIR if img_type == "pancafe" else FORM_SCREENSHOTS_DIR
        os.makedirs(dest_dir, exist_ok=True)
        if shift_id:
            shift = load_shift(shift_id)
            if shift:
                safe_name = re.sub(r'[^\w\-]', '_', shift.employee_name)
                copy_name = f"{shift.date}_{safe_name}{ext}"
            else:
                copy_name = f"{shift_id}{ext}"
        else:
            copy_name = f"unknown{ext}"
        copy2(filepath, os.path.join(dest_dir, copy_name))
    except Exception:
        pass

    return jsonify({"success": True, "filename": filename, "type": img_type})


@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory("assets", filename)


@app.route("/api/sheets/status")
def sheets_status():
    ready = shift_manager.sheets.is_ready()
    return jsonify({"configured": ready})


_ALARMS_LOCK = threading.Lock()
PENDING_ALARMS_FILE = os.path.join(LOCAL_DATA_DIR, "pending_alarms.json")

def _load_pending_alarms():
    if not os.path.exists(PENDING_ALARMS_FILE):
        return []
    try:
        with open(PENDING_ALARMS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save_pending_alarms(alarms):
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=LOCAL_DATA_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(alarms, f, indent=2)
        os.replace(tmp, PENDING_ALARMS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

@app.route("/api/alarms/schedule", methods=["POST"])
def schedule_alarms():
    data = request.get_json() or {}
    incoming = data.get("sessions", [])
    now = datetime.now()
    cutoff_24h = (now - timedelta(hours=24)).timestamp() * 1000
    cutoff_7d = (now - timedelta(days=7)).timestamp() * 1000

    with _ALARMS_LOCK:
        existing = _load_pending_alarms()
        alarm_map = {a["id"]: a for a in existing}

        for s in incoming:
            sid = s.get("id")
            if not sid:
                continue
            end_ts = s.get("endTs", 0)
            end_dt = datetime.fromtimestamp(end_ts / 1000.0) if end_ts else now
            if sid in alarm_map:
                alarm_map[sid]["end_timestamp"] = end_dt.isoformat()
                alarm_map[sid]["end_ts"] = end_ts
                alarm_map[sid]["endTotalMin"] = s.get("endTotalMin", 0)
                alarm_map[sid]["psNumber"] = s.get("psNumber", "")
            else:
                alarm_map[sid] = {
                    "id": sid,
                    "psNumber": s.get("psNumber", ""),
                    "end_timestamp": end_dt.isoformat(),
                    "end_ts": end_ts,
                    "endTotalMin": s.get("endTotalMin", 0),
                    "acknowledged": False
                }

        # GC: drop only acknowledged alarms older than 24h, or never acked older than 7d
        cleaned = []
        for a in alarm_map.values():
            ts = a.get("end_ts", 0)
            if a.get("acknowledged", False):
                if ts >= cutoff_24h:
                    cleaned.append(a)
            else:
                if ts >= cutoff_7d:
                    cleaned.append(a)

        _save_pending_alarms(cleaned)
    return jsonify({"success": True, "count": len(cleaned)})

@app.route("/api/alarms/pending", methods=["GET"])
def get_pending_alarms():
    now_ms = datetime.now().timestamp() * 1000
    with _ALARMS_LOCK:
        alarms = _load_pending_alarms()
        pending = [a for a in alarms if not a.get("acknowledged", False) and a.get("end_ts", 0) <= now_ms]
    return jsonify({"success": True, "alarms": pending})

@app.route("/api/alarms/acknowledge", methods=["POST"])
def acknowledge_alarms():
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if isinstance(ids, str):
        ids = [ids]
    ids_set = set(ids)

    with _ALARMS_LOCK:
        alarms = _load_pending_alarms()
        for a in alarms:
            if a.get("id") in ids_set:
                a["acknowledged"] = True
        _save_pending_alarms(alarms)
    return jsonify({"success": True, "acknowledged": list(ids_set)})


@app.route("/api/sheets/sync-shift/<shift_id>", methods=["POST"])
def sync_one_shift(shift_id):
    shift = load_shift(shift_id)
    if not shift:
        return jsonify({"success": False, "error": "Shift not found"}), 404
    if shift.status not in ("closed",):
        return jsonify({"success": False, "error": "Only closed shifts can be synced"}), 400
    if shift.synced_to_sheets:
        return jsonify({"success": True, "message": f"Shift {shift_id} already synced"})

    try:
        sm = shift_manager.sheets
        sm._authenticate()
        wb = sm.client.open_by_key(sm.config.sheet_id)
        sm._ensure_sheets_exist(wb)
        sm._append_summary(wb, shift)
        sm._append_transactions(wb, shift)
        shift.synced_to_sheets = True
        save_shift(shift)
        return jsonify({"success": True, "message": f"Shift {shift_id} synced"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/screenshots/re-upload/<shift_id>", methods=["POST"])
def re_upload_screenshots(shift_id):
    shift = load_shift(shift_id)
    if not shift:
        return jsonify({"success": False, "error": "Shift not found"}), 404
    if shift.status not in ("closed",):
        return jsonify({"success": False, "error": "Only closed shifts can have screenshots re-uploaded"}), 400

    if not shift_manager.sheets.is_ready():
        return jsonify({"success": False, "error": "Google Sheets not configured"}), 400

    sm = shift_manager.sheets
    try:
        sm._authenticate()
        wb = sm.client.open_by_key(sm.config.sheet_id)
        sm._ensure_sheets_exist(wb)
        ws = wb.worksheet(SUMMARY_SHEET_NAME)

        existing_ids = ws.col_values(1)
        if shift.shift_id not in existing_ids:
            return jsonify({"success": False, "error": "Shift not found in the summary sheet. Sync the shift first."}), 404

        row_idx = existing_ids.index(shift.shift_id) + 1

        # Locate screenshot columns by the sheet's own header row instead of
        # hardcoding positions. _resolve_column_indices returns 0-based
        # offsets while gspread cell APIs are 1-based; sheets lacking those
        # headers (legacy layouts) fall back to their fixed cols 23/24.
        col_map = sm._resolve_column_indices(ws)
        pancafe_col = col_map.get("Pancafe Screenshot", 22) + 1
        form_col = col_map.get("Form Screenshot", 23) + 1

        warnings = []
        uploaded = 0
        final_urls = {}
        for label, filename, col in (
            ("Pancafe screenshot", shift.pancafe_screenshot_filename, pancafe_col),
            ("Form screenshot", shift.form_screenshot_filename, form_col),
        ):
            if not filename:
                warnings.append(f"{label}: no screenshot on record for this shift")
                final_urls[label] = ""
                continue
            try:
                current = ws.cell(row_idx, col).value or ""
            except Exception:
                current = ""
            if "ibb.co" in current or "imgbb.com" in current:
                final_urls[label] = current
                continue
            if not os.path.exists(os.path.join(UPLOAD_DIR, filename)):
                warnings.append(
                    f"{label}: file '{filename}' missing locally — cell left unchanged"
                )
                final_urls[label] = current
                continue
            url = sm._upload_to_imgbb(filename)
            if not url:
                warnings.append(f"{label}: upload returned no URL")
                final_urls[label] = current
                continue
            ws.update_cell(row_idx, col, url)
            uploaded += 1
            final_urls[label] = url
            if "ibb.co" not in url and "imgbb.com" not in url:
                warnings.append(
                    "ImgBB API key not configured (imgbb_key.txt) — stored local server link instead of imgbb.com"
                )

        return jsonify({
            "success": True,
            "skipped": uploaded == 0 and not warnings,
            "message": "Screenshots re-uploaded and sheet updated" if uploaded else "Nothing to re-upload",
            "pancafe_url": final_urls.get("Pancafe screenshot", ""),
            "form_url": final_urls.get("Form screenshot", ""),
            "warnings": warnings
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _sync_closed_shifts(sm, wb, skip_existing=True):
    from core.local_cache import get_all_shifts
    all_shifts = get_all_shifts()
    closed = [s for s in all_shifts if s.status in ("closed",)]
    if not closed:
        return {"synced": [], "skipped": [], "errors": []}

    existing_ids = set()
    existing_keys = set()
    if skip_existing:
        try:
            ws = wb.worksheet(SUMMARY_SHEET_NAME)
            rows = ws.get_all_values()
            if len(rows) > 1:
                header = rows[0]
                has_shift_id_col = len(header) > 0 and header[0] == "Shift ID"
                for row in rows[1:]:
                    if has_shift_id_col:
                        if row and len(row) > 0:
                            existing_ids.add(row[0])
                    else:
                        if row and len(row) >= 11:
                            total = round(float(row[10]), 2) if row[10] else "0"
                            key = f"{row[0]}|{row[3]}|{total}"
                            existing_keys.add(key)
        except Exception:
            pass

    results = {"synced": [], "skipped": [], "errors": []}
    for s in closed:
        if s.synced_to_sheets:
            results["skipped"].append(s.shift_id)
            continue
        if s.shift_id in existing_ids:
            if not s.synced_to_sheets:
                s.synced_to_sheets = True
                save_shift(s)
            results["skipped"].append(s.shift_id)
            continue
        key = f"{s.date}|{s.employee_name}|{round(s.grand_total, 2)}"
        if key in existing_keys:
            if not s.synced_to_sheets:
                s.synced_to_sheets = True
                save_shift(s)
            results["skipped"].append(s.shift_id)
            continue
        try:
            sm._append_summary(wb, s)
            sm._append_transactions(wb, s)
            s.synced_to_sheets = True
            save_shift(s)
            results["synced"].append(s.shift_id)
        except Exception as e:
            results["errors"].append({"shift": s.shift_id, "error": str(e)})
    return results


@app.route("/api/sync-errors")
def get_sync_errors():
    if _require_admin() is None:
        return jsonify({"success": False, "error": "Admin auth required"}), 401
    from core.local_cache import get_sync_errors
    return jsonify({"success": True, "errors": get_sync_errors()})


@app.route("/api/sheets/sync-all", methods=["POST"])
def sync_all_shifts():
    if not shift_manager.sheets.is_ready():
        return jsonify({"success": False, "error": "Google Sheets not configured"}), 400

    sm = shift_manager.sheets
    try:
        sm._authenticate()
        wb = sm.client.open_by_key(sm.config.sheet_id)
        sm._ensure_sheets_exist(wb)
    except Exception as e:
        return jsonify({"success": False, "error": f"Auth failed: {str(e)}"}), 500

    results = _sync_closed_shifts(sm, wb)
    return jsonify({
        "success": len(results["errors"]) == 0,
        "results": results,
        "message": f"Synced {len(results['synced'])}, skipped {len(results['skipped'])}, errors {len(results['errors'])}"
    })


def _startup_sync():
    try:
        if shift_manager.sheets.is_ready():
            sm = shift_manager.sheets
            sm._authenticate()
            wb = sm.client.open_by_key(sm.config.sheet_id)
            sm._ensure_sheets_exist(wb)
            results = _sync_closed_shifts(sm, wb, skip_existing=True)
            synced = len(results["synced"])
            if synced:
                print(f"  Synced {synced} unsynced shift(s) to Google Sheets")
    except Exception as e:
        print(f"  Note: Could not auto-sync shifts: {e}")


@app.route("/api/sheets/clear", methods=["POST"])
def clear_sheets():
    if not shift_manager.sheets.is_ready():
        return jsonify({"success": False, "error": "Google Sheets not configured"}), 400
    try:
        sm = shift_manager.sheets
        sm._authenticate()
        wb = sm.client.open_by_key(sm.config.sheet_id)
        ws1 = wb.worksheet("Shift Summary")
        ws2 = wb.worksheet(TRANSACTIONS_SHEET_NAME)
        ws1.clear()
        ws2.clear()
        ws1.append_row(["Shift ID", "Date", "Day", "Shift Timing",
            "Employee Name", "Topup Sale", "Morning Pkg Sale",
            "Nighter Pkg Sale", "PS5 Sale", "Cafeteria Sale",
            "Total Expenses", "Grand Total", "Cash Received",
            "Online Payments", "Actual POS Amount", "Total TAX Amount",
            "Morning Pkg Count", "Nighter Pkg Count",
            "PS5 Session Count", "Inventory", "Expenses",
            "Closed At", "Pancafe Screenshot", "Form Screenshot"])
        ws2.append_row(["Date", "Day", "Shift Name", "Employee",
            "Type", "Item / Notes", "Controllers", "Start Time",
            "End Time", "Duration (hrs)", "Amount (PKR)",
            "Cash Received", "Online Payments", "Timestamp"])
        return jsonify({"success": True, "message": "All shift data cleared from Google Sheets"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    import threading
    t = threading.Thread(target=_startup_sync, daemon=True)
    t.start()

    url = f"http://localhost:{port}"
    print()
    print("  " + "+" + "="*38 + "+")
    print("  |  " + "GAMING ZONE SHIFT MANAGEMENT".center(34) + "  |")
    print("  |  " + "".center(34) + "  |")
    print("  |  " + url.center(34) + "  |")
    print("  " + "+" + "="*38 + "+")
    print()

    try:
        import waitress
        waitress.serve(app, host="127.0.0.1", port=port)
    except ImportError:
        print("  └─ using Flask dev server")
        app.run(host="127.0.0.1", port=port, debug=debug)
