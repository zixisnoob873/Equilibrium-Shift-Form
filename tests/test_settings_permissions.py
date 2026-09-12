import os
import sys
import unittest
import json
import tempfile
import shutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import server

class TestSettingsPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_settings_file = server.SETTINGS_FILE
        server.SETTINGS_FILE = os.path.join(self.tmp_dir, 'settings.json')
        
        self.initial_data = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Test Employee'],
            'inventory_items': ['Lays', 'Sting', 'Water'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27,
            'admin_pins': {
                'Rafay': 'pbkdf2:sha256:600000'
            }
        }
        with open(server.SETTINGS_FILE, 'w') as f:
            json.dump(self.initial_data, f)
            
        server.app.config['TESTING'] = True
        server.app.config['WTF_CSRF_ENABLED'] = False
        self.client = server.app.test_client()

    def tearDown(self):
        server.SETTINGS_FILE = self.orig_settings_file
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_settings_strips_pins(self):
        res = self.client.get('/api/settings')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertNotIn('admin_pins', data)
        self.assertNotIn('employee_pins', data)
        self.assertIn('inventory_items', data)
        self.assertEqual(data['inventory_items'], ['Lays', 'Sting', 'Water'])

    def test_update_inventory_without_admin_auth_succeeds(self):
        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Test Employee'],
            'inventory_items': ['Water', 'Lays', 'Sting', 'Monster Energy', 'Chocolates'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27
        }
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['inventory_items']), 5)

        with open(server.SETTINGS_FILE, 'r') as f:
            persisted = json.load(f)
        self.assertIn('Monster Energy', persisted['inventory_items'])

    def test_update_packages_without_admin_auth_fails(self):
        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Test Employee'],
            'inventory_items': ['Lays', 'Sting', 'Water'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250},
                {'hz': '360Hz', 'hrs': '3hrs', 'price': 500}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27
        }
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 401)

    def test_update_employees_without_admin_auth_fails(self):
        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Hacker'],
            'inventory_items': ['Lays', 'Sting', 'Water'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27
        }
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 401)

    def test_update_ps5_pricing_without_admin_auth_fails(self):
        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Test Employee'],
            'inventory_items': ['Lays', 'Sting', 'Water'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 999,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27
        }
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 401)

    def test_update_with_valid_admin_token_succeeds(self):
        import time
        token = 'test-token-12345'
        server.ADMIN_SESSIONS[token] = {'name': 'Rafay', 'created_at': time.time()}

        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'New Staff Member'],
            'inventory_items': ['Lays', 'Sting', 'Water'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 120}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 750,
                'one_controller_first_hour': 450,
                'two_controllers_extended': 550,
                'one_controller_extended': 350,
                'ps5_pc_rate': 300
            },
            'ps5_numbers': ['PS5-A', 'PS5-B'],
            'total_pcs': 30
        }
        res = self.client.post('/api/settings', json=payload, headers={'X-Admin-Token': token})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_pcs'], 30)
        self.assertEqual(data['employees'], ['Rafay', 'Jahanzaib Khan', 'New Staff Member'])

    def test_inventory_items_sorted_alphabetically_on_save(self):
        payload = {
            'employees': ['Rafay', 'Jahanzaib Khan', 'Test Employee'],
            'inventory_items': ['Water', 'Apples', 'Sting', 'Bananas', 'Lays'],
            'packages': [
                {'hz': '180Hz', 'hrs': '1hrs', 'price': 100},
                {'hz': '240Hz', 'hrs': '2hrs', 'price': 250}
            ],
            'ps5_pricing': {
                'two_controllers_first_hour': 700,
                'one_controller_first_hour': 400,
                'two_controllers_extended': 500,
                'one_controller_extended': 300,
                'ps5_pc_rate': 250
            },
            'ps5_numbers': ['Left', 'Right', 'PC'],
            'total_pcs': 27
        }
        res = self.client.post('/api/settings', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        expected = ['Apples', 'Bananas', 'Lays', 'Sting', 'Water']
        self.assertEqual(data['inventory_items'], expected)

        # Verify persisted on disk is also sorted
        with open(server.SETTINGS_FILE, 'r') as f:
            persisted = json.load(f)
        self.assertEqual(persisted['inventory_items'], expected)

if __name__ == '__main__':
    unittest.main()
