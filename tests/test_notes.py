"""
Shift Notes (summary sheet column 27) — end-to-end coverage.

A note is free text entered in the form's Expenses & Refunds section. It has
no amount and must NEVER influence money: not total_expenses, not
grand_total, not the payment check, not the analytics aggregators. The whole
point of this suite is that the note feature is additive and inert.

Run:  python tests\test_notes.py
"""
import os
import sys
import json
import shutil
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.models import ShiftData
from core.google_sheets import (
    GoogleSheetsManager,
    SUMMARY_HEADERS,
    TRANSACTIONS_HEADERS,
    SUMMARY_SHEET_NAME,
    TRANSACTIONS_SHEET_NAME,
)
from core.analytics import compute_financial_stats
import core.local_cache as lc
import server as server_mod

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else "  << " + str(detail)))


# --------------------------------------------------------------------------
# 1. Schema: the header exists, is LAST, and the old columns did not move
# --------------------------------------------------------------------------
check("N1  Summary sheet is now 27 columns", len(SUMMARY_HEADERS) == 27, len(SUMMARY_HEADERS))
check("N2  Transactions sheet is still 14 columns", len(TRANSACTIONS_HEADERS) == 14, len(TRANSACTIONS_HEADERS))
check("N3  col 27 is 'Note'", SUMMARY_HEADERS[26] == "Note", SUMMARY_HEADERS[26])
check("N4  cols 1-26 unchanged (index-stable append)",
      SUMMARY_HEADERS[:26] == [
          "Shift ID", "Date", "Day", "Shift Timing", "Employee Name", "Topup Sale",
          "Morning Pkg Sale", "Nighter Pkg Sale", "PS5 Sale", "Cafeteria Sale",
          "Total", "Online Payments", "Cash Received", "Actual POS Amount",
          "Total Payment Received", "Total Expenses", "Reconciliation",
          "Grand Total", "Total TAX Amount", "Morning Pkg Count",
          "Nighter Pkg Count", "PS5 Session Count", "Inventory", "Closed At",
          "Pancafe Screenshot", "Form Screenshot"],
      SUMMARY_HEADERS[:26])
check("N5  screenshot columns still at 25/26 (1-based)",
      SUMMARY_HEADERS.index("Pancafe Screenshot") + 1 == 25
      and SUMMARY_HEADERS.index("Form Screenshot") + 1 == 26,
      (SUMMARY_HEADERS.index("Pancafe Screenshot") + 1, SUMMARY_HEADERS.index("Form Screenshot") + 1))


# --------------------------------------------------------------------------
# 2. Models: round-trip plus tolerance of every shape a client might send
# --------------------------------------------------------------------------
s = ShiftData(shift_id="note0001", employee_name="Tester", notes=["Monitor rebooted", "Drawer short 50"])
rt = ShiftData.from_dict(s.to_dict())
check("N6  to_dict/from_dict round-trips notes", rt.notes == ["Monitor rebooted", "Drawer short 50"], rt.notes)

check("N7  accepts bare-string form", ShiftData.from_dict({"notes": "solo"}).notes == ["solo"],
      ShiftData.from_dict({"notes": "solo"}).notes)
check("N8  accepts nested-array form", ShiftData.from_dict({"notes": [["a"], ["b"]]}).notes == ["a", "b"],
      ShiftData.from_dict({"notes": [["a"], ["b"]]}).notes)
check("N9  accepts dict form", ShiftData.from_dict({"notes": [{"text": "d"}]}).notes == ["d"],
      ShiftData.from_dict({"notes": [{"text": "d"}]}).notes)
check("N10 pre-existing shift JSON (no notes key) loads empty",
      ShiftData.from_dict({"shift_id": "old1", "status": "closed"}).notes == [], "must be []")
check("N11 null notes is safe", ShiftData.from_dict({"notes": None}).notes == [], "must be []")
check("N12 blanks are dropped, text trimmed",
      ShiftData.from_dict({"notes": ["  a  ", "", "   ", "b"]}).notes == ["a", "b"],
      ShiftData.from_dict({"notes": ["  a  ", "", "   ", "b"]}).notes)


# --------------------------------------------------------------------------
# 3. Server parser
# --------------------------------------------------------------------------
check("N13 _parse_notes normalizes a plain list",
      server_mod._parse_notes(["a", " b ", "", "c"]) == ["a", "b", "c"],
      server_mod._parse_notes(["a", " b ", "", "c"]))
check("N14 _parse_notes tolerates a bare string",
      server_mod._parse_notes("solo") == ["solo"], server_mod._parse_notes("solo"))
check("N15 _parse_notes on None/[] is empty",
      server_mod._parse_notes(None) == [] and server_mod._parse_notes([]) == [], "must be []")

# 3b. Malformed input must NEVER raise and must never reach the sheet as junk.
# A raise inside close/auto-save is caught by the route's except -> HTTP 500,
# which would lose the entire shift save over a bad notes field.
_fmt_mgr = GoogleSheetsManager.__new__(GoogleSheetsManager)


def _fmt(notes):
    return _fmt_mgr._format_notes_for_sheet(ShiftData(notes=notes))


malformed = [5, True, False, 3.7, {"text": "d"}, {"no_text": 1}, [["deep"]],
             [object()], {"a": 1}, b"bytes", [None], [""], "ok", ["ok"], 0, [[], {}, ""]]
raised = []
for bad in malformed:
    for label, fn in (("_parse_notes", server_mod._parse_notes),
                      ("from_dict", lambda v: ShiftData.from_dict({"notes": v}).notes),
                      ("_format_notes_for_sheet", _fmt)):
        try:
            fn(bad)
        except Exception as e:
            raised.append("%s(%r) -> %s: %s" % (label, bad, type(e).__name__, e))
check("N47 no malformed notes value can raise", not raised, raised)

# Unrecognised structures must be dropped, never stringified into the sheet.
check("N49 all-junk notes render as '-' (nothing stringified)",
      _fmt([{"x": 1}, [[["y"]]], object(), {"a": {"b": 1}}]) == "-",
      repr(_fmt([{"x": 1}, [[["y"]]], object(), {"a": {"b": 1}}])))
check("N50 dict-shaped note renders its text, not the dict",
      _fmt([{"text": "real note"}]) == "real note", repr(_fmt([{"text": "real note"}])))
check("N51 pair-shaped note renders its text",
      _fmt([["paired note"]]) == "paired note", repr(_fmt([["paired note"]])))


# --------------------------------------------------------------------------
# 4. Sheet cell formatting: "-" / bare / numbered
# --------------------------------------------------------------------------
mgr = GoogleSheetsManager.__new__(GoogleSheetsManager)
check("N16 0 notes -> '-'", mgr._format_notes_for_sheet(ShiftData(notes=[])) == "-",
      repr(mgr._format_notes_for_sheet(ShiftData(notes=[]))))
check("N17 1 note -> bare text, no numbering",
      mgr._format_notes_for_sheet(ShiftData(notes=["Monitor rebooted"])) == "Monitor rebooted",
      repr(mgr._format_notes_for_sheet(ShiftData(notes=["Monitor rebooted"]))))
check("N18 2+ notes -> numbered one per line",
      mgr._format_notes_for_sheet(ShiftData(notes=["a", "b", "c"])) == "1. a\n2. b\n3. c",
      repr(mgr._format_notes_for_sheet(ShiftData(notes=["a", "b", "c"]))))
check("N19 all-blank notes -> '-'",
      mgr._format_notes_for_sheet(ShiftData(notes=["", "  "])) == "-",
      repr(mgr._format_notes_for_sheet(ShiftData(notes=["", "  "]))))


# --------------------------------------------------------------------------
# 5. Header auto-migration safety
# --------------------------------------------------------------------------
class FakeWs:
    """Minimal worksheet double that records cell writes."""

    def __init__(self, header, fail=False):
        self.header = list(header)
        self.written = []
        self.title = "Shift Summary"
        self._fail = fail

    def row_values(self, n):
        return list(self.header)

    def cell(self, row, col):
        self.written.append((row, col))
        if self._fail:
            raise RuntimeError("quota exceeded")
        ws = self

        class _Cell:
            @property
            def value(self):
                return ws.header[col - 1] if col - 1 < len(ws.header) else None

            @value.setter
            def value(self, v):
                if len(ws.header) < col:
                    ws.header += [""] * (col - len(ws.header))
                ws.header[col - 1] = v
        return _Cell()


legacy = ["Shift ID", "Date", "Day", "Shift Timing", "Employee Name", "Topup Sale",
          "Morning Pkg Sale", "Nighter Pkg Sale", "PS5 Sale", "Cafeteria Sale",
          "Total", "Online Payments", "Cash Received", "Actual POS Amount",
          "Total Payment Received", "Expenses", "Closed At",
          "Pancafe Screenshot", "Form Screenshot"]

ws26 = FakeWs(SUMMARY_HEADERS[:26])
check("N20 26-col sheet: 'Note' added at row 1, col 27",
      mgr._topup_headers(ws26, SUMMARY_HEADERS) is True and ws26.written == [(1, 27)]
      and ws26.header[26] == "Note", (ws26.written, ws26.header[26:]))
check("N21 migration is idempotent (2nd run is a no-op)",
      mgr._topup_headers(ws26, SUMMARY_HEADERS) is False and ws26.written == [(1, 27)],
      ws26.written)
ws27 = FakeWs(SUMMARY_HEADERS)
check("N22 already-27 sheet: nothing written",
      mgr._topup_headers(ws27, SUMMARY_HEADERS) is False and ws27.written == [], ws27.written)
ws_legacy = FakeWs(legacy)
check("N23 DRIFTED/legacy sheet: refused, zero writes",
      mgr._topup_headers(ws_legacy, SUMMARY_HEADERS) is False and ws_legacy.written == [],
      ws_legacy.written)
check("N24 empty header row: no-op",
      mgr._topup_headers(FakeWs([]), SUMMARY_HEADERS) is False, "must be False")
check("N25 API failure mid-write: caught, no crash",
      mgr._topup_headers(FakeWs(SUMMARY_HEADERS[:26], fail=True), SUMMARY_HEADERS) is False, "must be False")


# --------------------------------------------------------------------------
# 6. Full route round-trip: start -> auto-save -> disk -> close
# --------------------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="notes_test_")
orig_data_dir = lc.LOCAL_DATA_DIR
orig_settings = server_mod.SETTINGS_FILE

lc.LOCAL_DATA_DIR = tmp
server_mod.SETTINGS_FILE = os.path.join(tmp, "settings.json")
server_mod.shift_manager.current_shift = None
server_mod.shift_manager.sheets.is_ready = lambda: False
server_mod.app.config["TESTING"] = True
server_mod.app.config["WTF_CSRF_ENABLED"] = False
client = server_mod.app.test_client()

try:
    r = client.post("/api/shift/start", json={"employee_name": "Note Tester"})
    body = r.get_json()
    check("N26 shift starts", r.status_code == 200 and body["success"], (r.status_code, body))
    sid = body["shift"]["shift_id"]
    lm = body["shift"]["last_modified"]

    payload = {
        "shift_id": sid,
        "employee_name": "Note Tester",
        "last_modified": lm,
        "notes": ["Monitor rebooted", "Drawer short 50"],
        "expenses": [{"description": "Refund", "amount": 100.0}],
        "inventory_items_snapshot": [],
        "financial_summary": {
            "topup": 0, "cafeteria": 0, "morning_pkg": 500, "nighter_pkg": 0,
            "ps_sale": 700, "total_expenses": 100.0, "grand_total": 1200.0,
            "cash_received": 900.0, "online_payments": 200.0,
            "actual_pos_amount": 0.0, "total_tax_amount": 0.0,
        },
    }
    r = client.post("/api/shift/auto-save", json={"shift": payload})
    check("N27 auto-save with notes succeeds", r.status_code == 200, (r.status_code, r.get_data()[:200]))

    on_disk = lc.load_shift(sid)
    check("N28 notes persisted to disk", on_disk.notes == ["Monitor rebooted", "Drawer short 50"], on_disk.notes)
    check("N29 notes did NOT inflate total_expenses (still 100)", on_disk.total_expenses == 100.0, on_disk.total_expenses)
    check("N30 notes did NOT inflate grand_total (still 1200)", on_disk.grand_total == 1200.0, on_disk.grand_total)
    check("N31 the real expense still parsed", len(on_disk.expenses) == 1
          and on_disk.expenses[0].description == "Refund", on_disk.expenses)
    check("N32 notes mirrored into in-memory current_shift",
          server_mod.shift_manager.current_shift.notes == ["Monitor rebooted", "Drawer short 50"],
          server_mod.shift_manager.current_shift.notes)

    # close: payment must still reconcile against grand_total - expenses
    payload["last_modified"] = on_disk.last_modified
    r = client.post("/api/shift/close", json={"shift": payload})
    cbody = r.get_json()
    check("N33 close succeeds with notes present", r.status_code == 200 and cbody["success"], (r.status_code, cbody))
    closed = cbody["shift"]
    check("N34 closed shift keeps its notes", closed["notes"] == ["Monitor rebooted", "Drawer short 50"], closed["notes"])
    check("N35 closed shift total_expenses unchanged (100)", closed["total_expenses"] == 100.0, closed["total_expenses"])
    check("N36 closed shift grand_total unchanged (1200)", closed["grand_total"] == 1200.0, closed["grand_total"])

    # analytics must ignore notes entirely
    stats = compute_financial_stats([lc.load_shift(sid)])
    k, rc = stats["kpis"], stats["revenue_streams"]
    check("N37 analytics total_expenses is 100 (notes excluded)", k["total_expenses"] == 100.0, k["total_expenses"])
    check("N38 analytics gross_revenue is 1200 (notes excluded)", k["gross_revenue"] == 1200.0, k["gross_revenue"])
    check("N39 analytics net_profit = gross - expenses", round(k["net_profit"], 2) == 1100.0, k["net_profit"])
    check("N40 analytics expense log has exactly 1 entry (the real one)",
          len(stats["expenses"]) == 1 and stats["expenses"][0]["description"] == "Refund", stats["expenses"])
    check("N41 no note text leaked into any analytics field",
          "Monitor rebooted" not in json.dumps(stats), "note text found in analytics output")

    # sheet rendering end-to-end through the real _append_summary
    appended = {}

    class RowWs:
        row_count = 1000

        def __init__(self, header):
            self.header = list(header)
            self.rows = [list(header)]

        def row_values(self, n):
            return list(self.header)

        def col_values(self, c):
            return [r[0] if r else "" for r in self.rows]

        def get_all_values(self):
            return [list(r) for r in self.rows]

        def append_row(self, row):
            self.rows.append(list(row))

        def insert_row(self, row, index):
            self.rows.insert(index, list(row))

    class Wb:
        def __init__(self):
            self.s = RowWs(SUMMARY_HEADERS)

        def worksheet(self, name):
            assert name == SUMMARY_SHEET_NAME
            return self.s

    m2 = GoogleSheetsManager.__new__(GoogleSheetsManager)
    m2._sync_lock = threading.Lock()
    m2.config = type("C", (), {"imgbb_key": ""})()
    m2._upload_to_imgbb = lambda f, errors=None: ""
    shift = lc.load_shift(sid)
    wb = Wb()
    m2._append_summary(wb, shift)
    written = wb.s.rows[-1]
    check("N42 summary row now has 27 values", len(written) == 27, len(written))
    check("N43 col 27 holds the numbered note list",
          written[26] == "1. Monitor rebooted\n2. Drawer short 50", repr(written[26]))
    check("N44 col 16 Total Expenses still the real expense only",
          written[15] == "Refund: 100\nTotal: 100", repr(written[15]))

    shift.notes = []
    wb2 = Wb()
    m2._append_summary(wb2, shift)
    check("N45 zero notes writes '-' in col 27", wb2.s.rows[-1][26] == "-", repr(wb2.s.rows[-1][26]))
    shift.notes = ["only one"]
    wb3 = Wb()
    m2._append_summary(wb3, shift)
    check("N46 single note writes bare text (unnumbered)", wb3.s.rows[-1][26] == "only one", repr(wb3.s.rows[-1][26]))

finally:
    server_mod.shift_manager.current_shift = None
    lc.LOCAL_DATA_DIR = orig_data_dir
    server_mod.SETTINGS_FILE = orig_settings
    shutil.rmtree(tmp, ignore_errors=True)

# --------------------------------------------------------------------------
failed = [r for r in RESULTS if not r[0]]
print()
print("RESULT: " + ("ALL PASS (" + str(len(RESULTS)) + " checks)" if not failed
                    else str(len(failed)) + " FAILED -> " + str([r[1] for r in failed])))
sys.exit(1 if failed else 0)
