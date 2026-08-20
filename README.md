# Gaming Zone Shift Management

A Flask-based shift management system for gaming zones and internet cafes. Employees clock in/out of shifts, record PC package sales, PS5 sessions, cafeteria/topup sales, track inventory, capture screenshots, and sync everything to Google Sheets.

---

## Quick Start

```bat
pip install -r requirements.txt
python setup_sheets.py
python server.py
```

Then open http://localhost:5000 in your browser.

`start.bat` opens a browser tab automatically. `launch.bat` runs the server only.

---

## Google Sheets Setup

The app syncs closed shifts to Google Sheets. You need a service account and a sheet.

### 1. Enable Google Sheets API

Go to https://console.cloud.google.com/ → create a project → **APIs & Services → Library** → search for **Google Sheets API** → **Enable**.

### 2. Create a Service Account

**APIs & Services → Credentials** → **+ Create Credentials → Service Account** → name it → **Done**. Click the service account → **Keys** tab → **Add Key → Create New Key → JSON**. A file downloads.

### 3. Save credentials

Rename the downloaded JSON to `credentials.json` and place it in the project root.

### 4. Get your Sheet ID

Create a new Google Sheet. From the URL `https://docs.google.com/spreadsheets/d/THIS_PART_HERE/edit`, copy the ID. Create `sheet_id.txt` in the project root and paste only that ID.

### 5. Share the sheet

Open your Google Sheet → **Share**. Find `client_email` in your `credentials.json` (looks like `xxx@xxx.iam.gserviceaccount.com`). Add it as an **Editor**.

### 6. Verify

```bat
python setup_sheets.py
```

### (Optional) ImgBB for Screenshot Hosting

Create `imgbb_key.txt` in the project root with your ImgBB API key. Screenshot URLs will be hosted on ImgBB instead of the local server.

---

## Features

### Shift Lifecycle
- **Start shift** → select employee → form populates with default values
- **Auto-save** every 30 seconds while form is active
- **Close shift** → enter employee PIN → payment validation → screenshot capture → sync to Google Sheets
- **Orphan recovery** — if the server restarts mid-shift, the app detects the orphaned active shift and restores the form

### PC Booking
- Morning and Nighter package bookings via a modal with PC grid
- PCs shown as **green** (available) or **red** (occupied)
- Double-click a red PC to remove its entry from the shift
- PC count is configurable in Settings (default: 27)
- Package hz/hrs auto-matched by price if missing from submission

### PS5 Sessions
- Track sessions with controller count, start/end times, duration
- Auto-calculates pricing based on configured rates:
  - 2 controllers first hour
  - 1 controller first hour
  - 2 controllers extended (per hour)
  - 1 controller extended (per hour)
  - PC per controller per hour

### Inventory
- Items snapshot saved on shift start
- Columns: opening stock, restock, closing stock
- Sold = opening + restock - closing (clamped to 0)
- Last shift's closing stock pre-filled as opening stock for new shift
- Items added/removed mid-shift don't affect active inventory

### Expenses
- Free-form description + amount entries
- Auto-calculated total

### Payment Validation
- Cash received + online payments + POS amount must equal grand total (±0.01)
- Validated both client-side (before submit) and server-side (after submit)

### Screenshots
- **Auto-capture on close** — captures the shift form via `dom-to-image-more`
- **Paste handler** — paste pancafe screenshots from clipboard (Ctrl+V)
- Uploaded to `uploads/` directory
- Organized copies saved to `screenshots/pancafe_screenshot/` and `screenshots/shift_form_screenshot/`
- Non-blocking — shift closes even if screenshot upload fails
- File validation: magic bytes (PNG/JPEG/GIF/WebP/BMP) + Pillow verify + 20MB limit

### Google Sheets Sync
- Two sheets: **Shift Summary** (24 columns) and **Detailed Transactions** (14 columns)
- Sync runs in a background thread on shift close — the close request never blocks
- Dedup by shift_id (primary) or date+employee+total (fallback); transactions deduped by employee+timestamp, all under a lock so concurrent syncs can't double-append
- Batch sync all unsynced shifts on server startup
- Manual sync via Settings UI or API
- Sync errors logged to `local_data/sync_errors.jsonl` (last 100)
- "Clear Sheets" resets local sync flags so the sheet can be rebuilt from local data

### Shift History
- Paginated view of all shifts
- Click to view details (closed shifts require admin auth)
- Last closed shift data shown on form

### Multi-Tab Safety (TabCoordinator)
- Uses `BroadcastChannel` to coordinate editing across browser tabs
- Only one tab can edit a shift at a time
- Heartbeat detection with automatic lock takeover
- Lock modal with "Continue on this tab anyway" option

### Security
- **PIN-based auth** — pbkdf2:sha256 hashed, 4-20 digits
- **Admin sessions** — token-based, 1-hour TTL
- **Rate limiting** — 5 failed attempts per 15 minutes per IP
- **CSRF protection** — Flask-WTF with meta tag + fetch interceptor
- **CSP headers** — Flask-Talisman with restrictive policy
- **Image validation** — magic bytes + Pillow verify + size limits
- **XSS prevention** — `escHtml()` on all user-data interpolations
- **Atomic writes** — tempfile + os.replace for all file saves
- CORS locked to the `BASE_URL` env var (default `http://localhost:5000`)

---

## Project Structure

```
├── server.py                 # Flask app — all routes (~985 lines)
├── config.py                 # Defaults: employees, packages, shifts, pricing
├── requirements.txt          # Python dependencies
├── settings.json             # Runtime overrides (employees, packages, PINs, etc.)
├── credentials.json          # Google service account key
├── sheet_id.txt              # Google Sheet ID
├── imgbb_key.txt             # Optional ImgBB API key
├── setup_sheets.py           # One-time sheet tab creation
├── guide.txt                 # Google Cloud setup instructions
├── start.bat / launch.bat    # Quick-start scripts
├── AGENTS.md                 # Internal development documentation
├── README.md                 # This file
│
├── core/
│   ├── models.py             # Dataclasses: ShiftData, PackageEntry, PS5Session, etc.
│   ├── local_cache.py        # Atomic JSON file I/O for shift persistence
│   ├── shift_manager.py      # Shift orchestration (start/close lifecycle)
│   └── google_sheets.py      # Google Sheets sync + ImgBB screenshot upload
│
├── static/
│   ├── css/style.css         # Dark theme, CSS custom properties (~944 lines)
│   └── js/app.js             # Vanilla JS SPA (~2674 lines)
│
├── templates/
│   └── index.html            # Single HTML template (~652 lines)
│
├── local_data/               # Shift JSON files (shift_{uuid8}.json)
├── uploads/                  # Screenshot files
├── screenshots/              # Organized copies (pancafe/ and form/)
├── assets/                   # Static assets (logo.png)
└── __pycache__/              # Python bytecode cache
```

---

## Configuration

### `settings.json`

Runtime configuration file (auto-created with defaults if missing):

| Key | Type | Description |
|-----|------|-------------|
| `employees` | string[] | Employee names |
| `inventory_items` | string[] | Cafeteria inventory item names |
| `packages` | object[] | `[{hz, hrs, price}]` — PC package tiers |
| `ps5_pricing` | object | `{two_controllers_first_hour, one_controller_first_hour, two_controllers_extended, one_controller_extended, ps5_pc_rate}` |
| `ps5_numbers` | string[] | PS5 station identifiers (e.g. "Left", "Right", "PC") |
| `total_pcs` | number | Total number of PCs available for booking (default: 27) |
| `admin_users` | string[] | Admin names who can reset employee PINs (default: Rafay, Jahanzaib Khan) |
| `admin_pins` | object | Hashed admin PINs (not exposed via API) |
| `employee_pins` | object | Hashed employee PINs (not exposed via API) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 5000 | Server port |
| `BASE_URL` | http://localhost:5000 | Public URL for screenshot links |
| `FLASK_SECRET_KEY` | auto-generated | Flask secret key |
| `FLASK_DEBUG` | 0 | Enable debug mode |

---

## API Reference

### Config & Session

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Employees, packages, PS5 pricing, PC count, shifts, current timing |
| GET | `/api/session` | Active/orphaned/last shift info |
| GET | `/api/health` | Health check |

### Shift CRUD

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/shift/start` | Start a new shift (requires employee name) |
| POST | `/api/shift/close` | Close shift (validates PIN, payment match) |
| POST | `/api/shift/auto-save` | Save in-progress state (409 on stale data) |
| GET | `/api/shift/last-closed` | Most recently closed shift |
| GET | `/api/shifts/history?page=1&per_page=100` | Paginated shift history |
| GET | `/api/shifts/:id` | Single shift detail (closed shifts need admin auth) |

### Auth (Admin)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/pin-status` | Check if admin has a PIN set |
| POST | `/api/admin/set-pin` | First-time admin PIN setup |
| POST | `/api/admin/verify-pin` | Admin login → returns session token |
| GET | `/api/admin/session` | Verify admin token is still valid |
| POST | `/api/admin/reset-employee-pin` | Admin resets an employee's PIN |

### Auth (Employee)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/employee/pin-status?name=X` | Check if employee has a PIN |
| POST | `/api/employee/set-pin` | First-time employee PIN setup |
| POST | `/api/employee/verify-pin` | Employee PIN verification for close |

### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Get current config (PINs stripped) |
| POST | `/api/settings` | Update config (requires admin auth) |

### Google Sheets

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sheets/status` | Whether Google Sheets is configured |
| POST | `/api/sheets/sync-all` | Batch-sync all unsynced closed shifts |
| POST | `/api/sheets/sync-shift/:id` | Sync a single shift |
| POST | `/api/sheets/clear` | Clear all sheet data, re-create headers, reset local sync flags |
| GET | `/api/sync-errors` | Last 100 sync errors (admin auth) |

### Screenshots

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload-screenshot` | Upload screenshot (multipart: image + shift_id + type) |
| POST | `/api/screenshots/re-upload/:id` | Re-upload screenshots to sheet |
| GET | `/uploads/:filename` | Serve uploaded screenshot files |
| GET | `/assets/:path` | Serve static assets |

---

## State & Persistence

| State | Location | Survives Restart? |
|-------|----------|:---:|
| Shift data | `local_data/shift_{uuid8}.json` | Yes |
| Settings | `settings.json` | Yes |
| Google credentials | `credentials.json`, `sheet_id.txt` | Yes |
| Sync errors | `local_data/sync_errors.jsonl` | Yes |
| Screenshots | `uploads/`, `screenshots/` | Yes |
| Active shift reference | In-memory (`ShiftManager.current_shift`) | No |
| Admin sessions | In-memory (`ADMIN_SESSIONS` dict) | No |
| Rate limiting | In-memory (`FAILED_ATTEMPTS` dict) | No |
| Tab coordinator | Per-browser (`BroadcastChannel`) | No |

---

## Security Details

- **PIN storage**: `werkzeug.security.generate_password_hash(pin, method='pbkdf2:sha256')`
- **CSRF**: Flask-WTF + monkey-patched `window.fetch` injects `X-CSRFToken` on all non-GET requests
- **CSP**: `default-src 'self'`, script-src allows `cdn.jsdelivr.net`, style-src allows `fonts.googleapis.com`
- **CORS**: Locked to the `BASE_URL` env var (default `http://localhost:5000`)
- **Image upload**: Magic byte validation + Pillow verify + 20MB limit
- **XSS**: `escHtml()` escapes `& < > " '` on all user-data interpolations
- **Rate limiting**: 5 failed PIN attempts per 15 min per IP (in-memory)
- **Atomic writes**: `tempfile.mkstemp()` + `os.replace()` prevents file corruption
- **Server**: Waitress production server by default; falls back to Flask dev server

---

## Known Issues

1. **Drive quota 403** — Basic Google service accounts have zero Drive storage quota. The `_upload_to_drive()` function will 403. Fix: create a shared drive.
2. **State volatility** — Admin sessions, rate limiting counters, and the active shift reference are lost on server restart.
3. **CSS/JS cache busting** — Manual version bumps in `index.html` (`style.css?v=13`, `app.js?v=23`).

---

## Dependencies

| Library | Purpose |
|---------|---------|
| Flask 3.x | Web framework |
| Flask-CORS | CORS headers |
| Flask-WTF | CSRF protection |
| Flask-Talisman | Security headers (CSP) |
| gspread | Google Sheets API |
| google-auth | Service account authentication |
| google-api-python-client | Google API client (transitive dependency) |
| requests | ImgBB uploads |
| waitress | Production WSGI server |
| Pillow | Image validation |

**Frontend CDN:** `dom-to-image-more` (via `cdn.jsdelivr.net`) for screenshot capture.

---

## Requirements

- Python 3.8+
- Modern web browser (Chrome, Firefox, Edge)
- Google account (for Sheets integration, optional)
- ImgBB API key (for remote screenshot hosting, optional)

---

## License

Internal tool — no license specified.
