import re
from typing import List, Optional, Dict, Any
from collections import defaultdict
from .models import ShiftData


def categorize_expense(description: str) -> str:
    """Categorizes an expense description based on common gaming zone keywords."""
    d = (description or "").lower().strip()
    if not d:
        return "Other"
    
    if any(k in d for k in ["stock", "gatorade", "sting", "lays", "pdm", "water", "juice", "drink", "chocolate", "kurkure", "nimko", "slice", "twister", "supercrisp", "bar", "daal", "milo", "nescafe", "redbull"]):
        return "Stock & Inventory"
    elif any(k in d for k in ["topup", "top up", "balance", "recharge", "account"]):
        return "Account Topup"
    elif any(k in d for k in ["tea", "chai", "food", "khana", "lunch", "dinner", "biryani", "roti", "samosa", "snack", "sweet", "milk", "sugar", "patti", "nashta", "paratha"]):
        return "Food & Refreshment"
    elif any(k in d for k in ["tissue", "clean", "soap", "surf", "mop", "bulb", "tape", "dust", "wiper", "broom", "towel", "glass"]):
        return "Cleaning & Supplies"
    elif any(k in d for k in ["repair", "hardware", "controller", "cable", "mouse", "keyboard", "wire", "switch", "headphone", "stand", "plug", "socket", "strip", "fan", "ac", "pc repair"]):
        return "Maintenance & Hardware"
    elif any(k in d for k in ["salary", "advance", "tip", "reward", "wage"]):
        return "Staff & Payroll"
    elif any(k in d for k in ["bill", "electric", "internet", "net", "generator", "diesel", "fuel", "petrol", "rent", "water bill"]):
        return "Utilities & Power"
    else:
        return "General / Misc"


def compute_financial_stats(
    shifts: List[ShiftData],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    shift_name: Optional[str] = None,
    employee_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyzes and aggregates all closed shift records into comprehensive financial metrics,
    charts data, stream breakdowns, inventory movement, and employee performance.
    """
    filtered: List[ShiftData] = []
    
    for s in shifts:
        s_date = (s.date or "").strip()
        if start_date and s_date < start_date:
            continue
        if end_date and s_date > end_date:
            continue
        if shift_name and shift_name.lower() != "all" and s.shift_name.lower() != shift_name.lower():
            continue
        if employee_name and employee_name.lower() != "all" and s.employee_name.lower() != employee_name.lower():
            continue
        filtered.append(s)

    # Sort chronological (oldest to newest for charts)
    filtered.sort(key=lambda s: (s.date or "", s.opened_at or "", s.closed_at or ""))

    total_shifts = len(filtered)
    
    # 1. Executive Summary KPIs
    gross_revenue = 0.0
    total_expenses = 0.0
    morning_pkg_total = 0.0
    nighter_pkg_total = 0.0
    ps5_total = 0.0
    cafeteria_sale = 0.0
    topup_sale = 0.0
    cash_received = 0.0
    online_payments = 0.0
    actual_pos_amount = 0.0
    total_tax_amount = 0.0

    # 2. Analytics Aggregators
    timeline_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "date": "",
        "day": "",
        "gross_revenue": 0.0,
        "expenses": 0.0,
        "net_profit": 0.0,
        "morning_pkgs": 0.0,
        "nighter_pkgs": 0.0,
        "ps5": 0.0,
        "cafe": 0.0,
        "topup": 0.0,
        "shifts_count": 0
    })

    shift_comparison: Dict[str, Dict[str, Any]] = {
        "Morning": {"count": 0, "gross_revenue": 0.0, "expenses": 0.0, "net_profit": 0.0},
        "Evening": {"count": 0, "gross_revenue": 0.0, "expenses": 0.0, "net_profit": 0.0},
        "Night": {"count": 0, "gross_revenue": 0.0, "expenses": 0.0, "net_profit": 0.0},
    }

    emp_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "name": "",
        "shifts_count": 0,
        "gross_revenue": 0.0,
        "expenses": 0.0,
        "net_profit": 0.0,
        "cash_collected": 0.0,
        "online_collected": 0.0,
        "pos_collected": 0.0
    })

    pkg_tiers: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    pc_occupancy: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"morning": 0, "nighter": 0, "total": 0, "revenue": 0.0})
    morning_pkg_count = 0
    nighter_pkg_count = 0

    ps5_consoles: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"sessions": 0, "hours": 0, "revenue": 0.0})
    ps5_controllers: Dict[str, Dict[str, Any]] = {
        "1 Controller": {"sessions": 0, "hours": 0, "revenue": 0.0},
        "2 Controllers": {"sessions": 0, "hours": 0, "revenue": 0.0},
        "3+ Controllers": {"sessions": 0, "hours": 0, "revenue": 0.0},
        "Extended Sessions": {"sessions": 0, "hours": 0, "revenue": 0.0}
    }
    total_ps5_sessions = 0
    total_ps5_hours = 0

    inventory_units_sold: Dict[str, int] = defaultdict(int)
    inventory_restocked: Dict[str, int] = defaultdict(int)

    all_expenses_list: List[Dict[str, Any]] = []
    expense_categories: Dict[str, float] = defaultdict(float)

    peak_shift: Dict[str, Any] = {"shift_id": "", "date": "", "shift_name": "", "employee_name": "", "revenue": 0.0}

    # Iterate shifts
    for s in filtered:
        s_date = s.date or ""
        s_day = s.day or ""
        s_emp = s.employee_name or "Unknown"
        s_name = s.shift_name or "Unknown"

        # Totals
        s_gross = float(s.grand_total or 0.0)
        s_exp = float(s.total_expenses or 0.0)
        s_profit = s_gross - s_exp

        gross_revenue += s_gross
        total_expenses += s_exp
        morning_pkg_total += float(s.morning_pkg_total or 0.0)
        nighter_pkg_total += float(s.nighter_pkg_total or 0.0)
        ps5_total += float(s.ps5_total or 0.0)
        cafeteria_sale += float(s.cafeteria_sale or 0.0)
        topup_sale += float(s.topup_sale or 0.0)
        cash_received += float(s.cash_received or 0.0)
        online_payments += float(s.online_payments or 0.0)
        actual_pos_amount += float(s.actual_pos_amount or 0.0)
        total_tax_amount += float(s.total_tax_amount or 0.0)

        # Peak shift detection
        if s_gross > peak_shift["revenue"]:
            peak_shift = {
                "shift_id": s.shift_id,
                "date": s_date,
                "shift_name": s_name,
                "employee_name": s_emp,
                "revenue": round(s_gross, 2)
            }

        # Daily Timeline
        if s_date:
            day_entry = timeline_map[s_date]
            day_entry["date"] = s_date
            day_entry["day"] = s_day
            day_entry["gross_revenue"] += s_gross
            day_entry["expenses"] += s_exp
            day_entry["net_profit"] += s_profit
            day_entry["morning_pkgs"] += float(s.morning_pkg_total or 0.0)
            day_entry["nighter_pkgs"] += float(s.nighter_pkg_total or 0.0)
            day_entry["ps5"] += float(s.ps5_total or 0.0)
            day_entry["cafe"] += float(s.cafeteria_sale or 0.0)
            day_entry["topup"] += float(s.topup_sale or 0.0)
            day_entry["shifts_count"] += 1

        # Shift Comparison
        normalized_shift_name = "Morning" if "morning" in s_name.lower() else ("Evening" if "evening" in s_name.lower() else ("Night" if "night" in s_name.lower() else s_name))
        if normalized_shift_name not in shift_comparison:
            shift_comparison[normalized_shift_name] = {"count": 0, "gross_revenue": 0.0, "expenses": 0.0, "net_profit": 0.0}
        sc = shift_comparison[normalized_shift_name]
        sc["count"] += 1
        sc["gross_revenue"] += s_gross
        sc["expenses"] += s_exp
        sc["net_profit"] += s_profit

        # Employee Matrix
        emp_entry = emp_map[s_emp]
        emp_entry["name"] = s_emp
        emp_entry["shifts_count"] += 1
        emp_entry["gross_revenue"] += s_gross
        emp_entry["expenses"] += s_exp
        emp_entry["net_profit"] += s_profit
        emp_entry["cash_collected"] += float(s.cash_received or 0.0)
        emp_entry["online_collected"] += float(s.online_payments or 0.0)
        emp_entry["pos_collected"] += float(s.actual_pos_amount or 0.0)

        # Packages Analytics
        for p in (s.morning_packages or []):
            morning_pkg_count += 1
            pc_name = str(p.pc_name or "")
            amt = float(p.amount or 0.0)
            hz = str(p.hz or "")
            hrs = str(p.hrs or "")
            tier_label = f"{hz} {hrs}".strip() or (f"PKR {int(amt)}" if amt else "Standard")
            pkg_tiers[tier_label]["count"] += 1
            pkg_tiers[tier_label]["revenue"] += amt
            if pc_name:
                pc_occupancy[pc_name]["morning"] += 1
                pc_occupancy[pc_name]["total"] += 1
                pc_occupancy[pc_name]["revenue"] += amt

        for p in (s.nighter_packages or []):
            nighter_pkg_count += 1
            pc_name = str(p.pc_name or "")
            amt = float(p.amount or 0.0)
            hz = str(p.hz or "")
            hrs = str(p.hrs or "")
            tier_label = f"{hz} {hrs}".strip() or (f"PKR {int(amt)}" if amt else "Standard")
            pkg_tiers[tier_label]["count"] += 1
            pkg_tiers[tier_label]["revenue"] += amt
            if pc_name:
                pc_occupancy[pc_name]["nighter"] += 1
                pc_occupancy[pc_name]["total"] += 1
                pc_occupancy[pc_name]["revenue"] += amt

        # PS5 Analytics
        for ps in (s.ps5_sessions or []):
            total_ps5_sessions += 1
            dur = int(ps.duration_hours or 1)
            total_ps5_hours += dur
            amt = float(ps.amount or 0.0)
            ps_num = str(ps.ps_number or "Console").strip()
            ctrls = int(ps.controllers or 2)
            is_ext = bool(ps.is_extended)

            ps5_consoles[ps_num]["sessions"] += 1
            ps5_consoles[ps_num]["hours"] += dur
            ps5_consoles[ps_num]["revenue"] += amt

            if is_ext:
                ps5_controllers["Extended Sessions"]["sessions"] += 1
                ps5_controllers["Extended Sessions"]["hours"] += dur
                ps5_controllers["Extended Sessions"]["revenue"] += amt

            if ctrls == 1:
                ps5_controllers["1 Controller"]["sessions"] += 1
                ps5_controllers["1 Controller"]["hours"] += dur
                ps5_controllers["1 Controller"]["revenue"] += amt
            elif ctrls == 2:
                ps5_controllers["2 Controllers"]["sessions"] += 1
                ps5_controllers["2 Controllers"]["hours"] += dur
                ps5_controllers["2 Controllers"]["revenue"] += amt
            else:
                ps5_controllers["3+ Controllers"]["sessions"] += 1
                ps5_controllers["3+ Controllers"]["hours"] += dur
                ps5_controllers["3+ Controllers"]["revenue"] += amt

        # Inventory sold units
        for item in (s.inventory or []):
            item_name = str(item.name or "").strip()
            if not item_name:
                continue
            opening = int(item.opening_stock or 0)
            restock = int(item.restock_qty or 0)
            closing = int(item.closing_stock or 0)
            sold = max(0, opening + restock - closing)
            inventory_units_sold[item_name] += sold
            inventory_restocked[item_name] += restock

        # Expenses
        for exp in (s.expenses or []):
            desc = str(exp.description or "").strip()
            amt = float(exp.amount or 0.0)
            cat = categorize_expense(desc)
            expense_categories[cat] += amt
            all_expenses_list.append({
                "date": s_date,
                "shift": s_name,
                "employee": s_emp,
                "description": desc or "Expense",
                "amount": round(amt, 2),
                "category": cat
            })

    # Sort all expenses reverse chronological
    all_expenses_list.sort(key=lambda x: x["date"], reverse=True)

    # Convert timeline to sorted list
    timeline_list = sorted(list(timeline_map.values()), key=lambda x: x["date"])
    for t in timeline_list:
        t["gross_revenue"] = round(t["gross_revenue"], 2)
        t["expenses"] = round(t["expenses"], 2)
        t["net_profit"] = round(t["net_profit"], 2)
        t["morning_pkgs"] = round(t["morning_pkgs"], 2)
        t["nighter_pkgs"] = round(t["nighter_pkgs"], 2)
        t["ps5"] = round(t["ps5"], 2)
        t["cafe"] = round(t["cafe"], 2)
        t["topup"] = round(t["topup"], 2)

    # Find peak day
    peak_day = {"date": "", "revenue": 0.0}
    for t in timeline_list:
        if t["gross_revenue"] > peak_day["revenue"]:
            peak_day = {"date": t["date"], "revenue": t["gross_revenue"]}

    # Inventory leaderboard
    inventory_leaderboard = []
    for item_name, units in inventory_units_sold.items():
        inventory_leaderboard.append({
            "name": item_name,
            "units_sold": units,
            "restocked": inventory_restocked[item_name]
        })
    inventory_leaderboard.sort(key=lambda x: x["units_sold"], reverse=True)

    # Package tiers list
    tiers_list = []
    for tier_name, data in pkg_tiers.items():
        tiers_list.append({
            "tier": tier_name,
            "count": data["count"],
            "revenue": round(data["revenue"], 2)
        })
    tiers_list.sort(key=lambda x: x["count"], reverse=True)

    # PC occupancy list
    occupancy_list = []
    for pc, data in pc_occupancy.items():
        occupancy_list.append({
            "pc_name": pc,
            "morning": data["morning"],
            "nighter": data["nighter"],
            "total": data["total"],
            "revenue": round(data["revenue"], 2)
        })
    # Natural sort PC #1, PC #2...
    def _pc_sort_key(item):
        m = re.search(r'\d+', item["pc_name"])
        return int(m.group()) if m else 999
    occupancy_list.sort(key=_pc_sort_key)

    # PS5 consoles list
    ps5_consoles_list = []
    for c_name, data in ps5_consoles.items():
        ps5_consoles_list.append({
            "console": c_name,
            "sessions": data["sessions"],
            "hours": data["hours"],
            "revenue": round(data["revenue"], 2)
        })
    ps5_consoles_list.sort(key=lambda x: x["revenue"], reverse=True)

    # PS5 controllers list
    ps5_controllers_list = []
    for ctrl_name, data in ps5_controllers.items():
        ps5_controllers_list.append({
            "type": ctrl_name,
            "sessions": data["sessions"],
            "hours": data["hours"],
            "revenue": round(data["revenue"], 2)
        })

    # Employee list
    emp_list = []
    for emp_name, data in emp_map.items():
        s_count = data["shifts_count"]
        emp_list.append({
            "name": emp_name,
            "shifts_count": s_count,
            "gross_revenue": round(data["gross_revenue"], 2),
            "expenses": round(data["expenses"], 2),
            "net_profit": round(data["net_profit"], 2),
            "cash_collected": round(data["cash_collected"], 2),
            "online_collected": round(data["online_collected"], 2),
            "pos_collected": round(data["pos_collected"], 2),
            "avg_revenue_per_shift": round(data["gross_revenue"] / s_count, 2) if s_count > 0 else 0.0
        })
    emp_list.sort(key=lambda x: x["gross_revenue"], reverse=True)

    # Shift comparison list
    shift_comparison_list = []
    for s_type, data in shift_comparison.items():
        s_count = data["count"]
        shift_comparison_list.append({
            "shift_name": s_type,
            "count": s_count,
            "gross_revenue": round(data["gross_revenue"], 2),
            "expenses": round(data["expenses"], 2),
            "net_profit": round(data["net_profit"], 2),
            "avg_revenue": round(data["gross_revenue"] / s_count, 2) if s_count > 0 else 0.0
        })

    # Expense category list
    expense_categories_list = []
    for cat_name, amt in expense_categories.items():
        expense_categories_list.append({
            "category": cat_name,
            "amount": round(amt, 2),
            "percentage": round((amt / total_expenses * 100), 1) if total_expenses > 0 else 0.0
        })
    expense_categories_list.sort(key=lambda x: x["amount"], reverse=True)

    # Net profit & collected
    net_profit = gross_revenue - total_expenses
    net_collected = cash_received + online_payments + actual_pos_amount

    # Averages
    avg_rev = round(gross_revenue / total_shifts, 2) if total_shifts > 0 else 0.0
    avg_profit = round(net_profit / total_shifts, 2) if total_shifts > 0 else 0.0
    avg_exp = round(total_expenses / total_shifts, 2) if total_shifts > 0 else 0.0

    return {
        "kpis": {
            "total_shifts": total_shifts,
            "gross_revenue": round(gross_revenue, 2),
            "total_expenses": round(total_expenses, 2),
            "net_profit": round(net_profit, 2),
            "net_collected": round(net_collected, 2),
            "cash_received": round(cash_received, 2),
            "online_payments": round(online_payments, 2),
            "actual_pos_amount": round(actual_pos_amount, 2),
            "total_tax_amount": round(total_tax_amount, 2),
            "avg_revenue_per_shift": avg_rev,
            "avg_profit_per_shift": avg_profit,
            "avg_expenses_per_shift": avg_exp,
            "peak_shift": peak_shift,
            "peak_day": peak_day
        },
        "revenue_streams": {
            "morning_pkg_total": round(morning_pkg_total, 2),
            "nighter_pkg_total": round(nighter_pkg_total, 2),
            "ps5_total": round(ps5_total, 2),
            "cafeteria_sale": round(cafeteria_sale, 2),
            "topup_sale": round(topup_sale, 2),
            "morning_pkg_count": morning_pkg_count,
            "nighter_pkg_count": nighter_pkg_count,
            "total_ps5_sessions": total_ps5_sessions,
            "total_ps5_hours": total_ps5_hours
        },
        "payment_methods": {
            "cash": round(cash_received, 2),
            "online": round(online_payments, 2),
            "pos": round(actual_pos_amount, 2),
            "tax": round(total_tax_amount, 2),
            "cash_pct": round((cash_received / net_collected * 100), 1) if net_collected > 0 else 0.0,
            "online_pct": round((online_payments / net_collected * 100), 1) if net_collected > 0 else 0.0,
            "pos_pct": round((actual_pos_amount / net_collected * 100), 1) if net_collected > 0 else 0.0
        },
        "timeline": timeline_list,
        "shift_comparison": shift_comparison_list,
        "employee_performance": emp_list,
        "package_tiers": tiers_list,
        "pc_occupancy": occupancy_list,
        "ps5_consoles": ps5_consoles_list,
        "ps5_controllers": ps5_controllers_list,
        "inventory_leaderboard": inventory_leaderboard,
        "expense_categories": expense_categories_list,
        "expenses": all_expenses_list
    }
