# AGENTS.md — Gaming Zone Shift Management

## Quick start
```bat
pip install -r requirements.txt
python setup_sheets.py        # one-time: creates sheet tabs
python server.py              # http://localhost:5000
```
`start.bat` also opens a browser tab; `launch.bat` runs the server only. Google Sheets setup steps in `guide.txt`.

## Architecture
- **Backend**: single Flask app in `server.py` (~1093 lines). No blueprints, no app factory, no dependency injection.
- **Core** (`core/`): `models.py` (dataclasses), `shift_manager.py` (start/close orchestration), `local_cache.py` (atomic JSON file I/O), `google_sheets.py` (Sheets + ImgBB sync).
- **Frontend**: vanilla JS (`static/js/app.js`, 3415 lines, no framework), single template (`templates/index.html`, 749 lines), dark theme CSS (`static/css/style.css`, 1149 lines, CSS custom properties, no preprocessor).
- **Config**: defaults in `config.py`, overrides in `settings.json` (employees, inventory, packages, hashed PINs, ps5_pricing, ps5_numbers, total_pcs, admin_users). Both merged at runtime via `get_effective_config()`. `total_pcs` (default 27) drives PC-number dropdown lengths; validated/clamped 1–500 on save and persisted.
- **State**: shifts stored as `local_data/shift_{8-char-uuid}.json`; each JSON file is a `ShiftData.to_dict()` output. Shift IDs are first 8 chars of `uuid.uuid4()`.

## Shift lifecycle
`active` → `close_shift()` → `closed`
- `close_shift()` in `shift_manager.py` saves locally (atomic `tempfile.mkstemp` + `os.replace`), then **spawns a background daemon thread** (`_sync_closed_shift`) that runs `self.sheets.sync_shift_sync(shift)`. The close request never blocks on the sync. Sync failures logged to `sync_errors.jsonl` (last 100 available via `/api/sync-errors`) and retried by `_startup_sync()` / Sync All.
- `_startup_sync()` runs on server boot in a daemon thread to sync unsynced closed shifts. Boot also starts `_cleanup_orphan_uploads()` (deletes `uploads/` files older than 30 days not referenced by any shift) and `_sweep_stale_active_shifts()` (if a crash left multiple active shift files, keeps the most recently opened, closes leftovers older than 7 days).
- **Double-close prevention**: `_closing_ids: Set[str]` — `mark_closing()` at try-entry, `unmark_closing()` in `finally`. Returns 429 if shift is already closing.
- **Stale auto-save rejection**: `last_modified: float` (`time.time()`) on every save. Auto-save endpoint returns 409 if client timestamp < server timestamp (strict `<`). The 200 response echoes `last_modified`, and the client stores it on `currentShift.last_modified` so the next save passes. Auto-save also returns 409 "Shift is being closed" while a close is in flight (`is_closing`), and 409 "Shift is no longer active" for closed shifts.
- **Close identity merge**: temporal identity fields (date, day, shift, opened_at, status) always come from the stored active shift (`load_shift(shift_id)`, fallback `current_shift`) — never from the close payload, so a stale tab can't rewrite when the shift belongs to. The exception is `employee_name`: it is always overwritten from the close payload (the authenticated closing operator, PIN-verified client-side before close), so the sheet credits whoever actually closed the shift. A same-operator close is a no-op. Only live form data (financials, packages, PS5, inventory, expenses, screenshots) is merged in.
- **PS5 session schema**: 9-slot list `[ps_number, controllers, start, end, amount, duration, is_extended, row_id, amount_manual]`. `row_id` persists the client-side registry id (alarm identity across reloads); `amount_manual` marks hand-entered amounts that reload must not recompute. `ShiftData.from_dict` is defensive (`_f`/`_i` coercion helpers, non-list guards, backward-compatible with legacy 3-element inventory and <9-slot PS5 entries).
- **Payment validation**: `cash_received + online_payments + actual_pos_amount` must equal `grand_total - total_expenses` (net collectable) within 0.01. Both client-side (pre-submit) and server-side (post-submit) validation.
- **Package hz/hrs fallback**: if submitted package entries have empty hz/hrs (legacy clients), server does `_lookup_package_by_amount()` which matches price against current `settings.json` packages.
- **Orphan recovery**: `GET /api/session` checks `shift_manager.current_shift` first, then falls back to `get_last_active_shift()` scanning all JSON files for `status == "active"`. Frontend shows recovery toast and repopulates the form.

## State volatility (server restart)
Everything in memory is **lost on restart**:
- Admin sessions (`ADMIN_SESSIONS` dict — token TTL 3600s)
- Rate limiting counters (`FAILED_ATTEMPTS` — 5 per 15 min per IP)
- ShiftManager.current_shift reference
- Tab coordinator state (BroadcastChannel, per-browser)
- Only `local_data/shift_*.json` files and `sync_errors.jsonl` persist across restarts.

## Google Sheets / Drive
- Config files in project root: `credentials.json` (service account key), `sheet_id.txt` (sheet ID), `imgbb_key.txt` (optional ImgBB API key).
- Sheet tabs: `"Shift Summary"` (24 columns) and `"Detailed Transactions"` (14 columns). Constants `SUMMARY_SHEET_NAME` / `TRANSACTIONS_SHEET_NAME` in `core/google_sheets.py`.
- **Concurrency safety**: all dedup check + append pairs run under `GoogleSheetsManager._sync_lock` (threading.Lock), so background close sync, startup sync, and Sync All can never double-append — even when they race on the same shift.
- Dedup (summary, primary): `shift_id` match in column A. Dedup (summary, fallback): `date|employee_name|grand_total` matching by reading all values — also compares `closed_at` when the sheet has a Closed At column, so two legitimate same-day, same-employee, same-total shifts are never confused.
- Dedup (transactions): each shift's transaction rows share one timestamp, so `(employee_name, closed_at)` (fallback `opened_at`) identifies the block; retries skip if already present.
- **Partial-failure recovery**: if a previous sync appended the summary row but failed before transactions, `_sync_closed_shifts` (Sync All) and `sync_shift_sync` re-append the missing transaction rows (idempotent) instead of treating the shift as fully synced.
- Screenshot URLs: uploaded to ImgBB if API key configured, otherwise `BASE_URL/uploads/{filename}` local fallback.
- Summary columns: "Pancafe Screenshot" (col 23), "Form Screenshot" (col 24). `re_upload_screenshots` endpoint locates these columns by header name (fallback 23/24).
- History UI: the 📤 Sync button renders **disabled** for shifts where `synced_to_sheets` is true (`_renderHistoryItem`); Sync All skips synced shifts server-side.
- Transactions columns: "Timestamp" (col 14).
- Footer polls `/api/sheets/status` every 5s via `startAutoRefresh()`.
- **Known Drive quota issue**: basic service accounts have zero Drive storage quota. `_upload_to_drive()` will 403. Fix: create a shared drive.
- To reset: use Settings UI "Clear Sheets" or delete both worksheets (they auto-recreate on next sync). **Clear Sheets also resets `synced_to_sheets=False` on all closed shifts**, so Sync All / startup sync rebuild the sheet from local data.

## Security & Production
- **CSRF**: Flask-WTF with `csrf_token()` meta tag. `window.fetch` monkey-patched to inject `X-CSRFToken` on all non-GET. App accepts both `X-CSRFToken` and `X-CSRF-Token` (`WTF_CSRF_HEADERS`). Token never expires (`WTF_CSRF_TIME_LIMIT = None`).
- **CORS**: Locked to `origins: [BASE_URL env var, default "http://localhost:5000"]`.
- **CSP**: Flask-Talisman — `default-src 'self'`, `script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net`, `style-src 'self' 'unsafe-inline' fonts.googleapis.com`, `font-src fonts.gstatic.com`, `img-src 'self' data:`, `media-src 'self' data:` (required for the embedded `data:` alarm sound), `connect-src 'self'`. `force_https=False`.
- **PIN**: `werkzeug.security.generate_password_hash(pin, method='pbkdf2:sha256')`. Old SHA-256 hashes invalidated (will throw ValueError on check, caught by `_verify_pin()`).
- **Image validation**: magic-byte header check (PNG/JPEG/GIF/WebP/BMP) + Pillow `Image.open()` + `img.verify()`. 20MB limit. Returns 400 on invalid.
- **XSS**: `escHtml()` on all user-data interpolations in history items, package dropdowns, closed shift view, settings lists.
- **Server**: Waitress by default (`127.0.0.1:{PORT}`); falls back to Flask dev server. Secret key from `FLASK_SECRET_KEY` env var or `secrets.token_hex(32)`.
- **Admin sessions**: token-based, 1-hour TTL. Token in `X-Admin-Token` header, stored in `sessionStorage` at `adminToken`/`adminName`. Admin users in `settings.json` `admin_users` key (defaults: `["Rafay", "Jahanzaib Khan"]`). Only these two can reset employee PINs. Reset-employee-PIN accepts the live admin token first (works on a fresh page), falling back to `admin_name` + `admin_pin` body fields.
- **Rate limiting**: 5 failed PIN attempts per 15-minute window per IP. In-memory only.
- **Settings corruption**: `load_settings()` returns defaults with logged warning on `JSONDecodeError` / `OSError`. Atomic writes via `tempfile.mkstemp` + `os.replace`.

## Custom dropdown (`CustomDropdown` in `app.js`)
- Replaces all `<select>` on DOMContentLoaded via `initCustomDropdowns()`.
- Hidden select gets `class="cd-hidden"` (CSS `display:none`), trigger + menu are flat siblings (no wrapper).
- Menu uses `position: fixed` + viewport `getBoundingClientRect()` to avoid overflow clipping.
- Includes inline search input with keyboard navigation (ArrowUp/Down/Enter/Escape).
- After programmatic `.value = X`, call `syncDropdown(el)` to sync the UI.
- For dynamically added `<select>` rows, call `refreshCustomDropdowns(containerEl)`.
- Exempt with `data-cd-ignore` attribute on the `<select>`.

## Tab coordination (`TabCoordinator`)
- Uses `BroadcastChannel('shift-form-sync')` for multi-tab editing safety.
- Message types: `ALIVE` (2s heartbeat), `PING`/`PONG` (active-tab discovery), `TAKEOVER` (force claim), `ACTIVE` (new active tab), `UNLOAD` (tab closing), `CLOSED` (shift closed).
- Inactive tabs show a lock modal with "Continue on this tab anyway" takeover option.
- Heartbeat + monitor loops detect stale editors (5s timeout on `_lastAlive`).
- Constructor wrapped in `try/catch` — `BroadcastChannel` failure doesn't crash the app.
- On `beforeunload`, sends `UNLOAD` message. On shift close, sends `CLOSED`.

## PS5 alarms & shift transitions
- **Three layers**: client `ps5TimerSessions` (app.js, rebuilt from `#ps5Body` rows via `syncTimerRegistry()`), server `local_data/pending_alarms.json`, service worker `ps5-alarms` IndexedDB.
- **Cross-shift persistence**: sessions still running when a shift is closed are saved by `startNewShift()` into `localStorage['ps5_pending_sessions']` (`_persistPendingSessions()`). `syncTimerRegistry()` re-merges them (row wins on id collision, dedup by id, `>24h past end` pruned). Carried-over sessions ring, show in the Timer Dashboard, and support Extend — they are **never added to form rows** (no revenue double-count).
- `dismissAlarm()` removes the session from pending + localStorage and sends acknowledge + SW `CLEAR`. `extendAlarmSession()` also handles the row-less pending case (recomputes end time from `startTime + duration`, re-persists, re-syncs).
- **Server GC**: `/api/alarms/schedule` never prunes by incoming set (old replace-all behavior deleted alarms mid-shift-transition). It now drops only alarms that are `acknowledged` AND `end_timestamp < now - 24h`, plus a hard 7-day cutoff for never-acknowledged alarms. `/api/alarms/acknowledge` is the explicit cleanup path. Unacknowledged alarms older than 24h are kept so reloads can still ring them (SW `MISSED_ALARMS`).
- **Timer end-time pinning**: `syncTimerRegistry()` pins `endDateMs` on each row's `data-end-ms` at first sync so a page kept open past midnight never recomputes an overnight session's end as "today (already past)". `calcPS5EndTime()` deletes the pin on start/duration edits. On reload after midnight, a crossing-midnight session would overshoot by a full day — any computed end more than 23h out is corrected back a day (sessions never run >24h). **Pins are also persisted per row_id in `localStorage['ps5_end_pins']` (`PS5_PINS_KEY`, `ps5EndPins` map + `_saveEndPins()`); `populateFormFromShift()` restores the true pinned end on reload (kills the >1h-after-end reload gap), `calcPS5EndTime()`/`dismissAlarm()` delete the stored pin, and `syncTimerRegistry()` prunes pins whose session id no longer exists.**
- **Self-contained alarm ring**: `startAlarmSound()` plays `ALARM_SOUND_DATA_URI` (alarm.wav embedded base64 in app.js) so the ring never depends on the server being up. While the alarm modal is open, `showAlarmModal()` runs a 4s re-ring interval (`alarmRetryIntervalId`) that replays sound + title flash — a throttled/failed single ring self-corrects. `dismissAlarm()`/`extendAlarmSession()` clear the interval.
- **Reliability hardening**: `registerAlarmSW()` re-seeds the SW (`syncTimerRegistry()`) once `navigator.serviceWorker.ready` resolves so an idle page still seeds background alarms; `syncTimerRegistry()` always persists `ps5EndPins` (prune + save every pass); `closeShift()` persists still-running sessions via `_persistPendingSessions()` so close → reload → next-start never loses rings; `extendAlarmSession()` clears the stored timer adjustment and refreshes the CustomDropdown menu before recomputing the end; the row-less pending extend advances from the persisted base `endDateMs` (never re-anchors to today, so midnight-crossing extensions keep a <24h endTs the SW accepts); `checkPS5Alarms()` saves pending on firing. Server: `_save_pending_alarms()` is atomic (`tempfile.mkstemp` + `os.replace`) and schedule/acknowledge run under `_ALARMS_LOCK` (no lost acks/updates); acknowledge forces `ids` to a list.
- **Duplicate PC guard**: `pcNameSelected()` rejects selecting a PC already present in the same section (morning/nighter tbody) with a toast.
- **Manual PS5 amounts survive reload**: `populateFormFromShift()` restores `amount_manual` rows with their stored amount instead of recomputing, and grows the duration dropdown to cover stored durations >6h.

## Timer adjustments (dashboard "Edit" button)
- Adjustments are timer-only: stored in `localStorage['ps5_timer_adjustments']` (`PS5_ADJUST_KEY`, map `sessionId → minutes`), loaded into `ps5TimerAdjustments` at boot. `_applyTimerAdjustment(session)` (called from `syncTimerRegistry()` row loop + pending merge) shifts only in-memory fields (`endDateMs`, `endTotalMin` wrapped `%1440`, `endTime`, `remainingSeconds`, `edited=true`). Form `.ps5-*` inputs and thus the database record / close payload are **never touched**.
- `toggleTimerEdit` / `applyTimerCustom(sessionId, sign)` / `applyTimerAdjust(sessionId, deltaMin)` / `resetTimerAdjust` / `closeTimerEditPanel` drive the bar: a single **Minutes** number field (`#tdEditMinutes`, `ps5EditMinutes` oninput) with `+ Add time` / `− Remove time` (green/red), `↺ Reset`, `Done`. `applyTimerCustom` parses the field (reject <1 with toast, cap 999) and delegates to `applyTimerAdjust` — clamps: min `now + 60s`, max `base end + 24h`. Dashboard End column shows a `✎` mark (`td-edited-mark`) when a session is adjusted. The bar lives in `#tdEditBar` **outside** the rebuilt tbody, so inputs keep value + focus across the 1s `renderTimerDashboard()` re-renders (`ps5EditOpenId` + `ps5EditBarHtml`).
- **Base-value persistence** (anti-double-count): `_persistPendingSessions()` stores the pre-adjustment times (subtracts `ps5TimerAdjustments[id]` from `endDateMs`/`endTotalMin`/`endTime`) so the merge re-applies each adjustment exactly once. `dismissAlarm()` deletes the stored adjustment for the dismissed session.

## Cross-shift carry-over (extended-hour entries)
- **Rule**: only sessions whose time was up AND were extended while **no shift was active** are carried into the next started shift's form as extended-hour (`isExtended`, ⚡ EXT) rows. Running in-shift extensions never carry (avoids revenue double-count).
- **Stamping**: `extendAlarmSession()` marks the row `row.dataset.wasExtended='true'` + `row.dataset.origEndMs` (pre-extension end) when `!currentShift || !currentShift.shift_id` (client nulls `currentShift` on close). The row-less pending branch sets `pend.originalEndDateMs = pend.originalEndDateMs || pend.endDateMs`, `pend.wasExtended = true`, and calls `carryOverPendingEntryToForm(pend)` immediately if a shift is already active (live row).
- **Carry-in**: `startNewShift()` → `carryOverEligiblePendingToForm()` (after `clearForm()`, before employee restore) iterates pending sessions where `wasExtended && !formRowCreated`. `carryOverPendingEntryToForm()` builds an EXT row starting at the **previous hour's end** (`new Date(originalEndDateMs)` → HH:MM), duration = `round((endDateMs − originalEndDateMs)/1h)` clamped 1..24, extension pricing via `recalcPS5RowAmount`; sets `row.dataset.rowId = p.id` (registry dedup: row wins on id collision, timer keeps ringing), class `ps5-extended`, and `p.formRowCreated = true` (guards duplicates). Row deletion in-form never re-adds the entry.

## Settings
- `GET /api/settings` returns current config (PINs stripped — `admin_pins`, `employee_pins` removed).
- `POST /api/settings` requires admin auth (`X-Admin-Token` header). Validates:
  - employees: list of strings (must have at least 1)
  - inventory_items: list of strings (must have at least 1)
  - packages: list of `{hz, hrs, price}` objects (must have at least 1)
  - ps5_pricing: object with 5 numeric keys: `two_controllers_first_hour`, `one_controller_first_hour`, `two_controllers_extended`, `one_controller_extended`, `ps5_pc_rate`
  - ps5_numbers: list of strings
  - Frontend also strips `employee_pins`/`admin_pins` before sending to prevent overwrite.
- `settings.json` also stores `admin_pins`, `employee_pins` (hashed). Admin PINs use `/api/admin/verify-pin`, employee PINs use `/api/employee/verify-pin`.
- Only "Rafay" or "Jahanzaib Khan" can reset employee PINs via the Settings UI.

## Key routes
| Path | Method | Purpose |
|---|---|---|
| `/api/config` | GET | employees, packages, ps5_pricing, ps5_numbers, shifts, current_shift timing |
| `/api/session` | GET | active/orphaned/last shift info |
| `/api/shift/start` | POST | start shift (creates UUID, saves snapshot) |
| `/api/shift/close` | POST | close shift (validates PIN, payment match, negative clamp) |
| `/api/shift/auto-save` | POST | save in-progress state (rejects stale with 409, 3 retries client-side) |
| `/api/shift/last-closed` | GET | last closed shift data |
| `/api/shifts/history` | GET | paginated shift list (page, per_page, has_more) |
| `/api/shifts/<shift_id>` | GET | single shift detail (closed shifts require admin auth) |
| `/api/upload-screenshot` | POST | multipart → `uploads/{shift_id}_{uuid}{ext}` |
| `/api/sheets/status` | GET | whether Google Sheets is configured |
| `/api/sheets/sync-all` | POST | batch-sync all closed shifts |
| `/api/sheets/sync-shift/<id>` | POST | sync single shift |
| `/api/sheets/clear` | POST | clear all sheet data, re-create headers, reset local sync flags |
| `/api/screenshots/re-upload/<shift_id>` | POST | idempotent screenshot re-upload: skips images whose sheet cell already holds an ImgBB URL (`ibb.co`/`imgbb.com`); uploads only empty/local-fallback cells; missing local files leave the cell unchanged and return a warning |
| `/api/sync-errors` | GET | last 100 sync errors (admin auth) |
| `/api/health` | GET | health check |
| `/api/admin/pin-status` | POST | check if admin has a PIN set |
| `/api/admin/set-pin` | POST | first-time admin PIN setup |
| `/api/admin/verify-pin` | POST | admin login → returns session token |
| `/api/admin/session` | GET | verify admin token is still valid |
| `/api/admin/reset-employee-pin` | POST | admin resets employee PIN |
| `/api/employee/pin-status` | GET | check if employee has a PIN |
| `/api/employee/set-pin` | POST | first-time employee PIN setup |
| `/api/employee/verify-pin` | POST | employee PIN verification for close |
| `/uploads/<filename>` | GET | serve uploaded screenshot files |
| `/assets/<path>` | GET | serve static assets (logo.png) |

## Screenshots
- Uploaded to `uploads/` dir (config: `UPLOAD_DIR`). API accepts `image` field + `shift_id` + `type` (`pancafe` or `form`). Filename: `{shift_id}_{uuid}{ext}`.
- **Auto-capture on close**: `closeShift()` captures form via `dom-to-image-more` (CDN `https://cdn.jsdelivr.net/npm/dom-to-image-more@3/dist/dom-to-image-more.min.js`, SVG `<foreignObject>`), with retry on small blob (<100 bytes). Screenshots section hidden during capture.
- `_ensurePancafeUploaded()` uploads pancafe screenshot from preview data URL on close (only if `data:` URL present and not already uploaded).
- `_uploadingScreenshot` flag prevents concurrent uploads — close flow waits up to 5s for in-progress upload.
- **Global paste handler** on `document` for pancafe screenshots — shows "No image found in clipboard" toast on non-image paste.
- Upload failure is non-blocking — shift closes regardless. Toast shown for success + failure.
- File validated: magic bytes (PNG `\x89PNG`, JPEG `\xff\xd8`, GIF `GIF87a`/`GIF89a`, WebP `RIFF....WEBP`, BMP `BM`) + Pillow `verify()` + 20MB size limit + minimum 4 bytes.
- Copied on upload to `screenshots/pancafe_screenshot/` or `screenshots/shift_form_screenshot/` by `{date}_{employee_name}{ext}`. Copy failure is silently ignored.

## Inventory
- Items snapshot saved on shift start (`inventory_items_snapshot`). Removing items from settings mid-shift doesn't affect active shift inventory table.
- Inventory columns: opening stock, restock, closing stock. Sold = `opening + restock - closing` (clamped to 0, computed client-side).
- On shift start, last shift's closing stock values are pre-filled as opening stock for the new shift.

## Employee PIN
- First-time PIN setup built into close flow: modal checks `/api/employee/pin-status`; if no PIN exists, switches to setup mode with confirm field (must match, 4-20 digits).
- PINs persisted in `settings.json` under `employee_pins` key (pbkdf2:sha256 hashed).
- Admin can reset employee PINs via Settings UI → 🔑 Reset PIN button, restricted to "Rafay" and "Jahanzaib Khan".

## Testing
Run from project root: `python tests\test_server_smoke.py` etc., plus `node tests\test_timer_logic.js` (pure-function logic, no DOM). Suites use the live server module with `WTF_CSRF_ENABLED=False`, temp data dirs and fake gspread/ImgBB where needed. Suites: `test_server_smoke` (start/close/auto-save/409s), `test_dedup` (Sheets dedup + partial-failure recovery), `test_reroute_clear` (re-upload + Clear Sheets), `test_reupload` (idempotent screenshot re-upload, 13 checks), `test_alarm_schedule` (alarm GC), `test_total_pcs` (settings persistence + clamp), `test_timer_logic.js` (adjustments/carry-over/custom input, 25 checks). No test framework, no test dependencies.

## Template / static cache busting
- `style.css?v=16`, `app.js?v=35` hardcoded in `index.html`. Bump `v` on changes to force browser reload.

## Dependencies (beyond flask baseline)
- `waitress`, `Flask-WTF`, `flask-talisman`, `Pillow`, `gspread`, `google-auth`, `google-api-python-client`
