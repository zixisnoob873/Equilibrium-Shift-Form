"""
Test suite verifying that packages with identical prices but distinct Hz/duration
tiers are handled correctly without collision across serialization, shift close,
and analytics aggregation.
"""
import sys
import os
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["WTF_CSRF_ENABLED"] = "False"
import server
import core.local_cache as lc
import config
from core.models import ShiftData, PackageEntry
from core.analytics import compute_financial_stats


class TestPackageCollision(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_data_dir = config.LOCAL_DATA_DIR
        self.orig_lc_dir = lc.LOCAL_DATA_DIR
        config.LOCAL_DATA_DIR = self.tmp_dir
        lc.LOCAL_DATA_DIR = self.tmp_dir
        server.LOCAL_DATA_DIR = self.tmp_dir
        server.shift_manager.current_shift = None
        server.shift_manager.sheets.is_ready = lambda: False
        server.app.config["TESTING"] = True
        server.app.config["WTF_CSRF_ENABLED"] = False
        self.client = server.app.test_client()

    def tearDown(self):
        config.LOCAL_DATA_DIR = self.orig_data_dir
        lc.LOCAL_DATA_DIR = self.orig_lc_dir
        server.LOCAL_DATA_DIR = self.orig_data_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_same_price_packages_serialization_and_analytics(self):
        # 1. Start a shift
        res = self.client.post("/api/shift/start", json={
            "employee_name": "Rafay",
            "date": "2026-08-29",
            "day": "Saturday",
            "shift_name": "Morning",
            "shift_timing": "10AM - 6PM"
        })
        self.assertEqual(res.status_code, 200)
        shift_data = res.get_json()["shift"]
        shift_id = shift_data["shift_id"]
        last_modified = shift_data["last_modified"]

        # 2. Auto-save shift with two packages of identical price (1600) but different tiers
        pkg_payload = {
            "shift": {
                "shift_id": shift_id,
                "last_modified": last_modified,
                "employee_name": "Rafay",
                "date": "2026-08-29",
                "day": "Saturday",
                "shift_name": "Morning",
                "shift_timing": "10AM - 6PM",
                "morning_packages": [
                    {"pc_name": "PC #1", "amount": 1600.0, "hz": "260Hz", "hrs": "8hrs"},
                    {"pc_name": "PC #2", "amount": 1600.0, "hz": "320Hz", "hrs": "6hrs"}
                ],
                "nighter_packages": [],
                "financial_summary": {
                    "topup": 0, "cafeteria": 0, "morning_pkg": 3200.0, "nighter_pkg": 0,
                    "ps_sale": 0, "total_expenses": 0, "grand_total": 3200.0,
                    "cash_received": 3200.0, "online_payments": 0, "actual_pos_amount": 0, "total_tax_amount": 0
                }
            }
        }
        res = self.client.post("/api/shift/auto-save", json=pkg_payload)
        self.assertEqual(res.status_code, 200)

        # 3. Verify on-disk shift data preserves both distinct packages
        loaded_shift = lc.load_shift(shift_id)
        self.assertIsNotNone(loaded_shift)
        self.assertEqual(len(loaded_shift.morning_packages), 2)
        p1 = loaded_shift.morning_packages[0]
        p2 = loaded_shift.morning_packages[1]
        self.assertEqual(p1.pc_name, "PC #1")
        self.assertEqual(p1.hz, "260Hz")
        self.assertEqual(p1.hrs, "8hrs")
        self.assertEqual(p1.amount, 1600.0)

        self.assertEqual(p2.pc_name, "PC #2")
        self.assertEqual(p2.hz, "320Hz")
        self.assertEqual(p2.hrs, "6hrs")
        self.assertEqual(p2.amount, 1600.0)

        # 4. Verify analytics properly isolates each package tier
        stats = compute_financial_stats([loaded_shift])
        pkg_tiers = {t["tier"]: t for t in stats["package_tiers"]}

        self.assertIn("260Hz 8hrs", pkg_tiers)
        self.assertEqual(pkg_tiers["260Hz 8hrs"]["count"], 1)
        self.assertEqual(pkg_tiers["260Hz 8hrs"]["revenue"], 1600.0)

        self.assertIn("320Hz 6hrs", pkg_tiers)
        self.assertEqual(pkg_tiers["320Hz 6hrs"]["count"], 1)
        self.assertEqual(pkg_tiers["320Hz 6hrs"]["revenue"], 1600.0)


if __name__ == "__main__":
    unittest.main()
