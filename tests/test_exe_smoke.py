import unittest
import os
import sys
import time
import shutil
import subprocess
import urllib.request
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE_PATH = os.path.join(BASE_DIR, "dist", "ShiftManagement.exe")
TEST_PORT = 5055
TEST_SANDBOX = os.path.join(BASE_DIR, "scratch", "test_exe_sandbox")


class TestExeSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(EXE_PATH):
            raise FileNotFoundError(f"EXE not found at {EXE_PATH}. Run build_exe.bat first.")

        # Create isolated sandbox folder
        if os.path.exists(TEST_SANDBOX):
            shutil.rmtree(TEST_SANDBOX, ignore_errors=True)
        os.makedirs(TEST_SANDBOX, exist_ok=True)

        # Copy EXE into sandbox
        cls.sandbox_exe = os.path.join(TEST_SANDBOX, "ShiftManagement.exe")
        shutil.copy2(EXE_PATH, cls.sandbox_exe)

        # Copy settings.json into sandbox
        shutil.copy2(os.path.join(BASE_DIR, "settings.json"), os.path.join(TEST_SANDBOX, "settings.json"))

        # Launch EXE on test port
        env = os.environ.copy()
        env["PORT"] = str(TEST_PORT)
        env["FLASK_DEBUG"] = "0"
        env["WTF_CSRF_ENABLED"] = "0"

        cls.proc = subprocess.Popen(
            [cls.sandbox_exe],
            cwd=TEST_SANDBOX,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Wait for server to start up (up to 15 seconds)
        url = f"http://127.0.0.1:{TEST_PORT}/api/health"
        started = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(url, timeout=1) as res:
                    if res.status == 200:
                        started = True
                        break
            except Exception:
                pass

        if not started:
            cls.proc.kill()
            out, err = cls.proc.communicate()
            raise RuntimeError(f"EXE failed to start on port {TEST_PORT}.\nStdout: {out}\nStderr: {err}")

        # Create cookie-aware opener for session persistence
        import http.cookiejar
        cls.cookie_jar = http.cookiejar.CookieJar()
        cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.cookie_jar))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "proc") and cls.proc:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        if os.path.exists(TEST_SANDBOX):
            shutil.rmtree(TEST_SANDBOX, ignore_errors=True)

    def _get(self, path: str):
        url = f"http://127.0.0.1:{TEST_PORT}{path}"
        req = urllib.request.Request(url)
        try:
            with self.opener.open(req, timeout=5) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _get_csrf_token(self):
        import re
        status, html_bytes = self._get("/")
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html_bytes.decode("utf-8"))
        return m.group(1) if m else ""

    def _post_json(self, path: str, payload: dict):
        url = f"http://127.0.0.1:{TEST_PORT}{path}"
        data = json.dumps(payload).encode("utf-8")
        csrf_token = self._get_csrf_token()
        headers = {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf_token
        }
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=5) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_health_and_index(self):
        status, data = self._get("/api/health")
        self.assertEqual(status, 200)
        json_data = json.loads(data.decode("utf-8"))
        self.assertEqual(json_data.get("status"), "ok")

        # HTML page rendered with bundled assets
        status, html_bytes = self._get("/")
        self.assertEqual(status, 200)
        html = html_bytes.decode("utf-8")
        self.assertIn("Gaming Zone - Shift Management", html)
        self.assertIn("id=\"financialDashboardView\"", html)
        self.assertIn("PS5 Sessions", html)

    def test_02_bundled_static_assets(self):
        # Bundled Chart.js
        status, chart_bytes = self._get("/static/js/chart.umd.min.js")
        self.assertEqual(status, 200)
        self.assertGreater(len(chart_bytes), 50000)

        # Bundled CSS
        status, css_bytes = self._get("/static/css/style.css?v=20")
        self.assertEqual(status, 200)
        self.assertIn(".fin-kpi-card", css_bytes.decode("utf-8"))

        # Bundled JS
        status, js_bytes = self._get("/static/js/app.js")
        self.assertEqual(status, 200)
        self.assertIn("function showFinancialsView()", js_bytes.decode("utf-8"))

    def test_03_settings_and_local_data_isolation(self):
        # Config route reads settings.json in the sandbox
        status, cfg_bytes = self._get("/api/config")
        self.assertEqual(status, 200)
        cfg = json.loads(cfg_bytes.decode("utf-8"))
        self.assertIn("employees", cfg)
        self.assertIn("ps5_numbers", cfg)
        self.assertEqual(cfg["ps5_numbers"], ["1", "2", "3", "PC"])

        # Start a shift inside the sandbox
        status, start_res = self._post_json("/api/shift/start", {"employee_name": "Rafay"})
        self.assertEqual(status, 200)
        self.assertTrue(start_res.get("success"))
        shift_id = start_res["shift"]["shift_id"]

        # Verify local_data folder was created in the sandbox directory next to the EXE
        sandbox_local_data = os.path.join(TEST_SANDBOX, "local_data")
        self.assertTrue(os.path.exists(sandbox_local_data), "local_data should be created next to the EXE")
        shift_file = os.path.join(sandbox_local_data, f"shift_{shift_id}.json")
        self.assertTrue(os.path.exists(shift_file), f"Shift file {shift_file} should exist in sandbox")

    def test_04_close_shift_and_financial_analytics(self):
        # 1. Get active shift from previous test or start new
        status, sess_bytes = self._get("/api/session")
        sess_data = json.loads(sess_bytes.decode("utf-8"))
        if sess_data.get("active_shift"):
            shift_id = sess_data["active_shift"]["shift_id"]
        else:
            status, start_res = self._post_json("/api/shift/start", {"employee_name": "Rafay"})
            shift_id = start_res["shift"]["shift_id"]

        # 2. Close shift with net payment match
        close_payload = {
            "shift": {
                "shift_id": shift_id,
                "employee_name": "Rafay",
                "date": "2026-08-20",
                "day": "Thursday",
                "shift_name": "Morning",
                "shift_timing": "8:00 AM - 4:00 PM",
                "financial_summary": {
                    "topup": 500,
                    "cafeteria": 300,
                    "morning_pkg": 1000,
                    "nighter_pkg": 0,
                    "ps_sale": 700,
                    "total_expenses": 200,
                    "grand_total": 2500,
                    "cash_received": 2300,
                    "online_payments": 0,
                    "actual_pos_amount": 0,
                    "total_tax_amount": 0
                },
                "morning_packages": [{"pc_name": "PC-1", "hz": "240Hz", "hrs": "3hrs", "amount": 1000}],
                "nighter_packages": [],
                "ps5_sessions": [{"ps_number": "1", "controllers": 2, "start_time": "10:00 AM", "end_time": "11:00 AM", "amount": 700, "duration_hours": 1}],
                "inventory": [{"name": "Monster Energy", "opening_stock": 10, "restock": 0, "closing_stock": 7, "price": 300}],
                "expenses": [{"category": "Cleaning", "amount": 200, "description": "Detergent"}]
            },
            "pin": "1234"
        }
        status, close_res = self._post_json("/api/shift/close", close_payload)
        self.assertEqual(status, 200)
        self.assertTrue(close_res.get("success"))

        # 3. Authenticate Admin and query Financial Analytics endpoint from the EXE
        sandbox_settings = os.path.join(TEST_SANDBOX, "settings.json")
        with open(sandbox_settings) as f:
            sdata = json.load(f)
        sdata.setdefault("admin_pins", {}).pop("Rafay", None)
        with open(sandbox_settings, "w") as f:
            json.dump(sdata, f, indent=2)

        status, set_res = self._post_json("/api/admin/set-pin", {"employee_name": "Rafay", "pin": "1234"})
        status, pin_login_res = self._post_json("/api/admin/verify-pin", {"employee_name": "Rafay", "pin": "1234"})
        admin_token = pin_login_res.get("token")
        self.assertTrue(bool(admin_token), f"Admin login failed: {pin_login_res}")

        # 4. Request Financial Stats from EXE
        url = f"http://127.0.0.1:{TEST_PORT}/api/admin/financial-stats"
        req = urllib.request.Request(url, headers={"X-Admin-Token": admin_token})
        with self.opener.open(req, timeout=5) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            stats = data.get("stats", {})
            kpis = stats.get("kpis", {})
            self.assertGreaterEqual(kpis.get("gross_revenue", 0), 2500)
            self.assertGreaterEqual(kpis.get("total_expenses", 0), 200)
            self.assertGreaterEqual(kpis.get("net_profit", 0), 2300)
            self.assertIn("ps5_consoles", stats)


if __name__ == "__main__":
    unittest.main()
