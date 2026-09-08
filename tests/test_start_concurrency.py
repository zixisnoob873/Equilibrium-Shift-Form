import sys
import os
import time
import json
import tempfile
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.local_cache as lc
import core.shift_manager as sm_mod
import server as server_mod
from core.models import ShiftData

# Setup isolated temp directory for real disk I/O
temp_dir = tempfile.mkdtemp(prefix="shift_test_")
lc.LOCAL_DATA_DIR = temp_dir

server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
server_mod.shift_manager.sheets.is_ready = lambda: False

client = server_mod.app.test_client()

# Reset in-memory state
server_mod.shift_manager.current_shift = None

def hit_start(idx):
    return client.post("/api/shift/start", json={"employee_name": f"Tester {idx}"})

print(f"Testing 10 simultaneous /api/shift/start requests with REAL disk I/O in {temp_dir}...")
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(hit_start, i) for i in range(10)]
    for f in concurrent.futures.as_completed(futures):
        results.append(f.result())

status_codes = [r.status_code for r in results]
successes = [r for r in results if r.status_code == 200]
conflicts = [r for r in results if r.status_code == 409]

print(f"Results: {len(successes)} succeeded (200), {len(conflicts)} rejected (409)")
assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
assert len(conflicts) == 9, f"Expected 9 conflicts, got {len(conflicts)}"

# Verify real disk state: exactly 1 shift file must exist in temp_dir
shift_files = [f for f in os.listdir(temp_dir) if f.startswith("shift_") and f.endswith(".json")]
print(f"Shift files created on disk: {shift_files}")
assert len(shift_files) == 1, f"Expected exactly 1 shift file on disk, got {len(shift_files)}: {shift_files}"

data = successes[0].get_json()
assert data["success"] is True
created_id = data["shift"]["shift_id"]
assert shift_files[0] == f"shift_{created_id}.json"
assert server_mod.shift_manager.current_shift is not None
assert server_mod.shift_manager.current_shift.shift_id == created_id
print(f"[PASS] Real-world atomic start verified: Shift {created_id} written to disk, all 9 concurrent racers rejected with 409.")

# Test 2: Auto-healing multiple active shifts in get_last_active_shift
print("\nTesting multi-active shift auto-healing with real disk files...")
# Create a second active shift file directly on disk with an older timestamp
stale_shift = ShiftData(
    shift_id="stale999",
    employee_name="Old Employee",
    date="2026-09-01",
    opened_at="2026-09-01 08:00:00",
    status="active"
)
lc.save_shift(stale_shift)

# Verify 2 active shifts currently exist on disk
all_active_before = lc.get_all_active_shifts()
assert len(all_active_before) == 2, f"Expected 2 active shifts before healing, got {len(all_active_before)}"
print(f"Active shifts before healing: {[s.shift_id for s in all_active_before]}")

# Call get_last_active_shift() which should trigger auto-healing
active = lc.get_last_active_shift()
assert active.shift_id == created_id, f"Expected newest {created_id}, got {active.shift_id}"

# Verify on disk that stale shift was auto-closed
stale_on_disk = lc.load_shift("stale999")
assert stale_on_disk.status == "closed", f"Expected stale shift on disk to be 'closed', got '{stale_on_disk.status}'"

# Verify that get_all_active_shifts now only returns the 1 true active shift
all_active_after = lc.get_all_active_shifts()
assert len(all_active_after) == 1, f"Expected 1 active shift after healing, got {len(all_active_after)}"
assert all_active_after[0].shift_id == created_id
print(f"[PASS] Multi-active auto-healing verified: stale shift auto-closed on disk, active count is now 1.")

# Clean up temp directory
import shutil
shutil.rmtree(temp_dir, ignore_errors=True)

print("\nALL CONCURRENCY & RECOVERY TESTS PASSED WITH REAL DISK I/O!")
