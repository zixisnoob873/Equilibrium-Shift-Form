import sys
import threading
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.google_sheets import GoogleSheetsManager
from core.models import ShiftData, PackageEntry, PS5Session
import core.google_sheets as gs_mod

# Never write fixture shifts to the real project's local_data: the sheets
# manager flags synced shifts by calling its own module-level save_shift.
gs_mod.save_shift = lambda s: None

SUMMARY_HEADER = ["Shift ID", "Date", "Day", "Shift Timing", "Employee Name",
                  "Topup Sale", "Morning Pkg Sale", "Nighter Pkg Sale", "PS5 Sale",
                  "Cafeteria Sale", "Total Expenses", "Grand Total", "Cash Received",
                  "Online Payments", "Actual POS Amount", "Total TAX Amount",
                  "Morning Pkg Count", "Nighter Pkg Count", "PS5 Session Count",
                  "Inventory", "Expenses", "Closed At", "Pancafe Screenshot", "Form Screenshot"]
TX_HEADER = ["Date", "Day", "Shift Name", "Employee", "Type", "Item / Notes",
             "Controllers", "Start Time", "End Time", "Duration (hrs)",
             "Amount (PKR)", "Cash Received", "Online Payments", "Timestamp"]


class MockSheet:
    def __init__(self, header):
        self.header = list(header)
        self.rows = [list(header)]
        self.lock = threading.Lock()

    def row_values(self, n):
        if n == 1:
            return list(self.header)
        return []

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


class MockWb:
    def __init__(self):
        self.summary = MockSheet(SUMMARY_HEADER)
        self.tx = MockSheet(TX_HEADER)

    def worksheet(self, name):
        if name == "Shift Summary":
            return self.summary
        return self.tx

    def add_worksheet(self, title=None, rows=0, cols=0):
        raise AssertionError("add_worksheet should not be called")


def make_shift(sid, emp, closed_at, n_pkgs=3):
    s = ShiftData()
    s.shift_id = sid
    s.employee_name = emp
    s.date = "2026-08-01"
    s.day = "Saturday"
    s.shift_name = "Evening"
    s.shift_timing = "4:00 PM - 12:00 AM"
    s.closed_at = closed_at
    s.opened_at = "2026-08-01 17:00:00"
    s.grand_total = 2400.0
    for i in range(n_pkgs):
        s.morning_packages.append(PackageEntry(f"PC #{i+1}", 800.0, "180Hz", "6hrs"))
    s.ps5_sessions.append(PS5Session("Left", 2, "18:00", "19:00", 700.0, 1, False))
    return s


def new_mgr(wb):
    mgr = GoogleSheetsManager()
    mgr.client = MockClient(wb)
    mgr._authenticate = lambda: None
    mgr.is_ready = lambda: True
    mgr._upload_to_imgbb = lambda f: ""
    return mgr


class MockClient:
    def __init__(self, wb):
        self.wb = wb

    def open_by_key(self, key):
        return self.wb


FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"[{status}] {name} {detail}")


# Scenario A: sequential double sync -> no duplicates
wb = MockWb()
mgr = new_mgr(wb)
s = make_shift("aaaa0001", "Ali", "2026-08-01 23:00:00")
ok1, msg1 = mgr.sync_shift_sync(s)
ok2, msg2 = mgr.sync_shift_sync(s)
check("A1 first sync ok", ok1, msg1)
check("A2 second sync ok", ok2, msg2)
check("A3 summary exactly 1 data row", len(wb.summary.rows) == 2, f"rows={len(wb.summary.rows)}")
check("A4 tx exactly 4 data rows (3 pkg + 1 ps5)", len(wb.tx.rows) == 5, f"rows={len(wb.tx.rows)}")

# Scenario B: concurrent double sync of same shift -> no duplicates
wb = MockWb()
mgr = new_mgr(wb)
s2 = make_shift("bbbb0002", "Bilal", "2026-08-01 22:00:00")
barrier = threading.Barrier(2)
results = []


def sync_thread():
    barrier.wait()
    results.append(mgr.sync_shift_sync(s2))


t1 = threading.Thread(target=sync_thread)
t2 = threading.Thread(target=sync_thread)
t1.start(); t2.start(); t1.join(); t2.join()
check("B1 summary exactly 1 data row", len(wb.summary.rows) == 2, f"rows={len(wb.summary.rows)}")
check("B2 tx exactly 4 data rows", len(wb.tx.rows) == 5, f"rows={len(wb.tx.rows)}")

# Scenario C: partial failure recovery (summary exists, tx missing)
wb = MockWb()
s3 = make_shift("cccc0003", "Sara", "2026-08-01 20:30:00")
wb.summary.append_row([s3.shift_id] + ["x"] * 23)
mgr = new_mgr(wb)
okc, msgc = mgr.sync_shift_sync(s3)
check("C1 recovery sync ok", okc, msgc)
check("C2 summary still exactly 1 data row", len(wb.summary.rows) == 2, f"rows={len(wb.summary.rows)}")
check("C3 tx appended exactly once", len(wb.tx.rows) == 5, f"rows={len(wb.tx.rows)}")
okc2, msgc2 = mgr.sync_shift_sync(s3)
check("C4 re-run does not duplicate tx", len(wb.tx.rows) == 5, f"rows={len(wb.tx.rows)}")

# Scenario D: same employee, different timestamps -> both blocks kept
wb = MockWb()
mgr = new_mgr(wb)
d1 = make_shift("dddd0003", "Usman", "2026-08-01 20:00:00")
d2 = make_shift("eeee0004", "Usman", "2026-08-01 21:00:00")
d1.grand_total = 2400.0
d2.grand_total = 3100.0
mgr.sync_shift_sync(d1)
mgr.sync_shift_sync(d2)
check("D1 both summaries present", len(wb.summary.rows) == 3, f"rows={len(wb.summary.rows)}")
check("D2 both tx blocks present", len(wb.tx.rows) == 9, f"rows={len(wb.tx.rows)}")

# Scenario E: empty closed_at + opened_at (legacy) -> no dedup crash, appends
wb = MockWb()
mgr = new_mgr(wb)
e1 = make_shift("ffff0005", "Hamza", "")
e1.opened_at = ""
mgr.sync_shift_sync(e1)
check("E1 legacy shift appended without crash", len(wb.summary.rows) == 2 and len(wb.tx.rows) == 5,
      f"s={len(wb.summary.rows)} tx={len(wb.tx.rows)}")

# Scenario F: recovery via _sync_closed_shifts path (summary in sheet, flag False)
import core.local_cache as lc
import server as server_mod

wb = MockWb()
s4 = make_shift("abcd9999", "Ahmed", "2026-08-01 19:00:00")
s4.status = "closed"
wb.summary.append_row([s4.shift_id] + ["x"] * 23)
mgr = new_mgr(wb)
lc.get_all_shifts = lambda: [s4]
lc.save_shift = lambda s: None
server_mod.save_shift = lambda s: None
res = server_mod._sync_closed_shifts(mgr, wb, skip_existing=False)
check("F1 shift recovered (transactions appended)", len(wb.tx.rows) == 5, f"rows={len(wb.tx.rows)}")
check("F2 recovery result has no errors", len(res["errors"]) == 0, str(res))
check("F3 shift flagged synced", s4.synced_to_sheets is True)

print()
if FAILURES:
    print("RESULT: FAILURES ->", FAILURES)
    sys.exit(1)
print("RESULT: ALL PASS")
