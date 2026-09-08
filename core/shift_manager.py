from datetime import datetime
import uuid
import threading
from typing import Optional, Set, List, Callable
from .models import ShiftData
from .local_cache import save_shift, load_shift, get_last_closed_shift, log_sync_error
from .google_sheets import GoogleSheetsManager
from config import get_current_date, get_current_day, detect_shift


class ShiftManager:
    def __init__(self):
        self.current_shift: Optional[ShiftData] = None
        self.sheets = GoogleSheetsManager()
        self._listeners = []
        self._closing_ids: Set[str] = set()
        self._start_lock = threading.Lock()

    def is_closing(self, shift_id: str) -> bool:
        return shift_id in self._closing_ids

    def mark_closing(self, shift_id: str):
        self._closing_ids.add(shift_id)

    def unmark_closing(self, shift_id: str):
        self._closing_ids.discard(shift_id)

    def add_listener(self, callback: Callable):
        self._listeners.append(callback)

    def _notify(self, event: str, data=None):
        for cb in self._listeners:
            cb(event, data)

    def start_new_shift(self, employee_name: str):
        shift_name, shift_timing = detect_shift()
        shift_id = str(uuid.uuid4())[:8]
        # 8-char ids are improbable to collide, but if one does, never silently
        # overwrite an existing shift file — mint a fresh id.
        while load_shift(shift_id) is not None:
            shift_id = str(uuid.uuid4())[:8]
        self.current_shift = ShiftData(
            shift_id=shift_id,
            employee_name=employee_name,
            date=get_current_date(),
            day=get_current_day(),
            shift_name=shift_name,
            shift_timing=shift_timing,
            opened_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status="active"
        )
        self._notify("shift_started", self.current_shift)
        return self.current_shift

    def get_last_closed_shift(self) -> Optional[ShiftData]:
        return get_last_closed_shift()

    def close_shift(self, shift: ShiftData):
        if not shift.employee_name:
            return (False, False, "No employee name")
        shift.status = "closed"
        shift.closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_shift(shift)
        # Google Sheets sync runs in a background daemon thread so the close
        # request never blocks on slow network calls. Failures are logged to
        # sync_errors.jsonl and retried by _startup_sync / Sync All.
        threading.Thread(target=self._sync_closed_shift, args=(shift,), daemon=True).start()
        self._notify("shift_closed", shift)
        return (True, True, "Syncing to Google Sheets in the background")

    def _sync_closed_shift(self, shift: ShiftData):
        try:
            sync_success, sync_message = self.sheets.sync_shift_sync(shift)
            if not sync_success:
                log_sync_error(shift.shift_id, sync_message)
        except Exception as e:
            log_sync_error(shift.shift_id, str(e))


