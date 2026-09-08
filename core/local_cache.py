import os
import json
import time
from typing import Optional, List
from .models import ShiftData
from config import LOCAL_DATA_DIR


def _ensure_dir():
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)


def save_shift(shift: ShiftData):
    _ensure_dir()
    shift.last_modified = time.time()
    import tempfile
    path = os.path.join(LOCAL_DATA_DIR, f"shift_{shift.shift_id}.json")
    fd, tmp = tempfile.mkstemp(dir=LOCAL_DATA_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(shift.to_dict(), f, indent=2)
        os.replace(tmp, path)
    except:
        os.unlink(tmp)
        raise


def load_shift(shift_id: str) -> Optional[ShiftData]:
    path = os.path.join(LOCAL_DATA_DIR, f"shift_{shift_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return ShiftData.from_dict(json.load(f))
    except (json.JSONDecodeError, OSError):
        return None


def get_all_shifts() -> List[ShiftData]:
    _ensure_dir()
    shifts = []
    for fname in os.listdir(LOCAL_DATA_DIR):
        if fname.startswith("shift_") and fname.endswith(".json"):
            path = os.path.join(LOCAL_DATA_DIR, fname)
            try:
                with open(path) as f:
                    shifts.append(ShiftData.from_dict(json.load(f)))
            except (json.JSONDecodeError, OSError):
                continue
    shifts.sort(key=lambda s: s.opened_at or "", reverse=True)
    return shifts


def get_all_closed_shifts() -> List[ShiftData]:
    return [s for s in get_all_shifts() if s.status in ("closed",)]


def get_recent_closed_shift_ids(limit: int = 2) -> List[str]:
    closed = get_all_closed_shifts()
    return [s.shift_id for s in closed[:limit]]


def get_last_closed_shift() -> Optional[ShiftData]:
    shifts = get_all_closed_shifts()
    if shifts:
        return shifts[0]
    return None


def get_last_shift() -> Optional[ShiftData]:
    shifts = get_all_shifts()
    if shifts:
        return shifts[0]
    return None

def get_all_active_shifts() -> List[ShiftData]:
    return [s for s in get_all_shifts() if s.status == "active"]


def get_last_active_shift() -> Optional[ShiftData]:
    active = get_all_active_shifts()
    if not active:
        return None
    if len(active) > 1:
        for stale in active[1:]:
            stale.status = "closed"
            if not stale.closed_at:
                stale.closed_at = stale.opened_at or time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                save_shift(stale)
                print(f"[RECOVERY] Auto-closed duplicate/stale active shift {stale.shift_id} (superseded by {active[0].shift_id})")
            except Exception as e:
                print(f"[WARNING] Failed to heal duplicate active shift {stale.shift_id}: {e}")
    return active[0]


SYNC_ERRORS_FILE = os.path.join(LOCAL_DATA_DIR, "sync_errors.jsonl")


def log_sync_error(shift_id: str, error: str):
    _ensure_dir()
    entry = json.dumps({"timestamp": time.time(), "shift_id": shift_id, "error": error})
    with open(SYNC_ERRORS_FILE, "a") as f:
        f.write(entry + "\n")


def get_sync_errors() -> List[dict]:
    _ensure_dir()
    if not os.path.exists(SYNC_ERRORS_FILE):
        return []
    errors = []
    with open(SYNC_ERRORS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    errors.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return errors[-100:]  # Return last 100 errors


AUDIT_LOGS_FILE = os.path.join(LOCAL_DATA_DIR, "audit_logs.jsonl")


def log_shift_access(
    shift_id: str,
    accessor_name: str,
    role: str,
    shift_date: str = "",
    shift_employee: str = "",
    ip: str = "",
):
    _ensure_dir()
    entry = json.dumps({
        "timestamp": time.time(),
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "shift_id": shift_id,
        "accessor_name": accessor_name,
        "role": role,
        "shift_date": shift_date,
        "shift_employee": shift_employee,
        "ip": ip,
    })
    with open(AUDIT_LOGS_FILE, "a") as f:
        f.write(entry + "\n")


def get_shift_access_logs(limit: int = 100) -> List[dict]:
    _ensure_dir()
    if not os.path.exists(AUDIT_LOGS_FILE):
        return []
    logs = []
    with open(AUDIT_LOGS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    logs.reverse()  # Newest first
    return logs[:limit]
