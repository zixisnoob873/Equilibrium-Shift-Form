import unittest
import os
import sys
import json
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.local_cache import get_all_shifts
from core.analytics import compute_financial_stats, categorize_expense
import server


class TestFinancialStats(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        server.app.config["WTF_CSRF_ENABLED"] = False
        self.client = server.app.test_client()

    def test_expense_categorization(self):
        self.assertEqual(categorize_expense("STING BOTTLE"), "Stock & Inventory")
        self.assertEqual(categorize_expense("Top up balance"), "Account Topup")
        self.assertEqual(categorize_expense("Chai and paratha"), "Food & Refreshment")
        self.assertEqual(categorize_expense("Tissue box & cleaner"), "Cleaning & Supplies")
        self.assertEqual(categorize_expense("PS5 Controller wire repair"), "Maintenance & Hardware")
        self.assertEqual(categorize_expense("Random unexpected expense"), "General / Misc")

    def test_compute_stats_with_local_data(self):
        shifts = get_all_shifts()
        if not shifts:
            print("SKIP: no local_data shifts available on this machine")
            return
        
        stats = compute_financial_stats(shifts)
        self.assertIn("kpis", stats)
        self.assertIn("revenue_streams", stats)
        self.assertIn("payment_methods", stats)
        self.assertIn("timeline", stats)
        self.assertIn("shift_comparison", stats)
        self.assertIn("employee_performance", stats)
        self.assertIn("inventory_leaderboard", stats)
        self.assertIn("expense_categories", stats)

        kpis = stats["kpis"]
        self.assertEqual(kpis["total_shifts"], len(shifts))
        self.assertGreater(kpis["gross_revenue"], 0)
        self.assertAlmostEqual(kpis["net_profit"], kpis["gross_revenue"] - kpis["total_expenses"], delta=0.01)

        # Verification of revenue stream sum matching gross revenue
        rev_streams = stats["revenue_streams"]
        stream_sum = (
            rev_streams["morning_pkg_total"]
            + rev_streams["nighter_pkg_total"]
            + rev_streams["ps5_total"]
            + rev_streams["cafeteria_sale"]
            + rev_streams["topup_sale"]
        )
        self.assertAlmostEqual(kpis["gross_revenue"], stream_sum, delta=0.01)

    def test_date_and_filter_constraints(self):
        shifts = get_all_shifts()
        if not shifts:
            return

        # Pick an exact date from the first shift
        test_date = shifts[0].date
        filtered_stats = compute_financial_stats(shifts, start_date=test_date, end_date=test_date)
        
        for t in filtered_stats["timeline"]:
            self.assertEqual(t["date"], test_date)

    def test_admin_api_endpoint_auth(self):
        # 1. Unauthenticated request -> 401
        res = self.client.get("/api/admin/financial-stats")
        self.assertEqual(res.status_code, 401)
        data = json.loads(res.data)
        self.assertFalse(data["success"])

        # 2. Authenticated request via valid admin session
        token = server._create_admin_session("Rafay")
        res = self.client.get("/api/admin/financial-stats", headers={"X-Admin-Token": token})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["admin"], "Rafay")
        self.assertIn("stats", data)
        self.assertIn("kpis", data["stats"])

    def test_empty_shifts_handling(self):
        stats = compute_financial_stats([])
        self.assertEqual(stats["kpis"]["total_shifts"], 0)
        self.assertEqual(stats["kpis"]["gross_revenue"], 0.0)
        self.assertEqual(stats["kpis"]["net_profit"], 0.0)
        self.assertEqual(stats["kpis"]["total_expenses"], 0.0)
        self.assertEqual(stats["timeline"], [])
        self.assertEqual(stats["inventory_leaderboard"], [])
        self.assertEqual(stats["expenses"], [])

    def test_null_defensive_coercion(self):
        # Create a mock shift with None in fields
        from core.models import ShiftData, PackageEntry, PS5Session, InventoryItem, ExpenseEntry
        bad_shift = ShiftData(
            shift_id="test0001",
            date="2026-08-20",
            day="Thursday",
            shift_name="Morning",
            employee_name="Test Operator",
            opened_at=None,
            closed_at=None,
            grand_total=None,
            total_expenses=None,
            morning_packages=[PackageEntry(pc_name=None, amount=None, hz=None, hrs=None)],
            ps5_sessions=[PS5Session(ps_number=None, controllers=None, duration_hours=None, amount=None)],
            inventory=[InventoryItem(name=None, opening_stock=None, restock_qty=None, closing_stock=None)],
            expenses=[ExpenseEntry(description=None, amount=None)]
        )
        stats = compute_financial_stats([bad_shift])
        self.assertEqual(stats["kpis"]["total_shifts"], 1)
        self.assertEqual(stats["kpis"]["gross_revenue"], 0.0)
        self.assertEqual(stats["kpis"]["total_expenses"], 0.0)



if __name__ == "__main__":
    unittest.main()
