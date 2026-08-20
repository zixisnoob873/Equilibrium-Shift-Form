import sys
import time
import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
assert hasattr(gspread.Worksheet, "append_rows"), "gspread append_rows missing"
print("[PASS] gspread.Worksheet.append_rows exists")

import core.local_cache as lc
import core.shift_manager as sm_mod
import server as server_mod

written = []


def noop_save(shift):
    written.append(shift.shift_id)


def noop_log(*a):
    pass


# Prevent ANY real file writes or sheet/error-log writes during the test
lc.save_shift = noop_save
sm_mod.save_shift = noop_save
server_mod.save_shift = noop_save
sm_mod.log_sync_error = noop_log
server_mod.shift_manager.sheets.is_ready = lambda: False
# Local data contains a real orphaned active shift; keep the test isolated
lc.get_last_active_shift = lambda: None
server_mod.get_last_active_shift = lambda: None

server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
client = server_mod.app.test_client()

t0 = time.time()
r = client.get("/api/health")
assert r.status_code == 200 and r.get_json()["status"] == "ok", r.get_data()
print("[PASS] /api/health 200")

r = client.get("/")
assert r.status_code == 200 and b"shiftFormView" in r.data, r.status_code
print("[PASS] GET / renders index.html")

r = client.post("/api/shift/start", json={"employee_name": "Smoke Tester"})
body = r.get_json()
assert r.status_code == 200 and body["success"], body
shift_id = body["shift"]["shift_id"]
print(f"[PASS] /api/shift/start -> {shift_id}")

payload = {
    "shift": {
        "shift_id": shift_id,
        "employee_name": "Smoke Tester",
        "date": "2026-08-01",
        "day": "Saturday",
        "shift_name": "Evening",
        "shift_timing": "4:00 PM - 12:00 AM",
        "financial_summary": {
            "topup": 100, "cafeteria": 50, "morning_pkg": 800,
            "nighter_pkg": 0, "ps_sale": 700, "total_expenses": 100,
            "grand_total": 1550, "cash_received": 1450,
            "online_payments": 0, "actual_pos_amount": 0,
            "total_tax_amount": 0
        },
        "morning_packages": [{"pc_name": "PC #1", "amount": 800, "hz": "180Hz", "hrs": "6hrs"}],
        "nighter_packages": [],
        "ps5_sessions": [],
        "inventory": [{"name": "Lays", "opening_stock": 5, "restock_qty": 0, "closing_stock": 2}],
        "expenses": [],
        "opened_at": "2026-08-01 17:00:00",
        "inventory_items_snapshot": ["Lays"],
        "form_screenshot_filename": "",
        "pancafe_screenshot_filename": ""
    }
}

t1 = time.time()
r = client.post("/api/shift/close", json=payload)
body = r.get_json()
elapsed = time.time() - t1
assert r.status_code == 200 and body["success"], (r.status_code, body)
assert body["sync_success"] is True, body
assert "background" in body["sync_message"].lower(), body["sync_message"]
assert body["shift"]["status"] == "closed", body["shift"]["status"]
assert body["shift"]["shift_id"] == shift_id
assert elapsed < 3.0, f"close took {elapsed:.2f}s (should be near-instant)"
print(f"[PASS] /api/shift/close 200 in {elapsed*1000:.0f}ms, background sync, sync_success=True")

assert server_mod.shift_manager.current_shift is None
print("[PASS] current_shift cleared after close")

r = client.post("/api/shift/close", json=payload)
assert r.status_code == 409, r.get_json()
print("[PASS] double close -> 409")

r = client.post("/api/shift/start", json={"employee_name": "Smoke Tester 2"})
body = r.get_json()
assert r.status_code == 200 and body["success"], body
print("[PASS] start after close -> 200 (new shift active)")

shift2_id = body["shift"]["shift_id"]

# Closing operator overrides the starter (A started, B closes -> sheet shows B).
close2 = {
    "shift": {
        "shift_id": shift2_id,
        "employee_name": "Closer B",
        "financial_summary": {
            "topup": 0, "cafeteria": 0, "morning_pkg": 0,
            "nighter_pkg": 0, "ps_sale": 0, "total_expenses": 0,
            "grand_total": 0, "cash_received": 0,
            "online_payments": 0, "actual_pos_amount": 0,
            "total_tax_amount": 0
        },
        "morning_packages": [], "nighter_packages": [],
        "ps5_sessions": [], "inventory": [], "expenses": [],
        "opened_at": "2026-08-01 17:00:00",
        "inventory_items_snapshot": []
    }
}
r = client.post("/api/shift/close", json=close2)
body = r.get_json()
assert r.status_code == 200 and body["success"], (r.status_code, body)
assert body["shift"]["employee_name"] == "Closer B", body["shift"]["employee_name"]
print("[PASS] close with different operator -> employee_name becomes Closer B")

# Same-operator close must keep the name (idempotent).
r = client.post("/api/shift/start", json={"employee_name": "Smoke Tester 3"})
body = r.get_json()
assert r.status_code == 200 and body["success"], body
shift3_id = body["shift"]["shift_id"]
print("[PASS] start after close -> 200 (new shift active)")

r = client.post("/api/shift/start", json={"employee_name": "Smoke Tester 4"})
body = r.get_json()
assert r.status_code == 409, body
print("[PASS] start while active -> 409")

close3 = {
    "shift": {
        "shift_id": shift3_id,
        "employee_name": "Smoke Tester 3",
        "financial_summary": {
            "topup": 0, "cafeteria": 0, "morning_pkg": 0,
            "nighter_pkg": 0, "ps_sale": 0, "total_expenses": 0,
            "grand_total": 0, "cash_received": 0,
            "online_payments": 0, "actual_pos_amount": 0,
            "total_tax_amount": 0
        },
        "morning_packages": [], "nighter_packages": [],
        "ps5_sessions": [], "inventory": [], "expenses": [],
        "opened_at": "2026-08-01 17:00:00",
        "inventory_items_snapshot": []
    }
}
r = client.post("/api/shift/close", json=close3)
body = r.get_json()
assert r.status_code == 200 and body["success"], body
assert body["shift"]["employee_name"] == "Smoke Tester 3", body["shift"]["employee_name"]
print("[OK] same-operator close -> employee_name kept")

# Payment match is net (grand total minus expenses): an exact net match closes,
# an excess against the gross total is rejected.
r = client.post("/api/shift/start", json={"employee_name": "Smoke Tester 5"})
body = r.get_json()
assert r.status_code == 200 and body["success"], body
shift5_id = body["shift"]["shift_id"]

close5_net = {
    "shift": {
        "shift_id": shift5_id,
        "employee_name": "Smoke Tester 5",
        "financial_summary": {
            "topup": 100, "cafeteria": 50, "morning_pkg": 800,
            "nighter_pkg": 0, "ps_sale": 700, "total_expenses": 100,
            "grand_total": 1550, "cash_received": 1450,
            "online_payments": 0, "actual_pos_amount": 0,
            "total_tax_amount": 0
        },
        "morning_packages": [], "nighter_packages": [],
        "ps5_sessions": [], "inventory": [], "expenses": [],
        "opened_at": "2026-08-01 17:00:00",
        "inventory_items_snapshot": []
    }
}

close5_excess = dict(close5_net)
close5_excess["shift"] = dict(close5_net["shift"])
close5_excess["shift"]["financial_summary"] = dict(close5_net["shift"]["financial_summary"])
close5_excess["shift"]["financial_summary"]["cash_received"] = 1550

r = client.post("/api/shift/close", json=close5_excess)
body = r.get_json()
assert r.status_code == 400 and "Payment mismatch" in (body.get("error") or ""), (r.status_code, body)
assert "minus Expenses" in body.get("error", ""), body.get("error")
print("[PASS] close with excess vs gross grand total rejected -> 400 (expenses excluded from target)")

r = client.post("/api/shift/close", json=close5_net)
body = r.get_json()
assert r.status_code == 200 and body["success"], (r.status_code, body)
print("[PASS] close with net match (grand_total minus expenses) accepted -> 200")

# orphan detection path
lc.get_last_active_shift = lambda: None
r = client.get("/api/session")
assert r.status_code == 200, r.get_data()
print("[PASS] /api/session 200")

print()
print("RESULT: ALL PASS")
