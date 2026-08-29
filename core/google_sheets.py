import json
import os
import threading
from typing import Optional, Callable
from config import UPLOAD_DIR, BASE_URL
from .local_cache import save_shift

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(ROOT_DIR, "credentials.json")
SHEET_ID_FILE = os.path.join(ROOT_DIR, "sheet_id.txt")
IMGBB_KEY_FILE = os.path.join(ROOT_DIR, "imgbb_key.txt")

SUMMARY_SHEET_NAME = "Shift Summary"
TRANSACTIONS_SHEET_NAME = "Detailed Transactions"

# Single source of truth for the sheet headers. The create-on-missing path
# writes these, so a layout change is one edit here.
SUMMARY_HEADERS = [
    "Shift ID", "Date", "Day", "Shift Timing",
    "Employee Name", "Topup Sale", "Morning Pkg Sale",
    "Nighter Pkg Sale", "PS5 Sale", "Cafeteria Sale",
    "Total",
    "Online Payments", "Cash Received", "Actual POS Amount",
    "Total Payment Received",
    "Total Expenses",
    "Reconciliation",
    "Grand Total",
    "Total TAX Amount",
    "Morning Pkg Count", "Nighter Pkg Count", "PS5 Session Count",
    "Inventory", "Closed At",
    "Pancafe Screenshot", "Form Screenshot"
]

TRANSACTIONS_HEADERS = [
    "Date", "Day", "Shift Name", "Employee",
    "Type", "Item / Notes", "Controllers", "Start Time",
    "End Time", "Duration (hrs)", "Amount (PKR)",
    "Cash Received", "Online Payments", "Timestamp"
]


class SheetConfig:
    def __init__(self):
        self.credentials_path = CREDENTIALS_FILE
        self.sheet_id = ""
        self.imgbb_key = ""
        self._load_sheet_id()
        self._load_imgbb_key()

    def _load_sheet_id(self):
        if os.path.exists(SHEET_ID_FILE):
            with open(SHEET_ID_FILE) as f:
                self.sheet_id = f.read().strip()

    def save_sheet_id(self, sheet_id: str):
        self.sheet_id = sheet_id
        with open(SHEET_ID_FILE, "w") as f:
            f.write(sheet_id)

    def _load_imgbb_key(self):
        if os.path.exists(IMGBB_KEY_FILE):
            with open(IMGBB_KEY_FILE) as f:
                self.imgbb_key = f.read().strip()

    def is_configured(self):
        return bool(self.sheet_id) and os.path.exists(self.credentials_path)


class GoogleSheetsManager:
    def __init__(self):
        self.config = SheetConfig()
        self.client = None
        self.sheet = None
        # Serializes check-then-append dedup so concurrent syncs (background
        # close sync, startup sync, manual sync-all) can never duplicate rows.
        self._sync_lock = threading.Lock()

    def _authenticate(self):
        import gspread
        from google.oauth2.service_account import Credentials
        scope = ["https://spreadsheets.google.com/feeds"]
        self._creds = Credentials.from_service_account_file(
            self.config.credentials_path, scopes=scope
        )
        self.client = gspread.authorize(self._creds)

    def is_ready(self) -> bool:
        return self.config.is_configured()

    def sync_shift_sync(self, shift: ShiftData):
        try:
            if not self.is_ready():
                return (False, "Google Sheets not configured")
            if shift.synced_to_sheets:
                return (True, "Shift already synced to Google Sheets")
            self._authenticate()
            wb = self.client.open_by_key(self.config.sheet_id)
            self._ensure_sheets_exist(wb)
            self._append_summary(wb, shift)
            self._append_transactions(wb, shift)
            shift.synced_to_sheets = True
            save_shift(shift)
            return (True, "Shift synced to Google Sheets successfully!")
        except Exception as e:
            return (False, f"Google Sheets sync failed: {str(e)}")

    def sync_shift(self, shift: ShiftData, progress_callback: Optional[Callable] = None, done_callback: Optional[Callable] = None):
        def _sync():
            try:
                if not self.is_ready():
                    if done_callback:
                        done_callback(False, "Google Sheets not configured. Check credentials.json and sheet_id.txt")
                    return
                if shift.synced_to_sheets:
                    if done_callback:
                        done_callback(True, "Shift already synced to Google Sheets")
                    return
                if progress_callback:
                    progress_callback("Authenticating...")
                self._authenticate()
                wb = self.client.open_by_key(self.config.sheet_id)
                if progress_callback:
                    progress_callback("Opening sheets...")
                self._ensure_sheets_exist(wb)
                if progress_callback:
                    progress_callback("Appending summary row...")
                self._append_summary(wb, shift)
                if progress_callback:
                    progress_callback("Appending transactions...")
                self._append_transactions(wb, shift)
                shift.synced_to_sheets = True
                save_shift(shift)
                if done_callback:
                    done_callback(True, "Shift synced to Google Sheets successfully!")
            except Exception as e:
                if done_callback:
                    done_callback(False, f"Google Sheets sync failed: {str(e)}")
        threading.Thread(target=_sync, daemon=True).start()

    def _ensure_sheets_exist(self, wb):
        import gspread.exceptions
        try:
            wb.worksheet(SUMMARY_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = wb.add_worksheet(title=SUMMARY_SHEET_NAME, rows=1000, cols=len(SUMMARY_HEADERS))
            ws.append_row(SUMMARY_HEADERS[:])
        except gspread.exceptions.APIError as e:
            print(f"  Sheets API error checking summary sheet: {e}")
            raise
        try:
            wb.worksheet(TRANSACTIONS_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = wb.add_worksheet(title=TRANSACTIONS_SHEET_NAME, rows=1000, cols=len(TRANSACTIONS_HEADERS) + 1)
            ws.append_row(TRANSACTIONS_HEADERS[:])
        except gspread.exceptions.APIError as e:
            print(f"  Sheets API error checking transactions sheet: {e}")
            raise

    def _upload_to_imgbb(self, filename: str, errors: Optional[list] = None) -> str:
        """Upload a screenshot to ImgBB and return its URL. On any failure a
        local-server fallback URL is returned instead; when `errors` is a
        list, a human-readable reason is appended so callers can surface WHY
        the fresh upload failed instead of silently degrading."""
        def _reason(msg):
            if errors is not None:
                errors.append(msg)

        if not filename:
            _reason("no filename on record")
            return ""
        filepath = os.path.join(UPLOAD_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  Screenshot file not found: {filepath}")
            _reason(f"file '{filename}' not found in uploads/")
            return self._local_screenshot_url(filename)
        try:
            size = os.path.getsize(filepath)
            if size < 100:
                print(f"  Screenshot file too small ({size}b): {filepath}")
                _reason(f"file too small ({size} bytes)")
                return self._local_screenshot_url(filename)
        except OSError as e:
            print(f"  Screenshot file check error: {e}")
            _reason(f"file check error: {e}")
            return self._local_screenshot_url(filename)

        if not self.config.imgbb_key:
            print("  ImgBB: No API key configured, using local fallback")
            _reason("ImgBB API key not configured (imgbb_key.txt)")
            return self._local_screenshot_url(filename)

        try:
            import requests
            import base64
            with open(filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            resp = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": self.config.imgbb_key, "image": b64},
                timeout=30
            )
            data = resp.json()
            if data.get("success"):
                url = data["data"]["url"]
                print(f"  ImgBB: Uploaded {filename} -> {url}")
                return url
            else:
                err = data.get("error", {}).get("message", "unknown")
                print(f"  ImgBB: API error: {err}, using local fallback")
                _reason(f"API error: {err}")
                return self._local_screenshot_url(filename)
        except Exception as e:
            print(f"  ImgBB: Error uploading {filename}: {e}, using local fallback")
            _reason(f"network error: {e}")
            return self._local_screenshot_url(filename)

    def _local_screenshot_url(self, filename: str) -> str:
        return f"{BASE_URL}/uploads/{filename}"

    def _resolve_column_indices(self, ws):
        """Read the header row and return {col_name: index} mapping.
        Works with both old sheets (no Shift ID) and new sheets."""
        try:
            header = ws.row_values(1)
            mapping = {}
            for i, name in enumerate(header):
                mapping[name.strip()] = i
            return mapping
        except Exception:
            return {}

    def _insert_position(self, rows, date_idx, closed_idx, date_val, closed_val):
        """Physical 1-based sheet row where (date_val, closed_val) belongs so
        data stays ordered by (Date, Closed At). Row 1 is assumed to be the
        header (consistent with the rest of this module). Rows with an empty
        date are ignored as sort targets; equal keys insert after (stable).
        Returns None when the entry belongs at the end (caller appends)."""
        if rows is None or len(rows) < 2 or date_idx is None or closed_idx is None:
            return None
        key = ((date_val or "").strip(), (closed_val or "").strip())
        for i in range(1, len(rows)):
            row = rows[i]
            if not row or len(row) <= max(date_idx, closed_idx):
                continue
            r_date = (row[date_idx] or "").strip()
            if not r_date:
                continue
            if (r_date, (row[closed_idx] or "").strip()) > key:
                return i + 1
        return None

    def _ordered_insert_at(self, ws, rows, col_map, date_key, closed_key, date_fallback, closed_fallback):
        """Compute the ordered insert row for one sheet, or None to append.
        Falls back to append when the grid is full: values.append grows the
        grid automatically, an insert at full capacity would push the last
        row out of it."""
        date_idx = col_map.get("Date", date_fallback)
        closed_idx = col_map.get("Closed At", closed_fallback)
        if rows is None:
            try:
                rows = ws.get_all_values()
            except Exception:
                return None
        insert_at = self._insert_position(rows, date_idx, closed_idx, date_key, closed_key)
        if insert_at is None:
            return None
        row_count = getattr(ws, "row_count", None)
        if row_count and len(rows) >= row_count:
            return None
        return insert_at

    def _resolve_screenshot_url(self, shift: ShiftData, label: str):
        """Return the URL for a screenshot, reusing a previously stored one and
        only calling ImgBB when none exists yet. Persists any freshly obtained
        URL back onto the shift so re-syncs (Sync All, startup sync) never
        re-upload and never hit the ImgBB rate limit."""
        if label == "pancafe":
            filename = shift.pancafe_screenshot_filename
            stored = shift.pancafe_screenshot_url
        else:
            filename = shift.form_screenshot_filename
            stored = shift.form_screenshot_url
        if stored:
            return stored, False
        url = self._upload_to_imgbb(filename)
        if url:
            if label == "pancafe":
                shift.pancafe_screenshot_url = url
            else:
                shift.form_screenshot_url = url
            return url, True
        return url, False

    def _persist_screenshot_urls(self, shift: ShiftData, changed: bool):
        if changed:
            save_shift(shift)

    def _append_summary(self, wb, shift: ShiftData, ordered: bool = False):
        ws = wb.worksheet(SUMMARY_SHEET_NAME)

        pancafe_url, pancafe_changed = self._resolve_screenshot_url(shift, "pancafe")
        form_url, form_changed = self._resolve_screenshot_url(shift, "form")
        changed = pancafe_changed or form_changed

        # Dedup check + append run under a lock so the existence check and the
        # append are atomic — concurrent syncs can never double-append a shift.
        with self._sync_lock:
            col_map = self._resolve_column_indices(ws)

            # Primary dedup: check if shift_id already exists in column A
            try:
                existing_ids = ws.col_values(1)
                if shift.shift_id in existing_ids:
                    print(f"  Dedup: shift {shift.shift_id} already exists in sheet (UUID match), skipping")
                    self._persist_screenshot_urls(shift, changed)
                    return
            except Exception:
                pass

            # Fallback dedup: use header-aware column lookup so it works with
            # both old sheets (no Shift ID column) and new sheets. Also
            # compares closed_at when available so two legitimate same-day,
            # same-employee, same-total shifts are never confused.
            rows = None
            if col_map:
                date_idx = col_map.get("Date")
                emp_idx = col_map.get("Employee Name")
                total_idx = col_map.get("Grand Total")
                closed_idx = col_map.get("Closed At")
                if date_idx is not None and emp_idx is not None and total_idx is not None:
                    need_closed = closed_idx is not None and bool(shift.closed_at)
                    max_idx = max(date_idx, emp_idx, total_idx)
                    if need_closed:
                        max_idx = max(max_idx, closed_idx)
                    try:
                        rows = ws.get_all_values()
                        if len(rows) > 1:
                            for row in rows[1:]:
                                if row and len(row) > max_idx:
                                    sheet_total_str = row[total_idx]
                                    if sheet_total_str:
                                        try:
                                            sheet_total = round(float(sheet_total_str), 2)
                                        except (ValueError, TypeError):
                                            continue
                                        # "Grand Total" holds the net figure in new-layout sheets
                                        # (identified by the unique "Total
                                        # Payment Received" header), but the
                                        # legacy gross value in old sheets —
                                        # compare accordingly.
                                        if "Total Payment Received" in col_map:
                                            shift_total = round(shift.grand_total - shift.total_expenses, 2)
                                        else:
                                            shift_total = round(shift.grand_total, 2)
                                        if (sheet_total == shift_total and
                                            row[emp_idx] == shift.employee_name and
                                            row[date_idx] == shift.date):
                                            if need_closed and row[closed_idx] != shift.closed_at:
                                                continue
                                            print(f"  Dedup (fallback): shift {shift.shift_id} matched by date|employee|total")
                                            self._persist_screenshot_urls(shift, changed)
                                            return
                    except Exception:
                        pass

            # Ordered insertion (Re-Sync): position the shift's row by
            # (Date, Closed At) so a late-synced shift lands between its
            # chronological neighbours instead of at the bottom.
            # None => plain append (existing behaviour for all other paths).
            insert_at = None
            if ordered:
                insert_at = self._ordered_insert_at(
                    ws, rows, col_map, shift.date, shift.closed_at,
                    date_fallback=1, closed_fallback=23
                )

            inv_parts = [f"{i.name}: {i.closing_stock}" for i in shift.inventory]
            inv_str = ", ".join(inv_parts) if inv_parts else "None"

            total_sale = shift.grand_total
            total_payment = shift.cash_received + shift.online_payments + shift.actual_pos_amount
            reconciliation = total_sale - total_payment - shift.total_expenses
            grand_total_net = total_sale - shift.total_expenses

            summary_row = [
                shift.shift_id,
                shift.date, shift.day, shift.shift_timing,
                shift.employee_name, shift.topup_sale, shift.morning_pkg_total,
                shift.nighter_pkg_total, shift.ps5_total, shift.cafeteria_sale,
                total_sale,
                shift.online_payments, shift.cash_received, shift.actual_pos_amount,
                total_payment,
                shift.total_expenses,
                reconciliation,
                grand_total_net,
                shift.total_tax_amount,
                len(shift.morning_packages), len(shift.nighter_packages),
                len(shift.ps5_sessions), inv_str,
                shift.closed_at,
                pancafe_url,
                form_url
            ]
            if insert_at is None:
                ws.append_row(summary_row)
            else:
                ws.insert_row(summary_row, insert_at)
        self._persist_screenshot_urls(shift, changed)

    def _append_transactions(self, wb, shift: ShiftData, ordered: bool = False):
        ws = wb.worksheet(TRANSACTIONS_SHEET_NAME)
        ts = shift.closed_at or shift.opened_at
        cash = shift.cash_received
        online = shift.online_payments
        rows = []
        for pkg in shift.morning_packages:
            notes = pkg.pc_name + (" (" + pkg.hz + " " + pkg.hrs + ")") if pkg.hz else pkg.pc_name
            rows.append([
                shift.date, shift.day, shift.shift_name,
                shift.employee_name, "Morning Package",
                notes, "", "", "", "", pkg.amount, cash, online, ts
            ])
        for pkg in shift.nighter_packages:
            notes = pkg.pc_name + (" (" + pkg.hz + " " + pkg.hrs + ")") if pkg.hz else pkg.pc_name
            rows.append([
                shift.date, shift.day, shift.shift_name,
                shift.employee_name, "Nighter Package",
                notes, "", "", "", "", pkg.amount, cash, online, ts
            ])
        for ses in shift.ps5_sessions:
            rows.append([
                shift.date, shift.day, shift.shift_name,
                shift.employee_name, "PS5 Session",
                ses.ps_number, ses.controllers, ses.start_time,
                ses.end_time, ses.duration_hours, ses.amount, cash, online, ts
            ])
        if not rows:
            return

        # Dedup check + append under a lock. Each shift's transactions share
        # one timestamp, so (employee, timestamp) uniquely identifies the
        # block; retries and concurrent syncs can never double-append.
        with self._sync_lock:
            col_map = self._resolve_column_indices(ws) if (ts or ordered) else {}
            insert_at = None
            if ts:
                emp_idx = col_map.get("Employee")
                ts_idx = col_map.get("Timestamp")
                if emp_idx is None:
                    emp_idx = 3
                if ts_idx is None:
                    ts_idx = 13
                try:
                    values = ws.get_all_values()
                    if len(values) > 1:
                        for row in values[1:]:
                            if row and len(row) > max(emp_idx, ts_idx):
                                if row[emp_idx] == shift.employee_name and row[ts_idx] == ts:
                                    print(f"  Dedup: transactions for shift {shift.shift_id} already exist, skipping")
                                    return
                        if ordered:
                            insert_at = self._ordered_insert_at(
                                ws, values, col_map, shift.date, ts,
                                date_fallback=0, closed_fallback=13
                            )
                except Exception:
                    pass
            elif ordered:
                # Legacy shift with no timestamp: order by date only, after
                # any same-date rows.
                try:
                    values = ws.get_all_values()
                    insert_at = self._ordered_insert_at(
                        ws, values, col_map, shift.date, "\uffff",
                        date_fallback=0, closed_fallback=0
                    )
                except Exception:
                    pass
            if insert_at is None:
                ws.append_rows(rows)
            else:
                ws.insert_rows(rows, insert_at)
