import sys, os, json, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as sm

sm.app.config["WTF_CSRF_ENABLED"] = False
client = sm.app.test_client()

tmpd = tempfile.mkdtemp()
src = os.path.join(os.path.dirname(sm.__file__), "settings.json")
tmp_settings = os.path.join(tmpd, "settings.json")
if os.path.exists(src):
    shutil.copy(src, tmp_settings)
else:
    with open(tmp_settings, "w") as f:
        json.dump({}, f)
sm.SETTINGS_FILE = tmp_settings

with sm.app.test_request_context():
    token = sm._create_admin_session("Rafay")
    payload = {
        "employees": ["Rafay", "Ali"],
        "inventory_items": ["Gatorade"],
        "packages": [{"hz": "180Hz", "hrs": "6hrs", "price": 800}],
        "ps5_pricing": {
            "two_controllers_first_hour": 700,
            "one_controller_first_hour": 400,
            "two_controllers_extended": 500,
            "one_controller_extended": 300,
            "ps5_pc_rate": 200,
        },
        "ps5_numbers": ["Left", "Right", "PC"],
        "total_pcs": 42,
    }
    resp = client.post(
        "/api/settings",
        json=payload,
        headers={"X-Admin-Token": token},
    )
    data = resp.get_json()
    print("POST /api/settings:", resp.status_code, "total_pcs ->", data.get("total_pcs") if isinstance(data, dict) else data)

    # corrupt-value clamp check
    payload["total_pcs"] = -5
    resp2 = client.post("/api/settings", json=payload, headers={"X-Admin-Token": token})
    d2 = resp2.get_json()
    print("POST clamp -5 ->", resp2.status_code, "total_pcs ->", d2.get("total_pcs") if isinstance(d2, dict) else d2)

    with open(tmp_settings, "r") as f:
        saved = json.load(f)
    print("persisted total_pcs =", saved.get("total_pcs"))
    cfg = sm.get_effective_config()
    print("effective total_pcs =", cfg["total_pcs"])

    ok = (data.get("total_pcs") == 42 and d2.get("total_pcs") == 1
          and saved.get("total_pcs") == 1 and cfg["total_pcs"] == 1)
    print("RESULT:", "ALL PASS" if ok else "FAIL")
