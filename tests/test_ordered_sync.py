import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from core.google_sheets import GoogleSheetsManager, SUMMARY_HEADERS, TRANSACTIONS_HEADERS
from core.models import ShiftData, PackageEntry, PS5Session

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"[{status}] {name} {detail}")


class MockSheet:
    def __init__(self, header):
        self.header = list(header)
        self.rows = [list(header)]
        self.lock = __import__("threading").Lock()
        self.row_count = 1000

    def row_values(self, n):
        with self.lock:
            return list(self.rows[n - 1]) if 1 <= n <= len(self.rows) else []

    def col_values(self, n):
        with self.lock:
            return [r[n - 1] if len(r) >= n else "" for r in self.rows]

    def get_all_values(self):
        with self.lock:
            return [list(r) for r in self.rows]

    def append_row(self, row):
        with self.lock:
            self.rows.append(list(row))

    def append_rows(self, rows):
        with self.lock:
            for r in rows:
                self.rows.append(list(r))

    def insert_row(self, row, index):
        with self.lock:
            self.rows.insert(index - 1, list(row))

    def insert_rows(self, rows, row):
        with self.lock:
            for k, r in enumerate(rows):
                self.rows.insert(row - 1 + k, list(r))


class MockWb:
    def __init__(self):
        self.summary = MockSheet(SUMMARY_HEADERS)
        self.tx = MockSheet(TRANSACTIONS_HEADERS)

    def worksheet(self, name):
        return self.summary if name == "Shift Summary" else self.tx


class MockClient:
    def __init__(self, wb):
        self.wb = wb

    def open_by_key(self, key):
        return self.wb


def new_mgr(wb):
    mgr = GoogleSheetsManager()
    mgr.client = MockClient(wb)
    mgr._authenticate = lambda: None
    mgr.is_ready = lambda: True
    mgr._upload_to_imgbb = lambda f, errors=None: ""
    return mgr


def make_shift(sid, date, closed_at, emp="Ali", n_tx=2):
    s = ShiftData()
    s.shift_id = sid
    s.employee_name = emp
    s.date = date
    s.day = "Wednesday"
    s.shift_name = "Evening"
    s.shift_timing = "4:00 PM - 12:00 AM"
    s.opened_at = date + " 17:00:00"
    s.closed_at = closed_at
    s.status = "closed"
    s.grand_total = 1000.0
    s.morning_packages.append(PackageEntry("PC #1", 800.0, "180Hz", "6hrs"))
    for i in range(n_tx - 1):
        s.ps5_sessions.append(PS5Session("Left", 2, "18:00", "19:00", 200.0, 1, False))
    return s


def sync_ordered(mgr, shift):
    mgr._append_summary(mgr.client.wb, shift, ordered=True)
    mgr._append_transactions(mgr.client.wb, shift, ordered=True)


# ---- Scenario A: late 12th shift inserts above 13th, later shift appends ----
wb = MockWb()
mgr = new_mgr(wb)
s13 = make_shift("shifth13", "2026-08-13", "2026-08-13 23:00:00")
sync_ordered(mgr, s13)  # empty sheet -> append
check("A1 first ordered sync appended after header", wb.summary.rows[1][0] == "shifth13", str([r[0] for r in wb.summary.rows]))
s12 = make_shift("shifth12", "2026-08-12", "2026-08-12 23:00:00")
sync_ordered(mgr, s12)
check("A2 12th inserted ABOVE 13th", [r[0] for r in wb.summary.rows[1:]] == ["shifth12", "shifth13"], str([r[0] for r in wb.summary.rows]))
check("A3 12th tx block above 13th tx block", [r[0] for r in wb.tx.rows[1:]][:2] == ["2026-08-12", "2026-08-12"] and wb.tx.rows[3][0] == "2026-08-13", str([r[0] for r in wb.tx.rows]))
s14 = make_shift("shifth14", "2026-08-14", "2026-08-14 23:00:00")
sync_ordered(mgr, s14)
check("A4 14th appended at end", [r[0] for r in wb.summary.rows[1:]] == ["shifth12", "shifth13", "shifth14"], str([r[0] for r in wb.summary.rows]))

# ---- Scenario B: repeated ordered sync never duplicates ----
s12b = make_shift("shifth12", "2026-08-12", "2026-08-12 23:00:00")
sync_ordered(mgr, s12b)
check("B1 repeat ordered sync: no duplicate", [r[0] for r in wb.summary.rows[1:]] == ["shifth12", "shifth13", "shifth14"], str([r[0] for r in wb.summary.rows]))
check("B2 repeat ordered sync: tx not duplicated", len(wb.tx.rows) == 1 + 2 + 2 + 2, f"tx rows={len(wb.tx.rows)}")

# ---- Scenario C: same-date tie-break by Closed At ----
wb2 = MockWb()
mgr2 = new_mgr(wb2)
eve = make_shift("shifteve", "2026-08-12", "2026-08-12 23:41:00")
sync_ordered(mgr2, eve)
mor = make_shift("shiftmor", "2026-08-12", "2026-08-12 15:47:00")
sync_ordered(mgr2, mor)
check("C1 earlier Closed At inserted above same-date later one", [r[0] for r in wb2.summary.rows[1:]] == ["shiftmor", "shifteve"], str([r[0] for r in wb2.summary.rows[1:]]))

# ---- Scenario D: rows with empty dates are skipped, not clobbered ----
wb2.summary.rows.append([""] * 26)  # junk row with empty date
late = make_shift("shiftlate", "2026-08-20", "2026-08-20 23:00:00")
sync_ordered(mgr2, late)
check("D1 empty-date junk row intact and untouched",
      wb2.summary.rows[-2] == [""] * 26 and wb2.summary.rows[1][0] == "shiftmor",
      str([r[0] for r in wb2.summary.rows[1:]]))
check("D2 late shift appended after junk row (nothing overwritten)",
      wb2.summary.rows[-1][0] == "shiftlate" and len(wb2.summary.rows) == 5,
      str([r[0] for r in wb2.summary.rows[1:]]))

# ---- Scenario E: grid-overflow guard falls back to append ----
wb3 = MockWb()
wb3.summary.row_count = 2  # grid holds exactly header + 1 data row
mgr3 = new_mgr(wb3)
g1 = make_shift("gridaaa1", "2026-08-13", "2026-08-13 23:00:00")
sync_ordered(mgr3, g1)
check("E1 first sync appends into grid", wb3.summary.rows[1][0] == "gridaaa1", str([r[0] for r in wb3.summary.rows]))
g2 = make_shift("gridaaa0", "2026-08-12", "2026-08-12 23:00:00")
sync_ordered(mgr3, g2)
check("E2 full grid falls back to append (grid grew, nothing lost)",
      [r[0] for r in wb3.summary.rows[1:]] == ["gridaaa1", "gridaaa0"], str([r[0] for r in wb3.summary.rows]))

# ---- Scenario F: legacy shift without timestamps ----
wb4 = MockWb()
mgr4 = new_mgr(wb4)
l1 = make_shift("legaaa01", "2026-08-13", "")
l1.opened_at = ""
sync_ordered(mgr4, l1)
l2 = make_shift("legaaa00", "2026-08-12", "")
l2.opened_at = ""
sync_ordered(mgr4, l2)
check("F1 legacy no-ts shifts ordered by date", [r[0] for r in wb4.summary.rows[1:]] == ["legaaa00", "legaaa01"], str([r[0] for r in wb4.summary.rows[1:]]))

# ---- Scenario G: endpoint integration (server.py sync_one_shift) ----
import server as server_mod
import core.local_cache as lc

server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
client = server_mod.app.test_client()

wb5 = MockWb()
mgr5 = new_mgr(wb5)
server_mod.shift_manager.sheets = mgr5

g_shift = make_shift("gord1234", "2026-08-12", "2026-08-12 23:00:00")
g_shift.synced_to_sheets = True  # flagged synced, but row was deleted from sheet
saved = []
server_mod.load_shift = lambda sid: g_shift
server_mod.save_shift = lambda s: saved.append(s.shift_id)

r = client.post("/api/sheets/sync-shift/gord1234")
b = r.get_json()
check("G1 flagged-synced + missing row -> re-inserted", r.status_code == 200 and b["success"] and not b.get("already_present"), str(b))
check("G2 re-inserted row present in sheet", wb5.summary.rows[1][0] == "gord1234", str([x[0] for x in wb5.summary.rows]))
check("G3 tx block re-inserted", len(wb5.tx.rows) == 1 + 2, f"tx rows={len(wb5.tx.rows)}")

# row already present -> no second insert
r2 = client.post("/api/sheets/sync-shift/gord1234")
b2 = r2.get_json()
check("G4 present row -> already_present, no duplicate", b2["success"] and b2.get("already_present") is True and len(wb5.summary.rows) == 2, str(b2))
check("G5 present row -> no extra tx rows", len(wb5.tx.rows) == 3, f"tx rows={len(wb5.tx.rows)}")

# unflagged + summary present + transactions MISSING -> partial-failure recovery
g_shift2 = make_shift("gord5678", "2026-08-11", "2026-08-11 23:00:00")
g_shift2.synced_to_sheets = False
server_mod.load_shift = lambda sid: g_shift2
wb5.summary.append_row([g_shift2.shift_id] + ["x"] * 25)
summary_rows_before = len(wb5.summary.rows)
tx_rows_before = len(wb5.tx.rows)
r3 = client.post("/api/sheets/sync-shift/gord5678")
b3 = r3.get_json()
check("G6 partial failure -> not 'already present'", b3["success"] and b3.get("already_present") is False, str(b3))
check("G7 summary not duplicated, missing tx block recovered",
      len(wb5.summary.rows) == summary_rows_before and len(wb5.tx.rows) == tx_rows_before + 2,
      f"summary={len(wb5.summary.rows)} tx={len(wb5.tx.rows)}")
check("G8 flag set True after recovery", g_shift2.synced_to_sheets is True and "gord5678" in saved, f"flag={g_shift2.synced_to_sheets}")

# non-closed -> 400
g_shift3 = make_shift("gord9012", "2026-08-10", "2026-08-10 23:00:00")
g_shift3.status = "active"
server_mod.load_shift = lambda sid: g_shift3
r4 = client.post("/api/sheets/sync-shift/gord9012")
check("G9 active shift -> 400", r4.status_code == 400, str(r4.status_code))

print()
if FAILURES:
    print("RESULT: FAILURES ->", FAILURES)
    sys.exit(1)
print("RESULT: ALL PASS")
