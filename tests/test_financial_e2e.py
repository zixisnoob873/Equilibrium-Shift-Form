import unittest
import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from core.local_cache import get_all_shifts
from core.analytics import compute_financial_stats


class TestFinancialE2E(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        server.app.config["WTF_CSRF_ENABLED"] = False
        self.client = server.app.test_client()

    def test_static_assets_and_html_elements(self):
        # 1. Verify index.html contains all required elements and IDs
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        required_strings = [
            "/static/js/chart.umd.min.js",
            'id="navFinancialsBtn"',
            'id="financialDashboardView"',
            'id="finTrendChart"',
            'id="finStreamsChart"',
            'id="finPaymentsChart"',
            'id="finShiftCompChart"',
            'id="kpiGrossRevenue"',
            'id="kpiTotalExpenses"',
            'id="kpiNetProfit"',
            'id="kpiNetCollected"',
            'id="kpiShiftsCount"',
            'id="finMorningVal"',
            'id="finNighterVal"',
            'id="finPS5TotalBadge"',
            'id="finPS5ConsolesBody"',
            'id="finCafeTotalBadge"',
            'id="finInventoryLeaderboardBody"',
            'id="finExpenseTotalBadge"',
            'id="finExpenseCategoryList"',
            'id="finEmployeeMatrixBody"',
            'id="finExpenseLogBody"',
            'id="finStartDate"',
            'id="finEndDate"',
            'id="finShiftFilter"',
            'id="finEmpFilter"',
            'id="finLoading"',
            'id="finContent"'
        ]
        for s in required_strings:
            self.assertIn(s, html, f"Missing required HTML element/attribute: {s}")

        # 2. Verify static Chart.js file is served
        res_chart = self.client.get("/static/js/chart.umd.min.js")
        self.assertEqual(res_chart.status_code, 200)
        self.assertTrue(len(res_chart.data) > 50000, "Chart.js should be bundled and not empty")

        # 3. Verify static style.css contains financial classes
        res_css = self.client.get("/static/css/style.css")
        self.assertEqual(res_css.status_code, 200)
        css = res_css.get_data(as_text=True)
        self.assertIn(".fin-kpi-card", css)
        self.assertIn(".fin-header-card", css)
        self.assertIn(".fin-chip", css)

        # 4. Verify static app.js contains controller functions
        res_js = self.client.get("/static/js/app.js")
        self.assertEqual(res_js.status_code, 200)
        js = res_js.get_data(as_text=True)
        self.assertIn("function showFinancialsView()", js)
        self.assertIn("function loadFinancialStats()", js)
        self.assertIn("function renderFinancialDashboard(", js)
        self.assertIn("function exportFinancialsToCSV()", js)
        self.assertIn("function setFinancialPreset(", js)

    def test_api_security_and_full_financial_payload(self):
        # 1. Unauthenticated -> 401
        res = self.client.get("/api/admin/financial-stats")
        self.assertEqual(res.status_code, 401)

        # 2. Invalid token -> 401
        res = self.client.get("/api/admin/financial-stats", headers={"X-Admin-Token": "invalid-token-12345"})
        self.assertEqual(res.status_code, 401)

        # 3. Valid Admin token -> 200
        token = server._create_admin_session("Rafay")
        res = self.client.get("/api/admin/financial-stats", headers={"X-Admin-Token": token})
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["admin"], "Rafay")

        stats = data["stats"]
        kpis = stats["kpis"]
        rev = stats["revenue_streams"]
        pm = stats["payment_methods"]
        timeline = stats["timeline"]
        shift_comp = stats["shift_comparison"]
        emp_perf = stats["employee_performance"]
        exp_cats = stats["expense_categories"]

        # Math invariant 1: Net profit = Gross Revenue - Total Expenses
        self.assertAlmostEqual(kpis["net_profit"], kpis["gross_revenue"] - kpis["total_expenses"], delta=0.01)

        # Math invariant 2: Net collected = Cash + Online + POS
        self.assertAlmostEqual(kpis["net_collected"], pm["cash"] + pm["online"] + pm["pos"], delta=0.01)

        # Math invariant 3: Gross revenue = Morning + Nighter + PS5 + Cafe + Topup
        gross_sum = (
            rev["morning_pkg_total"]
            + rev["nighter_pkg_total"]
            + rev["ps5_total"]
            + rev["cafeteria_sale"]
            + rev["topup_sale"]
        )
        self.assertAlmostEqual(kpis["gross_revenue"], gross_sum, delta=0.01)

        # Math invariant 4: Sum of expense categories = Total Expenses
        cat_sum = sum(c["amount"] for c in exp_cats)
        self.assertAlmostEqual(kpis["total_expenses"], cat_sum, delta=0.05)

        # Math invariant 5: Sum of employee gross revenue = Total Gross Revenue
        emp_gross_sum = sum(e["gross_revenue"] for e in emp_perf)
        self.assertAlmostEqual(kpis["gross_revenue"], emp_gross_sum, delta=0.05)

        # Math invariant 6: Sum of timeline gross revenue = Total Gross Revenue
        timeline_gross_sum = sum(t["gross_revenue"] for t in timeline)
        self.assertAlmostEqual(kpis["gross_revenue"], timeline_gross_sum, delta=0.05)

    def test_filter_combinations(self):
        token = server._create_admin_session("Jahanzaib Khan")
        shifts = get_all_shifts()
        if not shifts:
            return

        # 1. Filter by specific shift
        res = self.client.get(
            "/api/admin/financial-stats?shift_name=Morning",
            headers={"X-Admin-Token": token}
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["success"])

        # 2. Filter by employee
        first_emp = shifts[0].employee_name
        res = self.client.get(
            f"/api/admin/financial-stats?employee_name={first_emp}",
            headers={"X-Admin-Token": token}
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["success"])
        for e in data["stats"]["employee_performance"]:
            self.assertEqual(e["name"], first_emp)


if __name__ == "__main__":
    unittest.main()
