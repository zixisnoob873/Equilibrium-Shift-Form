from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json
from datetime import datetime


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@dataclass
class PackageEntry:
    pc_name: str = ""
    amount: float = 0.0
    hz: str = ""
    hrs: str = ""

    def to_list(self):
        return [self.pc_name, self.amount, self.hz, self.hrs]


@dataclass
class PS5Session:
    ps_number: str = ""
    controllers: int = 2
    start_time: str = ""
    end_time: str = ""
    amount: float = 0.0
    duration_hours: int = 1
    is_extended: bool = False
    row_id: str = ""
    amount_manual: bool = False

    def to_list(self):
        return [self.ps_number, self.controllers, self.start_time, self.end_time, self.amount, self.duration_hours, 1 if self.is_extended else 0, self.row_id, 1 if self.amount_manual else 0]


@dataclass
class InventoryItem:
    name: str = ""
    opening_stock: int = 0
    restock_qty: int = 0
    closing_stock: int = 0

    def to_list(self):
        return [self.name, self.opening_stock, self.restock_qty, self.closing_stock]


@dataclass
class ExpenseEntry:
    description: str = ""
    amount: float = 0.0


@dataclass
class ShiftData:
    shift_id: str = ""
    employee_name: str = ""
    date: str = ""
    day: str = ""
    shift_name: str = ""
    shift_timing: str = ""
    topup_sale: float = 0.0
    cafeteria_sale: float = 0.0
    cash_received: float = 0.0
    online_payments: float = 0.0
    actual_pos_amount: float = 0.0
    total_tax_amount: float = 0.0
    morning_packages: List[PackageEntry] = field(default_factory=list)
    nighter_packages: List[PackageEntry] = field(default_factory=list)
    ps5_sessions: List[PS5Session] = field(default_factory=list)
    inventory: List[InventoryItem] = field(default_factory=list)
    expenses: List[ExpenseEntry] = field(default_factory=list)
    morning_pkg_total: float = 0.0
    nighter_pkg_total: float = 0.0
    ps5_total: float = 0.0
    total_expenses: float = 0.0
    grand_total: float = 0.0
    status: str = "active"
    closed_at: str = ""
    opened_at: str = ""
    inventory_items_snapshot: List[str] = field(default_factory=list)
    form_screenshot_filename: str = ""
    pancafe_screenshot_filename: str = ""
    form_screenshot_url: str = ""
    pancafe_screenshot_url: str = ""
    synced_to_sheets: bool = False
    last_modified: float = 0.0

    def to_dict(self):
        return {
            "shift_id": self.shift_id,
            "employee_name": self.employee_name,
            "date": self.date,
            "day": self.day,
            "shift_name": self.shift_name,
            "shift_timing": self.shift_timing,
            "topup_sale": self.topup_sale,
            "cafeteria_sale": self.cafeteria_sale,
            "cash_received": self.cash_received,
            "online_payments": self.online_payments,
            "actual_pos_amount": self.actual_pos_amount,
            "total_tax_amount": self.total_tax_amount,
            "morning_packages": [[p.pc_name, p.amount, p.hz, p.hrs] for p in self.morning_packages],
            "nighter_packages": [[p.pc_name, p.amount, p.hz, p.hrs] for p in self.nighter_packages],
            "ps5_sessions": [s.to_list() for s in self.ps5_sessions],
            "inventory": [i.to_list() for i in self.inventory],
            "expenses": [[e.description, e.amount] for e in self.expenses],
            "morning_pkg_total": self.morning_pkg_total,
            "nighter_pkg_total": self.nighter_pkg_total,
            "ps5_total": self.ps5_total,
            "total_expenses": self.total_expenses,
            "grand_total": self.grand_total,
            "status": self.status,
            "closed_at": self.closed_at,
            "opened_at": self.opened_at,
            "inventory_items_snapshot": self.inventory_items_snapshot,
            "form_screenshot_filename": self.form_screenshot_filename,
            "pancafe_screenshot_filename": self.pancafe_screenshot_filename,
            "form_screenshot_url": self.form_screenshot_url,
            "pancafe_screenshot_url": self.pancafe_screenshot_url,
            "synced_to_sheets": self.synced_to_sheets,
            "last_modified": self.last_modified
        }

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            return cls()
        obj = cls()
        obj.shift_id = str(data.get("shift_id", ""))
        obj.employee_name = str(data.get("employee_name", ""))
        obj.date = str(data.get("date", ""))
        obj.day = str(data.get("day", ""))
        obj.shift_name = str(data.get("shift_name", ""))
        obj.shift_timing = str(data.get("shift_timing", ""))
        obj.topup_sale = _f(data.get("topup_sale", 0))
        obj.cafeteria_sale = _f(data.get("cafeteria_sale", 0))
        obj.cash_received = _f(data.get("cash_received", 0))
        obj.online_payments = _f(data.get("online_payments", 0))
        obj.actual_pos_amount = _f(data.get("actual_pos_amount", 0))
        obj.total_tax_amount = _f(data.get("total_tax_amount", 0))
        obj.morning_packages = []
        for p in data.get("morning_packages", []) or []:
            if not isinstance(p, (list, tuple)) or len(p) < 1:
                continue
            obj.morning_packages.append(PackageEntry(
                str(p[0]) if p[0] is not None else "",
                _f(p[1]) if len(p) > 1 else 0.0,
                str(p[2]) if len(p) > 2 and p[2] else "",
                str(p[3]) if len(p) > 3 and p[3] else ""
            ))
        obj.nighter_packages = []
        for p in data.get("nighter_packages", []) or []:
            if not isinstance(p, (list, tuple)) or len(p) < 1:
                continue
            obj.nighter_packages.append(PackageEntry(
                str(p[0]) if p[0] is not None else "",
                _f(p[1]) if len(p) > 1 else 0.0,
                str(p[2]) if len(p) > 2 and p[2] else "",
                str(p[3]) if len(p) > 3 and p[3] else ""
            ))
        obj.ps5_sessions = []
        for s in data.get("ps5_sessions", []) or []:
            if not isinstance(s, (list, tuple)):
                continue
            obj.ps5_sessions.append(PS5Session(
                ps_number=str(s[0]) if len(s) > 0 and s[0] else "",
                controllers=_i(s[1], 2) if len(s) > 1 else 2,
                start_time=str(s[2]) if len(s) > 2 and s[2] else "",
                end_time=str(s[3]) if len(s) > 3 and s[3] else "",
                amount=_f(s[4]) if len(s) > 4 else 0.0,
                duration_hours=_i(s[5], 1) if len(s) > 5 else 1,
                is_extended=bool(_i(s[6])) if len(s) > 6 else False,
                row_id=str(s[7]) if len(s) > 7 and s[7] else "",
                amount_manual=bool(_i(s[8])) if len(s) > 8 else False
            ))
        inv_raw = data.get("inventory", []) or []
        obj.inventory = []
        for i in inv_raw:
            if not isinstance(i, (list, tuple)) or len(i) < 1:
                continue
            name = str(i[0]) if i[0] is not None else ""
            if len(i) >= 4:
                opening = _i(i[1]) if len(i) > 1 else 0
                restock = _i(i[2]) if len(i) > 2 else 0
                closing = _i(i[3]) if len(i) > 3 else 0
            else:
                # backward compat: old 3-element [name, closing, restock]
                closing = _i(i[1]) if len(i) > 1 else 0
                restock = _i(i[2]) if len(i) > 2 else 0
                opening = closing + restock
                closing = 0
            obj.inventory.append(InventoryItem(name, opening, restock, closing))
        obj.expenses = []
        for e in data.get("expenses", []) or []:
            if isinstance(e, (list, tuple)) and len(e) > 0:
                obj.expenses.append(ExpenseEntry(str(e[0]) if e[0] is not None else "", _f(e[1]) if len(e) > 1 else 0.0))
        obj.morning_pkg_total = _f(data.get("morning_pkg_total", 0))
        obj.nighter_pkg_total = _f(data.get("nighter_pkg_total", 0))
        obj.ps5_total = _f(data.get("ps5_total", 0))
        obj.total_expenses = _f(data.get("total_expenses", 0))
        obj.grand_total = _f(data.get("grand_total", 0))
        obj.status = str(data.get("status") or "active")
        obj.closed_at = str(data.get("closed_at", ""))
        obj.opened_at = str(data.get("opened_at", ""))
        snap = data.get("inventory_items_snapshot", []) or []
        obj.inventory_items_snapshot = [str(x) for x in snap if x] if isinstance(snap, list) else []
        obj.form_screenshot_filename = str(data.get("form_screenshot_filename", data.get("screenshot_filename", "")))
        obj.pancafe_screenshot_filename = str(data.get("pancafe_screenshot_filename", ""))
        obj.form_screenshot_url = str(data.get("form_screenshot_url", ""))
        obj.pancafe_screenshot_url = str(data.get("pancafe_screenshot_url", ""))
        obj.synced_to_sheets = bool(data.get("synced_to_sheets", False))
        obj.last_modified = _f(data.get("last_modified", 0))
        return obj
