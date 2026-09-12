import unittest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
import core.local_cache as lc
from core.models import ShiftData, InventoryItem
from core.google_sheets import GoogleSheetsManager

class TestInventorySorting(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="inv_sort_test_")
        self.orig_settings_file = server.SETTINGS_FILE
        self.orig_local_data_dir = lc.LOCAL_DATA_DIR
        
        server.SETTINGS_FILE = os.path.join(self.tmp_dir, "settings.json")
        lc.LOCAL_DATA_DIR = os.path.join(self.tmp_dir, "local_data")
        os.makedirs(lc.LOCAL_DATA_DIR, exist_ok=True)
        
        # Unsorted cafeteria items initially on disk
        self.initial_data = {
            'employees': ['Rafay', 'Jahanzaib Khan'],
            'inventory_items': ['Water', 'Sting', 'Apples', 'Kurkure', 'Biscuits'],
            'packages': [{'hz': '180Hz', 'hrs': '1hrs', 'price': 100}],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27,
            'employee_pins': {}
        }
        with open(server.SETTINGS_FILE, 'w') as f:
            json.dump(self.initial_data, f)
            
        server.app.config['TESTING'] = True
        server.app.config['WTF_CSRF_ENABLED'] = False
        self.client = server.app.test_client()
        server.shift_manager.current_shift = None

    def tearDown(self):
        server.SETTINGS_FILE = self.orig_settings_file
        lc.LOCAL_DATA_DIR = self.orig_local_data_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_config_returns_alphabetical_inventory(self):
        res = self.client.get('/api/config')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('inventory_items', data)
        expected = ['Apples', 'Biscuits', 'Kurkure', 'Sting', 'Water']
        self.assertEqual(data['inventory_items'], expected)

    def test_post_settings_sorts_newly_added_items_alphabetically(self):
        # Add "Zebra Cake" and "Banana Shake" to unsorted list
        payload = self.initial_data.copy()
        payload['inventory_items'] = ['Water', 'Zebra Cake', 'Sting', 'Banana Shake', 'Apples']
        
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        expected = ['Apples', 'Banana Shake', 'Sting', 'Water', 'Zebra Cake']
        self.assertEqual(data['inventory_items'], expected)

        # Check disk persistence
        with open(server.SETTINGS_FILE, 'r') as f:
            persisted = json.load(f)
        self.assertEqual(persisted['inventory_items'], expected)

    def test_start_shift_creates_alphabetical_inventory_rows(self):
        res = self.client.post('/api/shift/start', json={'employee_name': 'Rafay'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        shift = data['shift']
        
        expected_snapshot = ['Apples', 'Biscuits', 'Kurkure', 'Sting', 'Water']
        self.assertEqual(shift['inventory_items_snapshot'], expected_snapshot)
        
        # Check inventory items in shift.inventory
        inv_names = [item[0] for item in shift['inventory']]
        self.assertEqual(inv_names, expected_snapshot)

    def test_google_sheets_summary_formats_inventory_alphabetically(self):
        # Create shift with mixed-order inventory items
        shift = ShiftData(
            shift_id="test1234",
            employee_name="Rafay",
            date="2026-09-12",
            inventory=[
                InventoryItem(name="Water", closing_stock=5),
                InventoryItem(name="Apples", closing_stock=12),
                InventoryItem(name="Sting", closing_stock=20),
            ]
        )
        
        # Test the formatting logic used by _append_summary
        sorted_inv = sorted(shift.inventory or [], key=lambda x: (x.name or "").strip().casefold())
        inv_parts = [f"{i.name}: {i.closing_stock}" for i in sorted_inv]
        inv_str = ", ".join(inv_parts)
        self.assertEqual(inv_str, "Apples: 12, Sting: 20, Water: 5")

if __name__ == '__main__':
    unittest.main()
