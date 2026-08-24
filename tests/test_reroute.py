import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from core.models import ShiftData
import server as server_mod

TMP = tempfile.mkdtemp(prefix="reroute_test_")
server_mod.UPLOAD_DIR = TMP
for fname in ("abc12345_pan.png", "abc12345_form.png"):
    with open(os.path.join(TMP, fname), "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * 300)

SUMMARY_HEADER = ["Shift ID", "Date", "Day", "Shift Timing", "Employee Name",
                  "Topup Sale", "Morning Pkg Sale", "Nighter Pkg Sale", "PS5 Sale",
                  "Cafeteria Sale", "Total Expenses", "Grand Total", "Cash Received",
                  "Online Payments", "Actual POS Amount", "Total TAX Amount",
                  "Morning Pkg Count", "Nighter Pkg Count", "PS5 Session Count",
                  "Inventory", "Expenses", "Closed At", "Pancafe Screenshot", "Form Screenshot"]


class Sheet:
    def __init__(self, header):
        self.header = list(header)
        self.rows = [list(header)]
        self.cells = {}

    def row_values(self, n):
        return list(self.header) if n == 1 else []

    def col_values(self, n):
        return [r[n - 1] if len(r) >= n else "" for r in self.rows]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def append_row(self, row):
        self.rows.append(list(row))

    def append_rows(self, rows):
        for r in rows:
            self.rows.append(list(r))

    def update_cell(self, row, col, val):
        self.cells[(row, col)] = val

    def cell(self, row, col):
        return SimpleNamespace(value=self.cells.get((row, col), ""))


class Wb:
    def __init__(self):
        self.summary = Sheet(SUMMARY_HEADER)
        self.tx = Sheet([])

    def worksheet(self, name):
        return self.summary if name == "Shift Summary" else self.tx


FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"[{status}] {name} {detail}")


def call_route(fn, *a):
    from flask import Response
    out = fn(*a)
    if isinstance(out, tuple):
        resp, code = out
        return resp, code
    return out, 200


# --- re_upload_screenshots: headers map to cols 23/24 ---
wb = Wb()
wb.summary.rows.append([s_id := "abc12345"] + ["x"] * 23)
sm = server_mod.shift_manager.sheets
sm._authenticate = lambda: None
sm.is_ready = lambda: True
sm.client = type("C", (), {"open_by_key": lambda self, k: wb})()
# Force-reupload mode only accepts fresh ImgBB links; local fallbacks are refused.
sm._upload_to_imgbb = lambda f, errors=None: "https://i.ibb.co/x/" + f
saved_shifts = []
server_mod.save_shift = lambda s: saved_shifts.append(s.shift_id)
shift = ShiftData()
shift.shift_id = s_id
shift.status = "closed"
shift.pancafe_screenshot_filename = "abc12345_pan.png"
shift.form_screenshot_filename = "abc12345_form.png"
server_mod.load_shift = lambda sid: shift

with server_mod.app.test_request_context():
    resp, code = call_route(server_mod.re_upload_screenshots, s_id)
    body = resp.get_json()
    check("re-upload ok", code == 200 and body["success"], str(body))
    check("pancafe written to col 23", wb.summary.cells.get((2, 23)) == "https://i.ibb.co/x/abc12345_pan.png", str(wb.summary.cells))
    check("form written to col 24", wb.summary.cells.get((2, 24)) == "https://i.ibb.co/x/abc12345_form.png", str(wb.summary.cells))
    check("cols 21/22 untouched", (2, 21) not in wb.summary.cells and (2, 22) not in wb.summary.cells, str(wb.summary.cells))

# --- legacy header fallback: no screenshot cols -> 23/24 ---
wb2 = Wb()
wb2.summary.header = SUMMARY_HEADER[:22]
wb2.summary.rows = [list(wb2.summary.header), [s_id] + ["x"] * 21]
sm.client = type("C", (), {"open_by_key": lambda self, k: wb2})()
sm._upload_to_imgbb = lambda f, errors=None: "https://i.ibb.co/x/" + f
with server_mod.app.test_request_context():
    resp, code = call_route(server_mod.re_upload_screenshots, s_id)
    body = resp.get_json()
    check("legacy fallback ok", code == 200 and body["success"], str(body))
    check("legacy pancafe col 23", wb2.summary.cells.get((2, 23)) == "https://i.ibb.co/x/abc12345_pan.png", str(wb2.summary.cells))
    check("legacy form col 24", wb2.summary.cells.get((2, 24)) == "https://i.ibb.co/x/abc12345_form.png", str(wb2.summary.cells))

# --- no sheet-clear concept: endpoint must not exist (404), no wipe route ---
server_mod.app.config["WTF_CSRF_ENABLED"] = False
client = server_mod.app.test_client()
r = client.post("/api/sheets/clear")
check("POST /api/sheets/clear -> 404 (endpoint removed)", r.status_code == 404, str(r.status_code))
check("clear_sheets symbol gone", not hasattr(server_mod, "clear_sheets"), "")

print()
if FAILURES:
    print("RESULT: FAILURES ->", FAILURES)
    sys.exit(1)
print("RESULT: ALL PASS")
