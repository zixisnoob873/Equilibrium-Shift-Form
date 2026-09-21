import os
import sys
import time
import socket
import unittest
import urllib.request
import json
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from launcher import (
    find_python_executable, is_port_in_use,
    ServerProcessManager, UpdateWorker
)


class TestLauncherUtils(unittest.TestCase):
    def test_find_python_executable(self):
        py_exe = find_python_executable()
        self.assertTrue(os.path.isfile(py_exe), f"Python exe not found: {py_exe}")
        self.assertTrue(py_exe.lower().endswith(".exe") or "python" in py_exe.lower())

    def test_is_port_in_use_with_bound_socket(self):
        # Bind a temporary socket on localhost and verify is_port_in_use reports True
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(is_port_in_use(port))
        finally:
            s.close()

    def test_is_port_in_use_with_unused_port(self):
        # Pick a free port, close it, and check that is_port_in_use reports False
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertFalse(is_port_in_use(port))


class TestServerProcessManager(unittest.TestCase):
    def test_dev_mode_environment_configuration(self):
        """Verifies that start_server in Dev Mode sets port 5001 and isolates dev data."""
        mgr = ServerProcessManager()
        # Mock subprocess.Popen to inspect the environment passed to it without spawning
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = None
            mock_popen.return_value = mock_proc

            started = mgr.start_server(dev_mode=True)
            self.assertTrue(started)
            self.assertEqual(mgr.port, 5001)
            self.assertTrue(mgr.dev_mode)

            # Check environment variables passed to popen
            _, kwargs = mock_popen.call_args
            env = kwargs.get("env", {})
            self.assertEqual(env.get("PORT"), "5001")
            self.assertEqual(env.get("BASE_URL"), "http://localhost:5001")
            self.assertEqual(env.get("DISABLE_SHEETS_SYNC"), "1")
            self.assertEqual(env.get("FLASK_DEBUG"), "1")
            self.assertIn("local_data_dev", env.get("LOCAL_DATA_DIR", ""))

    def test_production_mode_environment_configuration(self):
        """Verifies that start_server in Production Mode sets port 5000 and standard data dir."""
        mgr = ServerProcessManager()
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = None
            mock_popen.return_value = mock_proc

            started = mgr.start_server(dev_mode=False)
            self.assertTrue(started)
            self.assertEqual(mgr.port, 5000)
            self.assertFalse(mgr.dev_mode)

            _, kwargs = mock_popen.call_args
            env = kwargs.get("env", {})
            self.assertEqual(env.get("PORT"), "5000")
            self.assertEqual(env.get("BASE_URL"), "http://localhost:5000")
            self.assertIsNone(env.get("DISABLE_SHEETS_SYNC"))
            self.assertEqual(env.get("FLASK_DEBUG"), "0")
            self.assertIn("local_data", env.get("LOCAL_DATA_DIR", ""))


class TestLiveServerOnDevPort5001(unittest.TestCase):
    """
    Live integration test that starts the server strictly on port 5001 in dev mode,
    verifies /api/health responds with 200 OK, and cleanly terminates the server.
    Ensures zero interaction with port 5000.
    """
    def test_live_server_dev_mode_lifecycle(self):
        # Confirm port 5001 is initially free
        self.assertFalse(is_port_in_use(5001), "Port 5001 must be free before test")

        mgr = ServerProcessManager()
        logs = []
        mgr.log_received.connect(lambda msg: logs.append(msg))

        started = mgr.start_server(dev_mode=True, custom_port=5001)
        self.assertTrue(started, "Failed to initiate server startup on port 5001")

        # Wait up to 10 seconds for port 5001 to begin accepting connections
        connected = False
        for _ in range(20):
            time.sleep(0.5)
            if is_port_in_use(5001):
                connected = True
                break

        self.assertTrue(connected, f"Server on port 5001 did not start in time. Logs:\n{chr(10).join(logs)}")

        try:
            # Query /api/health on port 5001
            req = urllib.request.Request("http://localhost:5001/api/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertTrue(data.get("status") in ("healthy", "ok") or "status" in data)

            # Query /api/config and verify response
            req_config = urllib.request.Request("http://localhost:5001/api/config")
            with urllib.request.urlopen(req_config, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                config_data = json.loads(resp.read().decode())
                self.assertIn("employees", config_data)
        finally:
            # Cleanly stop the server
            mgr.stop_server()
            # Verify port 5001 is released
            time.sleep(1)
            self.assertFalse(is_port_in_use(5001), "Port 5001 was not cleanly released after stop_server")


if __name__ == "__main__":
    unittest.main()
