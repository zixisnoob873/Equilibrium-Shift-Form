import sys
import os
import json
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as server_mod

TMP = tempfile.mkdtemp(prefix="reupload_test_")
server_mod.UPLOAD_DIR = TMP

pancafe_file = os.path.join(TMP, "pancafe_test.png")
form_file = os.path.join(TMP, "form_test.png")
with open(pancafe_file, "wb") as f:
    f.write(b"\x89PNG" + b"\x00" * 500)
with open(form_file, "wb") as f:
    f.write(b"\x89PNG" + b"\x00" * 500)

IMG_URL = "https://i.ibb.co/xyz/img.png"
LOCAL_URL = "http://localhost:5000/uploads/pancafe_test.png"

uploads = []


class FakeCell:
    def __init__(self, value):
        self.value = value


class FakeWs:
    def __init__(self, ids, cells):
        self.ids = ids
        self.cells = cells  # (row, col) -> value
        self.updates = []

    def col_values(self, n):
        if n == 1:
            return self.ids
        return []

    def cell(self, row, col):
        return FakeCell(self.cells.get((row, col), ""))

    def update_cell(self, row, col, val):
        self.updates.append((row, col, val))
        self.cells[(row, col)] = val


class FakeWb:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, name):
        return self.ws


class FakeSheets:
    def __init__(self, ws):
        self._sync_lock = __import__("threading").Lock()
        self._ws = ws
        self.called = 0

    def is_ready(self):
        return True

    def _authenticate(self):
        pass

    def _ensure_sheets_exist(self, wb):
        pass

    @property
    def client(self):
        return SimpleNamespace(open_by_key=lambda k: FakeWb(self._ws))

    @property
    def config(self):
        return SimpleNamespace(sheet_id="test")

    def _resolve_column_indices(self, ws):
        return {"Pancafe Screenshot": 22, "Form Screenshot": 23}

    def _upload_to_imgbb(self, filename):
        uploads.append(filename)
        return IMG_URL


def make_shift(pancafe="pancafe_test.png", form="form_test.png"):
    return SimpleNamespace(
        shift_id="test1234",
        status="closed",
        pancafe_screenshot_filename=pancafe,
        form_screenshot_filename=form,
    )


server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
client = server_mod.app.test_client()

results = []
def check(name, cond, detail=""):
    results.append((cond, name))
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else "  << " + detail))

# Scenario 1: both cells already ImgBB -> skipped, zero uploads
ws = FakeWs(["test1234"], {(1, 23): IMG_URL, (1, 24): IMG_URL})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
server_mod.load_shift = lambda sid: make_shift()
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S1: skipped=True", r.status_code == 200 and b["success"] and b.get("skipped") is True, json.dumps(b))
check("S1: no ImgBB uploads", len(uploads) == 0, str(uploads))
check("S1: no cell writes", len(ws.updates) == 0, str(ws.updates))

# Scenario 2: both empty + files exist -> both uploaded
ws = FakeWs(["test1234"], {})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S2: uploaded both", b["success"] and len(uploads) == 2 and sorted(uploads) == sorted(["pancafe_test.png", "form_test.png"]), str(uploads))
check("S2: both cells written with ImgBB URL", len(ws.updates) == 2 and all(u[2] == IMG_URL for u in ws.updates), str(ws.updates))

# Scenario 3: local fallback URL in pancafe cell + file exists -> upgraded; empty form cell -> filled
ws = FakeWs(["test1234"], {(1, 23): LOCAL_URL})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S3: local cell upgraded to ImgBB", b["success"] and "pancafe_test.png" in uploads, str(uploads))
check("S3: both cells written (upgrade + fill)", len(ws.updates) == 2 and all(u[2] == IMG_URL for u in ws.updates), str(ws.updates))

# Scenario 4: pancafe file missing locally -> warning, cell unchanged; form still uploaded
ws = FakeWs(["test1234"], {(1, 23): LOCAL_URL})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
uploads.clear()
server_mod.load_shift = lambda sid: make_shift(pancafe="missing_pancafe.png")
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S4: missing file warns and pancafe cell not rewritten", b["success"] and any("missing locally" in w for w in b.get("warnings", [])),
    json.dumps(b))
check("S4: only form cell written", [u for u in ws.updates if u[1] == 23] == [] and [u for u in ws.updates if u[1] == 24],
    str(ws.updates))

# Scenario 5: one ImgBB, one empty -> only missing uploaded
ws = FakeWs(["test1234"], {(1, 23): IMG_URL})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S5: only form uploaded", b["success"] and uploads == ["form_test.png"], str(uploads))

# Scenario 6: shift row missing -> 404
ws = FakeWs(["otherid"], {})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
r = client.post("/api/screenshots/re-upload/test1234")
check("S6: missing summary row -> 404", r.status_code == 404, str(r.status_code))

# Scenario 7: no screenshot on record (empty filenames) -> warning, no crash
ws = FakeWs(["test1234"], {})
sm = FakeSheets(ws)
server_mod.shift_manager.sheets = sm
uploads.clear()
server_mod.load_shift = lambda sid: make_shift(pancafe="", form="")
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S7: empty filenames warn, no uploads", b["success"] and len(uploads) == 0 and len(b.get("warnings", [])) == 2, json.dumps(b))

# Scenario 8: active shift -> 400
server_mod.load_shift = lambda sid: SimpleNamespace(
    shift_id="test1234", status="active",
    pancafe_screenshot_filename="p.png", form_screenshot_filename="f.png")
r = client.post("/api/screenshots/re-upload/test1234")
check("S8: active shift -> 400", r.status_code == 400, str(r.status_code))

print()
failed = [n for c, n in results if not c]
print("RESULT: " + ("ALL PASS (" + str(len(results)) + " checks)" if not failed else str(len(failed)) + " FAILED: " + ", ".join(failed)))
sys.exit(1 if failed else 0)
