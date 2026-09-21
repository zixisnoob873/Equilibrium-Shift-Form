#!/usr/bin/env python3
"""
Gaming Zone Shift Management - Desktop Control Center & Launcher
----------------------------------------------------------------
Provides a modern Windows GUI, background running with System Tray integration,
Development Mode (Port 5001 + isolated data), Git-based Auto-Updater, and live server logs.
"""

import os
import sys
import time
import socket
import shutil
import winreg
import datetime
import threading
import subprocess
import webbrowser
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QSettings, QSize
from PyQt6.QtGui import QIcon, QPixmap, QFont, QAction, QColor, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QTextEdit, QFrame, QSystemTrayIcon,
    QMenu, QMessageBox, QSizePolicy, QLineEdit, QGroupBox
)

# ---------------------------------------------------------------------------
# Paths and Constants
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PNG = os.path.join(ASSETS_DIR, "logo.png")
ICON_ICO = os.path.join(ASSETS_DIR, "icon.ico")

APP_NAME = "Gaming Zone Shift Management"
APP_VERSION = "2.0.0"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "GamingZoneShiftManager"

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def find_python_executable() -> str:
    """Locates a valid Python executable on the system."""
    # 1. Check current running Python executable if not frozen
    if not getattr(sys, "frozen", False):
        if os.path.isfile(sys.executable):
            return sys.executable

    # 2. Check PATH
    py_path = shutil.which("python") or shutil.which("python3")
    if py_path and os.path.isfile(py_path):
        return py_path

    # 3. Check py launcher
    py_launcher = shutil.which("py")
    if py_launcher and os.path.isfile(py_launcher):
        return py_launcher

    # 4. Check known Windows local paths
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        py_candidates = [
            os.path.join(local_app_data, "Programs", "Python", "Python314", "python.exe"),
            os.path.join(local_app_data, "Programs", "Python", "Python313", "python.exe"),
            os.path.join(local_app_data, "Programs", "Python", "Python312", "python.exe"),
            os.path.join(local_app_data, "Programs", "Python", "Python311", "python.exe"),
            os.path.join(local_app_data, "Programs", "Python", "Python310", "python.exe"),
        ]
        for p in py_candidates:
            if os.path.isfile(p):
                return p

    # Fallback to sys.executable
    return sys.executable


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check whether a given TCP port is currently open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def get_windows_autostart() -> bool:
    """Check if the application is registered to run on Windows startup."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_windows_autostart(enable: bool) -> bool:
    """Enable or disable starting the application on Windows boot."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                # If running as executable, point to exe; otherwise python launcher.py
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" --minimized'
                else:
                    py_exe = find_python_executable()
                    script = os.path.abspath(__file__)
                    cmd = f'"{py_exe}" "{script}" --minimized'
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                except FileNotFoundError:
                    pass
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Background Server Process Manager
# ---------------------------------------------------------------------------
class ServerProcessManager(QObject):
    """Manages the backend Flask / Waitress server process."""
    log_received = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)  # status ("running", "stopped", "error", "starting"), details
    process_exited = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.process: Optional[subprocess.Popen] = None
        self.port = 5000
        self.dev_mode = False
        self.start_time: Optional[float] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_requested = False

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_server(self, dev_mode: bool = False, custom_port: Optional[int] = None) -> bool:
        """Starts the server in either Production (5000) or Development (5001) mode."""
        if self.is_running():
            self.stop_server()

        self.dev_mode = dev_mode
        self.port = custom_port if custom_port else (5001 if dev_mode else 5000)
        self._stop_requested = False

        self.status_changed.emit("starting", f"Starting server on port {self.port}...")

        python_exe = find_python_executable()
        server_script = os.path.join(BASE_DIR, "server.py")

        if not os.path.isfile(server_script):
            err_msg = f"server.py not found in {BASE_DIR}"
            self.log_received.emit(f"[ERROR] {err_msg}")
            self.status_changed.emit("error", err_msg)
            return False

        # Prepare environment variables
        env = os.environ.copy()
        env["PORT"] = str(self.port)
        env["BASE_URL"] = f"http://localhost:{self.port}"
        env["PYTHONUNBUFFERED"] = "1"

        if dev_mode:
            env["LOCAL_DATA_DIR"] = os.path.join(BASE_DIR, "local_data_dev")
            env["DISABLE_SHEETS_SYNC"] = "1"
            env["FLASK_DEBUG"] = "1"
            os.makedirs(env["LOCAL_DATA_DIR"], exist_ok=True)
        else:
            env["LOCAL_DATA_DIR"] = os.path.join(BASE_DIR, "local_data")
            env.pop("DISABLE_SHEETS_SYNC", None)
            env["FLASK_DEBUG"] = "0"
            os.makedirs(env["LOCAL_DATA_DIR"], exist_ok=True)

        cmd = [python_exe, server_script]
        self.log_received.emit(f"[*] Launching server: {' '.join(cmd)} (Port: {self.port}, DevMode: {dev_mode})")

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=CREATE_NO_WINDOW
            )
            self.start_time = time.time()

            # Background thread to continuously stream logs
            self._reader_thread = threading.Thread(target=self._stream_output, daemon=True)
            self._reader_thread.start()

            self.status_changed.emit("running", f"Running on http://localhost:{self.port}")
            return True

        except Exception as e:
            err = f"Failed to spawn server process: {str(e)}"
            self.log_received.emit(f"[ERROR] {err}")
            self.status_changed.emit("error", err)
            return False

    def _stream_output(self):
        """Continuously reads stdout from the server subprocess."""
        if not self.process or not self.process.stdout:
            return

        for line in iter(self.process.stdout.readline, ""):
            if line:
                self.log_received.emit(line.rstrip())

        self.process.stdout.close()
        exit_code = self.process.wait()
        self.start_time = None

        if not self._stop_requested:
            self.log_received.emit(f"[*] Server process terminated with exit code {exit_code}")
            self.status_changed.emit("stopped", f"Server stopped (code {exit_code})")
            self.process_exited.emit(exit_code)

    def stop_server(self):
        """Cleanly terminates the server process."""
        if not self.process:
            return

        self._stop_requested = True
        self.status_changed.emit("stopping", "Stopping server...")
        self.log_received.emit("[*] Terminating server process...")

        try:
            pid = self.process.pid
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW
                    )
                else:
                    self.process.kill()
                self.process.wait(timeout=1)
        except Exception as e:
            self.log_received.emit(f"[WARN] Exception while terminating process: {e}")
        finally:
            self.process = None
            self.start_time = None
            self.status_changed.emit("stopped", "Server is stopped.")
            self.log_received.emit("[*] Server stopped cleanly.")


# ---------------------------------------------------------------------------
# Background Git Auto-Updater Worker
# ---------------------------------------------------------------------------
class UpdateWorker(QThread):
    """Performs background Git fetch/pull and pip dependency update."""
    log_message = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, check_only: bool = False):
        super().__init__()
        self.check_only = check_only

    def run(self):
        git_exe = shutil.which("git")
        if not git_exe:
            self.finished.emit(False, "Git is not installed or not in system PATH.")
            return

        git_dir = os.path.join(BASE_DIR, ".git")
        if not os.path.isdir(git_dir):
            self.finished.emit(False, "Current directory is not a Git repository (.git not found).")
            return

        self.log_message.emit("[*] Checking for updates from GitHub...")
        try:
            # 1. Fetch remote
            res = subprocess.run(
                [git_exe, "fetch", "origin", "main"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=20
            )
            if res.returncode != 0:
                err = res.stderr.strip() or res.stdout.strip()
                self.finished.emit(False, f"Git fetch failed: {err}")
                return

            # 2. Check commit diff
            local_commit = subprocess.run(
                [git_exe, "rev-parse", "HEAD"],
                cwd=BASE_DIR, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
            ).stdout.strip()
            remote_commit = subprocess.run(
                [git_exe, "rev-parse", "origin/main"],
                cwd=BASE_DIR, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
            ).stdout.strip()

            if local_commit == remote_commit:
                self.log_message.emit("[*] System is already up to date! (Commit: " + local_commit[:7] + ")")
                self.finished.emit(True, "Already up to date.")
                return

            if self.check_only:
                self.log_message.emit(f"[!] New update available! Local: {local_commit[:7]} -> Remote: {remote_commit[:7]}")
                self.finished.emit(True, f"Update available: {remote_commit[:7]}")
                return

            # 3. Pull latest code
            self.log_message.emit("[*] Pulling latest changes from origin/main...")
            pull_res = subprocess.run(
                [git_exe, "pull", "origin", "main"],
                cwd=BASE_DIR, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=30
            )
            self.log_message.emit(pull_res.stdout.strip())
            if pull_res.returncode != 0:
                self.finished.emit(False, f"Git pull failed: {pull_res.stderr.strip()}")
                return

            # 4. Update dependencies
            req_file = os.path.join(BASE_DIR, "requirements.txt")
            if os.path.isfile(req_file):
                self.log_message.emit("[*] Checking & updating Python packages...")
                py_exe = find_python_executable()
                pip_res = subprocess.run(
                    [py_exe, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
                    cwd=BASE_DIR, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=60
                )
                if pip_res.returncode == 0:
                    self.log_message.emit("[*] Dependencies are up to date.")
                else:
                    self.log_message.emit(f"[WARN] Dependency check notice: {pip_res.stderr.strip()}")

            self.log_message.emit("[*] Update completed successfully!")
            self.finished.emit(True, "Updated successfully to latest version.")

        except Exception as e:
            self.finished.emit(False, f"Update failed: {str(e)}")


# ---------------------------------------------------------------------------
# Stylesheet (Tailwind Slate / Dark Theme matching web app)
# ---------------------------------------------------------------------------
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QFrame#card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 12px;
}

QFrame#headerCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e293b, stop:1 #0f172a);
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 14px;
}

QLabel#titleLabel {
    font-size: 17px;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.5px;
}

QLabel#subtitleLabel {
    font-size: 12px;
    color: #94a3b8;
}

QLabel#statusPill {
    padding: 5px 12px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.5px;
}

QLabel#statusPillRunning {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.3);
}

QLabel#statusPillDev {
    background-color: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.3);
}

QLabel#statusPillStopped {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
}

QPushButton {
    background-color: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #475569;
    border-color: #64748b;
}

QPushButton:pressed {
    background-color: #1e293b;
}

QPushButton#btnPrimary {
    background-color: #0284c7;
    border: 1px solid #38bdf8;
    color: #ffffff;
}

QPushButton#btnPrimary:hover {
    background-color: #0369a1;
}

QPushButton#btnSuccess {
    background-color: #059669;
    border: 1px solid #10b981;
    color: #ffffff;
}

QPushButton#btnSuccess:hover {
    background-color: #047857;
}

QPushButton#btnDanger {
    background-color: #dc2626;
    border: 1px solid #ef4444;
    color: #ffffff;
}

QPushButton#btnDanger:hover {
    background-color: #b91c1c;
}

QPushButton#btnLink {
    background: transparent;
    border: none;
    color: #38bdf8;
    text-align: left;
    padding: 0;
    font-weight: 600;
    text-decoration: underline;
}

QPushButton#btnLink:hover {
    color: #7dd3fc;
}

QCheckBox {
    color: #f8fafc;
    spacing: 8px;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #1e293b;
}

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
    image: none;
}

QTextEdit#logViewer {
    background-color: #020617;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    border-radius: 6px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
    padding: 8px;
}

QScrollBar:vertical {
    border: none;
    background: #0f172a;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Control Center")
        self.setMinimumSize(780, 680)
        self.resize(840, 720)

        # Settings
        self.settings = QSettings("GamingZone", "ShiftManagerLauncher")
        self.minimize_to_tray_enabled = self.settings.value("minimize_to_tray", True, type=bool)
        self.dev_mode_enabled = self.settings.value("dev_mode", False, type=bool)
        self.is_quitting = False

        # Core Managers
        self.server_mgr = ServerProcessManager()
        self.update_worker: Optional[UpdateWorker] = None

        # Window Icon
        if os.path.isfile(ICON_ICO):
            self.app_icon = QIcon(ICON_ICO)
        elif os.path.isfile(LOGO_PNG):
            self.app_icon = QIcon(LOGO_PNG)
        else:
            self.app_icon = self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)

        self.setWindowIcon(self.app_icon)

        # Setup UI & System Tray
        self._init_ui()
        self._init_system_tray()
        self._connect_signals()

        # Uptime Timer
        self.uptime_timer = QTimer(self)
        self.uptime_timer.timeout.connect(self._update_uptime)
        self.uptime_timer.start(1000)

        # Initialize in Stopped state (server launches only when user clicks Start)
        self._on_server_status_changed("stopped", "Click 'Start Server' to launch.")
        self._append_log("[*] Gaming Zone Shift Management ready. Click 'Start Server' to launch.")

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 1. Header Card
        header_card = QFrame()
        header_card.setObjectName("headerCard")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(12, 10, 12, 10)

        # Logo / Icon
        logo_label = QLabel()
        if os.path.isfile(LOGO_PNG):
            pix = QPixmap(LOGO_PNG).scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pix)
        else:
            logo_label.setPixmap(self.app_icon.pixmap(44, 44))
        header_layout.addWidget(logo_label)

        # Title / Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel(APP_NAME.upper())
        title_label.setObjectName("titleLabel")
        subtitle_label = QLabel(f"Server Manager & System Tray Controller • Version {APP_VERSION}")
        subtitle_label.setObjectName("subtitleLabel")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        # Status Pill
        self.status_pill = QLabel("INITIALIZING")
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("class", "statusPillStopped")
        header_layout.addWidget(self.status_pill)

        main_layout.addWidget(header_card)

        # 2. Status & Details Card
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setSpacing(10)

        # Row 1: URL & Port info
        url_row = QHBoxLayout()
        url_lbl_title = QLabel("Server URL:")
        url_lbl_title.setStyleSheet("color: #94a3b8; font-weight: 600;")
        self.btn_url = QPushButton("http://localhost:5000")
        self.btn_url.setObjectName("btnLink")
        self.btn_url.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_url.clicked.connect(self._open_in_browser)

        url_row.addWidget(url_lbl_title)
        url_row.addWidget(self.btn_url)
        url_row.addStretch()

        # PID & Uptime
        self.lbl_pid = QLabel("PID: -")
        self.lbl_pid.setStyleSheet("color: #94a3b8;")
        self.lbl_uptime = QLabel("Uptime: 00:00:00")
        self.lbl_uptime.setStyleSheet("color: #94a3b8;")
        url_row.addWidget(self.lbl_pid)
        url_row.addSpacing(16)
        url_row.addWidget(self.lbl_uptime)

        status_layout.addLayout(url_row)

        # Row 2: Mode & Sheets Sync Status
        mode_row = QHBoxLayout()
        self.lbl_mode = QLabel("Mode: Production")
        self.lbl_mode.setStyleSheet("color: #38bdf8; font-weight: 600;")
        self.lbl_sheets_status = QLabel("Sheets Sync: Active")
        self.lbl_sheets_status.setStyleSheet("color: #10b981; font-weight: 600;")
        mode_row.addWidget(self.lbl_mode)
        mode_row.addSpacing(20)
        mode_row.addWidget(self.lbl_sheets_status)
        mode_row.addStretch()
        status_layout.addLayout(mode_row)

        main_layout.addWidget(status_card)

        # 3. Action Buttons Row
        actions_card = QFrame()
        actions_card.setObjectName("card")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setSpacing(12)

        self.btn_open_browser = QPushButton("🌐 Open Web App")
        self.btn_open_browser.setObjectName("btnPrimary")
        self.btn_open_browser.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_browser.clicked.connect(self._open_in_browser)

        self.btn_restart = QPushButton("🔄 Restart Server")
        self.btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restart.setEnabled(False)
        self.btn_restart.clicked.connect(self._restart_server)

        self.btn_toggle_server = QPushButton("▶️ Start Server")
        self.btn_toggle_server.setObjectName("btnSuccess")
        self.btn_toggle_server.setStyleSheet("background-color: #059669; border: 1px solid #10b981; color: #ffffff;")
        self.btn_toggle_server.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_server.clicked.connect(self._toggle_server)

        self.btn_update = QPushButton("⬆️ Check for Updates")
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.clicked.connect(self._check_or_do_update)

        actions_layout.addWidget(self.btn_open_browser, 2)
        actions_layout.addWidget(self.btn_restart, 1)
        actions_layout.addWidget(self.btn_toggle_server, 1)
        actions_layout.addWidget(self.btn_update, 1)

        main_layout.addWidget(actions_card)

        # 4. Settings & Options
        options_card = QFrame()
        options_card.setObjectName("card")
        options_layout = QVBoxLayout(options_card)
        options_layout.setSpacing(8)

        # Dev Mode Checkbox
        dev_box = QHBoxLayout()
        self.chk_dev_mode = QCheckBox("Enable Development Mode (Port 5001)")
        self.chk_dev_mode.setChecked(self.dev_mode_enabled)
        self.chk_dev_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_dev_mode.toggled.connect(self._on_dev_mode_toggled)

        dev_desc = QLabel("Isolates dev data (local_data_dev) & leaves Port 5000 production server untouched")
        dev_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")

        dev_box.addWidget(self.chk_dev_mode)
        dev_box.addSpacing(10)
        dev_box.addWidget(dev_desc)
        dev_box.addStretch()
        options_layout.addLayout(dev_box)

        # General Preferences Row
        pref_row = QHBoxLayout()
        self.chk_minimize_tray = QCheckBox("Minimize to system tray on close [X]")
        self.chk_minimize_tray.setChecked(self.minimize_to_tray_enabled)
        self.chk_minimize_tray.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_minimize_tray.toggled.connect(self._on_minimize_tray_toggled)

        self.chk_autostart = QCheckBox("Start automatically with Windows")
        self.chk_autostart.setChecked(get_windows_autostart())
        self.chk_autostart.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_autostart.toggled.connect(self._on_autostart_toggled)

        pref_row.addWidget(self.chk_minimize_tray)
        pref_row.addSpacing(24)
        pref_row.addWidget(self.chk_autostart)
        pref_row.addStretch()
        options_layout.addLayout(pref_row)

        main_layout.addWidget(options_card)

        # 5. Live Server Logs Console
        logs_card = QFrame()
        logs_card.setObjectName("card")
        logs_layout = QVBoxLayout(logs_card)
        logs_layout.setSpacing(8)

        # Header for logs
        logs_header = QHBoxLayout()
        logs_title = QLabel("Server Console & Live Output")
        logs_title.setStyleSheet("font-weight: 600; color: #cbd5e1;")

        self.chk_autoscroll = QCheckBox("Auto-scroll")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.setStyleSheet("font-size: 11px; color: #94a3b8;")

        btn_copy_logs = QPushButton("Copy")
        btn_copy_logs.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        btn_copy_logs.clicked.connect(self._copy_logs)

        btn_clear_logs = QPushButton("Clear")
        btn_clear_logs.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        btn_clear_logs.clicked.connect(self._clear_logs)

        logs_header.addWidget(logs_title)
        logs_header.addStretch()
        logs_header.addWidget(self.chk_autoscroll)
        logs_header.addWidget(btn_copy_logs)
        logs_header.addWidget(btn_clear_logs)

        logs_layout.addLayout(logs_header)

        # Terminal text edit
        self.log_viewer = QTextEdit()
        self.log_viewer.setObjectName("logViewer")
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        logs_layout.addWidget(self.log_viewer)

        main_layout.addWidget(logs_card, 1)

    def _init_system_tray(self):
        """Initializes the Windows System Tray icon and context menu."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.app_icon)
        self.tray_icon.setToolTip(APP_NAME)

        # Context menu
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        self.tray_action_toggle = QAction("▶️ Start Server", self)
        self.tray_action_toggle.triggered.connect(self._toggle_server)
        tray_menu.addAction(self.tray_action_toggle)

        action_open_web = QAction("🌐 Open Web App", self)
        action_open_web.triggered.connect(self._open_in_browser)
        tray_menu.addAction(action_open_web)

        action_show = QAction("🖥️ Show Control Panel", self)
        action_show.triggered.connect(self._show_window)
        tray_menu.addAction(action_show)

        tray_menu.addSeparator()

        self.tray_action_restart = QAction("🔄 Restart Server", self)
        self.tray_action_restart.triggered.connect(self._restart_server)
        self.tray_action_restart.setEnabled(False)
        tray_menu.addAction(self.tray_action_restart)

        action_update = QAction("⬆️ Check for Updates...", self)
        action_update.triggered.connect(self._check_or_do_update)
        tray_menu.addAction(action_update)

        tray_menu.addSeparator()

        action_exit = QAction("❌ Exit Application", self)
        action_exit.triggered.connect(self.quit_application)
        tray_menu.addAction(action_exit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

    def _connect_signals(self):
        self.server_mgr.log_received.connect(self._append_log)
        self.server_mgr.status_changed.connect(self._on_server_status_changed)
        self.server_mgr.process_exited.connect(self._on_server_exited)

    # -----------------------------------------------------------------------
    # Server Operations
    # -----------------------------------------------------------------------
    def _start_server_clicked(self) -> bool:
        """Starts the server based on current settings and port checks."""
        target_port = 5001 if self.chk_dev_mode.isChecked() else 5000

        # Collision detection
        if is_port_in_use(target_port):
            if target_port == 5000:
                reply = QMessageBox.question(
                    self,
                    "Port 5000 In Use",
                    "Port 5000 is currently occupied by another process (e.g. your active production server).\n\n"
                    "Would you like to start in Development Mode on Port 5001 instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.chk_dev_mode.setChecked(True)
                    return self.server_mgr.start_server(dev_mode=True)
                else:
                    self._append_log("[WARN] Server not started: Port 5000 is already in use.")
                    self._on_server_status_changed("stopped", "Port 5000 already in use.")
                    return False
            else:
                self._append_log(f"[WARN] Port {target_port} is already in use.")
                QMessageBox.warning(self, "Port In Use", f"Port {target_port} is already in use by another application.")
                return False

        return self.server_mgr.start_server(dev_mode=self.chk_dev_mode.isChecked())

    def _open_in_browser(self):
        """Opens default browser to the current server URL."""
        port = self.server_mgr.port or (5001 if self.chk_dev_mode.isChecked() else 5000)
        url = f"http://localhost:{port}"
        if not self.server_mgr.is_running():
            reply = QMessageBox.question(
                self,
                "Server Not Running",
                f"The server is currently stopped.\n\nWould you like to start the server on Port {port} now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self._start_server_clicked():
                    QTimer.singleShot(1000, lambda: webbrowser.open(url))
            return

        self._append_log(f"[*] Opening {url} in default browser...")
        webbrowser.open(url)

    def _restart_server(self):
        """Restarts the server process."""
        self._append_log("[*] Restart requested by user.")
        self.server_mgr.start_server(dev_mode=self.chk_dev_mode.isChecked())

    def _toggle_server(self):
        """Starts or stops the server process."""
        if self.server_mgr.is_running():
            self.server_mgr.stop_server()
        else:
            self._start_server_clicked()

    def _on_server_status_changed(self, status: str, details: str):
        """Updates UI status pills, labels, and buttons according to server status."""
        port = self.server_mgr.port or (5001 if self.chk_dev_mode.isChecked() else 5000)
        url = f"http://localhost:{port}"
        self.btn_url.setText(url)

        if status == "running":
            if self.chk_dev_mode.isChecked():
                self.status_pill.setText("🟡 DEV MODE (5001)")
                self.status_pill.setStyleSheet("background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);")
                self.lbl_mode.setText("Mode: Development (Port 5001)")
                self.lbl_mode.setStyleSheet("color: #fbbf24; font-weight: 600;")
                self.lbl_sheets_status.setText("Sheets Sync: Disabled (Safe Dev Mode)")
                self.lbl_sheets_status.setStyleSheet("color: #94a3b8; font-weight: 600;")
            else:
                self.status_pill.setText("🟢 RUNNING (5000)")
                self.status_pill.setStyleSheet("background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);")
                self.lbl_mode.setText("Mode: Production (Port 5000)")
                self.lbl_mode.setStyleSheet("color: #38bdf8; font-weight: 600;")
                self.lbl_sheets_status.setText("Sheets Sync: Active")
                self.lbl_sheets_status.setStyleSheet("color: #10b981; font-weight: 600;")

            self.btn_toggle_server.setText("⏹️ Stop Server")
            self.btn_toggle_server.setObjectName("btnDanger")
            self.btn_toggle_server.setStyleSheet("background-color: #dc2626; border: 1px solid #ef4444; color: #ffffff;")
            self.btn_restart.setEnabled(True)

            if hasattr(self, "tray_action_toggle"):
                self.tray_action_toggle.setText("⏹️ Stop Server")
            if hasattr(self, "tray_action_restart"):
                self.tray_action_restart.setEnabled(True)

            pid = self.server_mgr.process.pid if self.server_mgr.process else "-"
            self.lbl_pid.setText(f"PID: {pid}")

        elif status in ("starting", "stopping"):
            self.status_pill.setText(f"⏳ {status.upper()}")
            self.status_pill.setStyleSheet("background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);")
            self.lbl_pid.setText("PID: -")

        else:  # stopped or error
            self.status_pill.setText("🔴 STOPPED")
            self.status_pill.setStyleSheet("background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);")
            self.btn_toggle_server.setText("▶️ Start Server")
            self.btn_toggle_server.setObjectName("btnSuccess")
            self.btn_toggle_server.setStyleSheet("background-color: #059669; border: 1px solid #10b981; color: #ffffff;")
            self.btn_restart.setEnabled(False)

            if hasattr(self, "tray_action_toggle"):
                self.tray_action_toggle.setText("▶️ Start Server")
            if hasattr(self, "tray_action_restart"):
                self.tray_action_restart.setEnabled(False)

            self.lbl_pid.setText("PID: -")
            self.lbl_uptime.setText("Uptime: 00:00:00")

            if self.chk_dev_mode.isChecked():
                self.lbl_mode.setText("Mode: Development (Port 5001)")
                self.lbl_mode.setStyleSheet("color: #fbbf24; font-weight: 600;")
                self.lbl_sheets_status.setText("Sheets Sync: Disabled (Safe Dev Mode)")
                self.lbl_sheets_status.setStyleSheet("color: #94a3b8; font-weight: 600;")
            else:
                self.lbl_mode.setText("Mode: Production (Port 5000)")
                self.lbl_mode.setStyleSheet("color: #38bdf8; font-weight: 600;")
                self.lbl_sheets_status.setText("Sheets Sync: Active")
                self.lbl_sheets_status.setStyleSheet("color: #10b981; font-weight: 600;")

    def _on_server_exited(self, code: int):
        self._on_server_status_changed("stopped", f"Exited with code {code}")

    def _update_uptime(self):
        """Updates the running uptime counter."""
        if self.server_mgr.is_running() and self.server_mgr.start_time:
            elapsed = int(time.time() - self.server_mgr.start_time)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            self.lbl_uptime.setText(f"Uptime: {hrs:02d}:{mins:02d}:{secs:02d}")

    # -----------------------------------------------------------------------
    # Log Viewer Operations
    # -----------------------------------------------------------------------
    def _append_log(self, text: str):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{now_str}] {text}"
        self.log_viewer.append(formatted)

        if self.chk_autoscroll.isChecked():
            cursor = self.log_viewer.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_viewer.setTextCursor(cursor)

    def _copy_logs(self):
        QApplication.clipboard().setText(self.log_viewer.toPlainText())
        self._append_log("[*] Logs copied to clipboard.")

    def _clear_logs(self):
        self.log_viewer.clear()

    # -----------------------------------------------------------------------
    # Preferences / Toggles
    # -----------------------------------------------------------------------
    def _on_dev_mode_toggled(self, checked: bool):
        self.settings.setValue("dev_mode", checked)
        if self.server_mgr.is_running():
            reply = QMessageBox.question(
                self,
                "Restart Required",
                f"Switching to {'Development Mode (Port 5001)' if checked else 'Production Mode (Port 5000)'} requires restarting the server.\n\n"
                "Would you like to restart now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.server_mgr.start_server(dev_mode=checked)
        else:
            self._on_server_status_changed("stopped", "")

    def _on_minimize_tray_toggled(self, checked: bool):
        self.minimize_to_tray_enabled = checked
        self.settings.setValue("minimize_to_tray", checked)

    def _on_autostart_toggled(self, checked: bool):
        success = set_windows_autostart(checked)
        if not success:
            QMessageBox.warning(self, "Auto-start Error", "Could not update Windows startup registry key.")
            self.chk_autostart.blockSignals(True)
            self.chk_autostart.setChecked(not checked)
            self.chk_autostart.blockSignals(False)

    # -----------------------------------------------------------------------
    # Git Auto-Updater
    # -----------------------------------------------------------------------
    def _check_or_do_update(self):
        if self.update_worker and self.update_worker.isRunning():
            return

        self.btn_update.setEnabled(False)
        self.btn_update.setText("Checking...")
        self._append_log("[*] Starting update check...")

        self.update_worker = UpdateWorker(check_only=False)
        self.update_worker.log_message.connect(self._append_log)
        self.update_worker.finished.connect(self._on_update_finished)
        self.update_worker.start()

    def _on_update_finished(self, success: bool, message: str):
        self.btn_update.setEnabled(True)
        self.btn_update.setText("⬆️ Check for Updates")

        if success:
            if "Already up to date" in message:
                QMessageBox.information(self, "Updates", "Gaming Zone Shift Management is already up to date!")
            else:
                self.tray_icon.showMessage("Update Successful", "System updated. Restarting server...", QSystemTrayIcon.MessageIcon.Information, 4000)
                self._restart_server()
                QMessageBox.information(self, "Update Successful", "Updated to latest version! Server restarted.")
        else:
            QMessageBox.warning(self, "Update Notice", message)

    # -----------------------------------------------------------------------
    # System Tray & Window Lifecycle
    # -----------------------------------------------------------------------
    def _on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_window()

    def _show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        """Intercepts window [X] to minimize to system tray unless quitting."""
        if self.minimize_to_tray_enabled and not self.is_quitting:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                APP_NAME,
                "Server is still running in background. Right-click this tray icon to restore or exit.",
                QSystemTrayIcon.MessageIcon.Information,
                2500
            )
        else:
            self.quit_application()
            event.accept()

    def quit_application(self):
        """Stops server and terminates the whole application."""
        self.is_quitting = True
        self._append_log("[*] Exiting application...")
        self.server_mgr.stop_server()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        QApplication.quit()


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()

    # If launched with --minimized flag (e.g. from Windows boot), don't show window initially
    if "--minimized" not in sys.argv:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
