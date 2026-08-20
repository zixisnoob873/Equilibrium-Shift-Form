import sys
import json
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as server_mod

# Isolate from the real pending_alarms.json
STORE = []


def fake_load():
    return [dict(a) for a in STORE]


def fake_save(alarms):
    STORE.clear()
    STORE.extend(dict(a) for a in alarms)


server_mod._load_pending_alarms = fake_load
server_mod._save_pending_alarms = fake_save
server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
client = server_mod.app.test_client()


def schedule(sessions):
    r = client.post("/api/alarms/schedule", json={"sessions": sessions})
    assert r.status_code == 200, r.get_data()
    return r.get_json()


def pending_ids():
    r = client.get("/api/alarms/pending")
    assert r.status_code == 200, r.get_data()
    return [a["id"] for a in r.get_json()["alarms"]]


def stored_ids():
    return [a["id"] for a in STORE]


def ack(ids):
    r = client.post("/api/alarms/acknowledge", json={"ids": ids})
    assert r.status_code == 200, r.get_data()


now = datetime.now()
end_just_fired = int((now - timedelta(minutes=2)).timestamp() * 1000)
end_past = int((now - timedelta(hours=1)).timestamp() * 1000)
end_stale = int((now - timedelta(hours=30)).timestamp() * 1000)

# 1. schedule one session -> stored and pending (end already passed)
schedule([{"id": "S1", "psNumber": "PS1", "endTs": end_just_fired, "endTotalMin": 120}])
assert stored_ids() == ["S1"], stored_ids()
assert pending_ids() == ["S1"], pending_ids()
print("[PASS] schedule S1 -> stored + pending")

# 2. shift transition: schedule with EMPTY list must NOT delete S1
schedule([])
assert "S1" in stored_ids(), stored_ids()
print("[PASS] empty schedule keeps S1 (old replace-all prune gone)")

# 3. partial list (S2 only) must NOT delete S1
schedule([{"id": "S2", "psNumber": "PS2", "endTs": end_just_fired, "endTotalMin": 60}])
ids = stored_ids()
assert "S1" in ids and "S2" in ids, ids
print("[PASS] partial schedule keeps both alarms")

# 4. reschedule S1 with a new end time -> timestamp updates, still pending
schedule([{"id": "S1", "psNumber": "PS1", "endTs": end_past, "endTotalMin": 90}])
r = client.get("/api/alarms/pending")
s1 = next(a for a in r.get_json()["alarms"] if a["id"] == "S1")
assert s1["end_timestamp"].startswith((now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")), s1["end_timestamp"]
print("[PASS] reschedule updates end_timestamp")

# 5. acknowledge removes from pending (explicit cleanup path still works)
ack(["S1", "S2"])
assert pending_ids() == [], pending_ids()
print("[PASS] acknowledge clears pending")

# 6. GC: acknowledged stale (>24h) alarm pruned on next schedule; recent acked kept
schedule([{"id": "S3", "psNumber": "PS3", "endTs": end_stale, "endTotalMin": 60}])
ack(["S3"])
schedule([])
assert "S3" not in stored_ids(), stored_ids()
assert "S1" in stored_ids(), stored_ids()
print("[PASS] acknowledged stale (>24h) pruned, acknowledged recent kept")

# 7. GC: unacknowledged alarm older than 24h KEPT (must still ring on reload)
schedule([{"id": "S4", "psNumber": "PS4", "endTs": end_stale, "endTotalMin": 60}])
schedule([])
assert "S4" in stored_ids(), stored_ids()
print("[PASS] unacknowledged stale alarm survives schedule GC")

print()
print("RESULT: ALL PASS")
