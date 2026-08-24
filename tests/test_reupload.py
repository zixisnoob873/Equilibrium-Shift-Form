import sys
import os
import json
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as server_mod

TMP = tempfile.mkdtemp(prefix="reupload_test_")
server_mod.UPLOAD_DIR = TMP

# Filenames are ownership-tagged to shift 'test1234_' (anti-mixing contract)
pancafe_file = os.path.join(TMP, "test1234_pan.png")
form_file = os.path.join(TMP, "test1234_form.png")
with open(pancafe_file, "wb") as f:
    f.write(b"\x89PNG" + b"\x00" * 500)
with open(form_file, "wb") as f:
    f.write(b"\x89PNG" + b"\x00" * 500)

IMG_URL = "https://i.ibb.co/xyz/img.png"
NEW_IMG_URL = "https://i.ibb.co/new/fresh.png"
LOCAL_URL = "http://localhost:5000/uploads/test1234_pan.png"

uploads = []
saved_shifts = []


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


def new_sm(ws, upload_fn):
    """Fresh sheets-manager fake; upload_fn(filename, errors) -> url."""
    sm = SimpleNamespace(
        _sync_lock=__import__("threading").Lock(),
        is_ready=lambda: True,
        _authenticate=lambda: None,
        _ensure_sheets_exist=lambda wb: None,
        client=SimpleNamespace(open_by_key=lambda k: FakeWb(ws)),
        config=SimpleNamespace(sheet_id="test", imgbb_key="testkey"),
        _resolve_column_indices=lambda ws_: {"Pancafe Screenshot": 22, "Form Screenshot": 23},
    )
    sm._upload_to_imgbb = lambda filename, errors=None: upload_fn(filename, errors)
    return sm


def default_upload(filename, errors=None):
    uploads.append(filename)
    return NEW_IMG_URL


def make_shift(pancafe="test1234_pan.png", form="test1234_form.png", status="closed"):
    return SimpleNamespace(
        shift_id="test1234",
        status=status,
        pancafe_screenshot_filename=pancafe,
        form_screenshot_filename=form,
        pancafe_screenshot_url="",
        form_screenshot_url="",
    )


server_mod.app.config["WTF_CSRF_ENABLED"] = False
server_mod.app.config["TESTING"] = True
client = server_mod.app.test_client()
server_mod.save_shift = lambda s: saved_shifts.append(s)

results = []
def check(name, cond, detail=""):
    results.append(cond)
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else "  << " + str(detail)))


# S1: both cells already hold OLD ImgBB links -> FORCE re-host replaces them
ws = FakeWs(["test1234"], {(1, 23): IMG_URL, (1, 24): IMG_URL})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
server_mod.load_shift = lambda sid: make_shift()
uploads.clear(); saved_shifts.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S1: success, both freshly re-hosted", r.status_code == 200 and b["success"] and b["uploaded_count"] == 2, json.dumps(b))
check("S1: cells overwritten with NEW links", ws.cells.get((1, 23)) == NEW_IMG_URL and ws.cells.get((1, 24)) == NEW_IMG_URL, str(ws.cells))
check("S1: persisted shift URLs updated", saved_shifts and saved_shifts[0].pancafe_screenshot_url == NEW_IMG_URL and saved_shifts[0].form_screenshot_url == NEW_IMG_URL, str(saved_shifts))
check("S1: no warnings", not b.get("warnings"), str(b.get("warnings")))

# S1b: same NEW link already in cells -> still succeeds, zero redundant writes
updates_before = len(ws.updates)
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S1b: identical value -> no redundant update_cell", b["success"] and len(ws.updates) == updates_before, str(ws.updates))

# S2: both cells EMPTY + files exist -> both uploaded
ws = FakeWs(["test1234"], {})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S2: both uploaded from empty cells", b["uploaded_count"] == 2 and sorted(uploads) == ["test1234_form.png", "test1234_pan.png"], str(uploads))
check("S2: both cells written", all(u[2] == NEW_IMG_URL for u in ws.updates), str(ws.updates))

# S3: localhost link in pancafe cell -> upgraded to fresh ImgBB link
ws = FakeWs(["test1234"], {(1, 23): LOCAL_URL})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S3: local cell upgraded to fresh ImgBB", b["success"] and ws.cells.get((1, 23)) == NEW_IMG_URL, str(ws.cells))
check("S3: both re-hosted", b["uploaded_count"] == 2, str(b))

# S4: pancafe file missing locally -> warning, cell preserved; form still uploaded
os.rename(pancafe_file, pancafe_file + ".bak")
try:
    ws = FakeWs(["test1234"], {(1, 23): IMG_URL})
    sm = new_sm(ws, default_upload)
    server_mod.shift_manager.sheets = sm
    server_mod.load_shift = lambda sid: make_shift(pancafe="test1234_gone.png")
    uploads.clear()
    r = client.post("/api/screenshots/re-upload/test1234")
    b = r.get_json()
    check("S4: missing file warns and cell NOT touched", b["success"] and any("missing locally" in w for w in b.get("warnings", [])), json.dumps(b))
    check("S4: old ibb link preserved", ws.cells.get((1, 23)) == IMG_URL, str(ws.cells))
    check("S4: only form uploaded", uploads == ["test1234_form.png"] and ws.cells.get((1, 24)) == NEW_IMG_URL, str(uploads))
finally:
    os.rename(pancafe_file + ".bak", pancafe_file)
    server_mod.load_shift = lambda sid: make_shift()

# S5: ANTI-MIXING - filename not tagged to this shift -> refused outright
ws = FakeWs(["test1234"], {(1, 23): IMG_URL, (1, 24): IMG_URL})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
server_mod.load_shift = lambda sid: make_shift(pancafe="other9999_steal.png", form="test1234_form.png")
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S5: untagged file refused with warning", any("not tagged to this shift" in w for w in b.get("warnings", [])), json.dumps(b))
check("S5: zero uploads of foreign file", "other9999_steal.png" not in uploads, str(uploads))
check("S5: cells untouched by foreign attempt", ws.cells.get((1, 23)) == IMG_URL, str(ws.cells))
check("S5: own tagged form file still re-hosted", b["uploaded_count"] == 1 and ws.cells.get((1, 24)) == NEW_IMG_URL, str(b))
server_mod.load_shift = lambda sid: make_shift()

# S6: UPLOAD FAILS (ImgBB error -> local fallback + reason) -> existing ibb cells PRESERVED
def failing_upload(filename, errors=None):
    uploads.append(filename)
    if errors is not None:
        errors.append("API error: rate limit exceeded")
    return LOCAL_URL

ws = FakeWs(["test1234"], {(1, 23): IMG_URL, (1, 24): IMG_URL})
sm = new_sm(ws, failing_upload)
server_mod.shift_manager.sheets = sm
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S6: nothing overwrites good links on failure", ws.cells.get((1, 23)) == IMG_URL and ws.cells.get((1, 24)) == IMG_URL, str(ws.cells))
check("S6: exact reason surfaced in warnings", any("API error: rate limit exceeded" in w for w in b.get("warnings", [])), json.dumps(b.get("warnings")))
check("S6: uploaded_count 0, success True", b["uploaded_count"] == 0 and b["success"] is True, str(b))

# S7: shift row missing -> 404
ws = FakeWs(["otherid"], {})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
r = client.post("/api/screenshots/re-upload/test1234")
check("S7: missing summary row -> 404", r.status_code == 404, str(r.status_code))

# S8: no screenshot on record (empty filenames) -> warnings, no crash
ws = FakeWs(["test1234"], {})
sm = new_sm(ws, default_upload)
server_mod.shift_manager.sheets = sm
server_mod.load_shift = lambda sid: make_shift(pancafe="", form="")
uploads.clear()
r = client.post("/api/screenshots/re-upload/test1234")
b = r.get_json()
check("S8: empty filenames warn, no uploads", b["success"] and len(uploads) == 0 and len(b.get("warnings", [])) == 2, json.dumps(b))
server_mod.load_shift = lambda sid: make_shift()

# S9: active shift -> 400
server_mod.load_shift = lambda sid: SimpleNamespace(
    shift_id="test1234", status="active",
    pancafe_screenshot_filename="p.png", form_screenshot_filename="f.png")
r = client.post("/api/screenshots/re-upload/test1234")
check("S9: active shift -> 400", r.status_code == 400, str(r.status_code))
server_mod.load_shift = lambda sid: make_shift()

print()
failed = [i for i, c in enumerate(results) if not c]
print("RESULT: " + ("ALL PASS (" + str(len(results)) + " checks)" if not failed else str(len(failed)) + " FAILED"))
sys.exit(1 if failed else 0)
