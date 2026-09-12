// Logic tests for the PS5 timer changes — extracts the REAL function sources
// from static/js/app.js and runs them against stubs.
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

function extract(name) {
    const start = src.indexOf('function ' + name);
    if (start < 0) throw new Error('function ' + name + ' not found');
    let i = src.indexOf('{', start);
    let depth = 0;
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') { depth--; if (depth === 0) break; }
    }
    return src.slice(start, i + 1);
}

const DAY = 86400000;
const dayStart = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };

function run(fn) { return Function('return (' + fn + ')')(); }

const G = globalThis;
function setG(name, value) { G[name] = value; }

setG('ps5TimerAdjustments', {});
setG('ps5EndPins', {});
setG('_saveEndPins', () => {});
setG('ps5TimerSessions', []);
setG('ps5PendingSessions', []);
setG('_savePendingSessions', () => {});
setG('syncAlarmsToSW', () => {});
setG('document', { getElementById: () => null, querySelectorAll: () => [] });
setG('config', {});
setG('initCustomDropdowns', () => {});
setG('syncDropdown', () => {});
setG('calcPS5EndTime', () => {});
setG('recalcPS5RowAmount', () => {});
setG('autoCalcPS5', () => {});

const results = [];
function check(name, cond, detail) {
    results.push([cond, name, detail]);
    console.log((cond ? '[PASS] ' : '[FAIL] ') + name + (cond ? '' : '  << ' + detail));
}

// ── 1. _applyTimerAdjustment ──
const applyAdj = run(extract('_applyTimerAdjustment'));
setG('_applyTimerAdjustment', applyAdj);
{
    const DS = dayStart();
    // no adjustment -> untouched
    const s1 = { id: 'a', endTotalMin: 1140, endDateMs: DS + 1140 * 60000, remainingSeconds: 3600, endTime: '19:00' };
    applyAdj(s1);
    check('no adj leaves session untouched', s1.endDateMs === DS + 1140 * 60000 && !s1.edited, JSON.stringify(s1));

    // +30m on 18:00-19:00 row session
    const s2 = { id: 'a', endTotalMin: 1140, endDateMs: DS + 1140 * 60000, remainingSeconds: 3600, endTime: '19:00' };
    setG('ps5TimerAdjustments', { a: 30 });
    applyAdj(s2);
    check('+30m -> end 19:30', s2.endTotalMin === 1170 && s2.endTime === '19:30' && s2.endDateMs === DS + 1170 * 60000 && s2.edited === true,
        JSON.stringify({ t: s2.endTime, m: s2.endTotalMin, d: s2.endDateMs - DS }));

    // -2h on 18:00-19:00
    setG('ps5TimerAdjustments', { a: -120 });
    const s3 = { id: 'a', endTotalMin: 1140, endDateMs: DS + 1140 * 60000, remainingSeconds: 3600, endTime: '19:00' };
    applyAdj(s3);
    check('-2h -> end 17:00', s3.endTotalMin === 1020 && s3.endTime === '17:00', s3.endTime);

    // midnight wrap: start 23:00 end 01:00 (next day), +2h -> 03:00
    const baseWrapped = DS + (60 + 1440) * 60000;
    setG('ps5TimerAdjustments', { b: 120 });
    const s4 = { id: 'b', endTotalMin: 60, endDateMs: baseWrapped, remainingSeconds: 7200, endTime: '01:00' };
    applyAdj(s4);
    check('midnight +2h -> 03:00 next day', s4.endTotalMin === 180 && s4.endTime === '03:00' && s4.endDateMs === DS + 1620 * 60000,
        JSON.stringify({ t: s4.endTime, m: s4.endTotalMin, d: s4.endDateMs - DS }));

    // midnight wrap: -2h from 01:00 (next day) -> 23:00 same day
    setG('ps5TimerAdjustments', { c: -120 });
    const s5 = { id: 'c', endTotalMin: 60, endDateMs: baseWrapped, remainingSeconds: 7200, endTime: '01:00' };
    applyAdj(s5);
    check('midnight -2h -> 23:00', s5.endTotalMin === 1380 && s5.endTime === '23:00' && s5.endDateMs === DS + 1380 * 60000,
        JSON.stringify({ t: s5.endTime, m: s5.endTotalMin, d: s5.endDateMs - DS }));
}

// ── 2. _persistPendingSessions stores BASE values (no double adjustment) ──
{
    const persist = run(extract('_persistPendingSessions'));
    const DS = dayStart();
    const saved = [];
    setG('ps5TimerAdjustments', { a: 30 });
    setG('ps5TimerSessions', [{
        id: 'a', psNumber: 'Left', controllers: 2, startTime: '18:00', endTime: '19:30',
        duration: 1, isExtended: false, amount: 700,
        endTotalMin: 1170, // adjusted (base 1140 + 30)
        endDateMs: DS + 1170 * 60000,
        alarmTriggered: false, wasExtended: true, originalEndDateMs: DS + 1140 * 60000
    }]);
    setG('ps5PendingSessions', []);
    setG('_savePendingSessions', () => { saved.push(JSON.parse(JSON.stringify(G.ps5PendingSessions))); });
    persist();
    const p = G.ps5PendingSessions[0];
    check('persist stores BASE endTotalMin (1140)', p.endTotalMin === 1140, p.endTotalMin);
    check('persist stores BASE endDateMs', p.endDateMs === DS + 1140 * 60000, p.endDateMs - DS);
    check('persist stores BASE endTime 19:00', p.endTime === '19:00', p.endTime);
    check('persist keeps flags', p.wasExtended === true && p.formRowCreated === false && p.originalEndDateMs === DS + 1140 * 60000,
        JSON.stringify(p));

    // re-apply on merge == original adjusted values
    setG('ps5TimerSessions', []);
    const merge = run(extract('syncTimerRegistry'));
    const DS2 = dayStart();
    setG('ps5TimerAdjustments', { a: 30 });
    setG('syncAlarmsToSW', () => {});
    setG('document', {
        getElementById: (id) => {
            if (id === 'ps5Body') return { querySelectorAll: () => [] };
            if (id === 'timerDashboard') return { style: { display: 'none' } };
            return null;
        },
        querySelectorAll: () => []
    });
    merge(); // no DOM rows; pending merge path only
    const s = G.ps5TimerSessions.find(x => x.id === 'a');
    check('merge re-applies adj -> end 19:30', s && s.endTotalMin === 1170 && s.endTime === '19:30' && s.endDateMs === DS2 + 1170 * 60000,
        s ? JSON.stringify({ t: s.endTime, d: s.endDateMs - DS2 }) : 'no session');
}

// ── 3. carryOverPendingEntryToForm ──
{
    const carry = run(extract('carryOverPendingEntryToForm'));
    const DS = dayStart();
    const rows = [];
    setG('document', {
        createElement: () => ({
            dataset: {}, classList: { add: () => {} },
            set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html || ''; },
            querySelector: () => ({ value: '' })
        }),
        getElementById: (id) => {
            if (id === 'ps5Body') return { appendChild: (r) => rows.push(r) };
            if (id === 'timerDashboard') return { style: { display: 'none' } };
            return null;
        },
        querySelectorAll: () => []
    });
    setG('config', { ps5_numbers: ['Left', 'Right', 'PC'] });
    setG('initCustomDropdowns', () => {});
    setG('syncDropdown', () => {});
    setG('calcPS5EndTime', () => {});
    setG('recalcPS5RowAmount', () => {});
    setG('autoCalcPS5', () => {});
    setG('_savePendingSessions', () => {});

    // single extension: orig end 19:00, new end 20:00
    let pend = { id: 's1', psNumber: 'Left', controllers: 2, originalEndDateMs: DS + 19 * 3600000, endDateMs: DS + 20 * 3600000 };
    const ok = carry(pend);
    check('carry creates row', ok === true && rows.length === 1, rows.length);
    const html = rows[0].innerHTML;
    check('carry row start = 19:00', html.includes('value="19:00"'), (html.match(/ps5-start[^>]*/g) || []).join(','));
    check('carry row duration = 1hr selected', html.includes('value="1" selected') && html.includes('>1 hr<'), '');
    check('carry row is EXT + rowId', html.includes('⚡ EXT') && rows[0].dataset.rowId === 's1' && rows[0].dataset.isExtended === 'true', '');
    check('carry marks formRowCreated', pend.formRowCreated === true, JSON.stringify(pend));

    // multi-extension: orig 19:00 -> 21:00 = 2 extra hours
    const pend2 = { id: 's2', psNumber: 'Right', controllers: 1, originalEndDateMs: DS + 19 * 3600000, endDateMs: DS + 21 * 3600000 };
    carry(pend2);
    const html2 = rows[1].innerHTML;
    check('carry 2 extended hrs selected', html2.includes('value="2" selected'), '');
    check('carry 2hr row start still 19:00', html2.includes('value="19:00"'), '');

    // guard: already created -> no duplicate
    const before = rows.length;
    carry(pend2);
    check('carry skips formRowCreated entries', rows.length === before, rows.length);

    // guard: no id
    carry({ psNumber: 'Left' });
    check('carry skips id-less entries', rows.length === before, rows.length);
}

// ── 4. applyTimerCustom (minutes field parsing) ──
{
    const custom = run(extract('applyTimerCustom'));
    const DS = dayStart();
    setG('ps5TimerSessions', [{ id: 'x', endTotalMin: 1140, endDateMs: DS + 1140 * 60000, remainingSeconds: 3600, endTime: '19:00' }]);
    setG('ps5TimerAdjustments', {});
    setG('ps5EditMinutes', '');
    const toasts = [];
    setG('showToast', (m) => toasts.push(m));
    setG('closeTimerEditPanel', () => { G.ps5EditOpenId = null; });
    setG('_saveTimerAdjustments', () => {});
    setG('syncTimerRegistry', () => {});
    setG('renderTimerDashboard', () => {});
    setG('applyTimerAdjust', (id, delta) => { G._lastDelta = delta; });

    setG('ps5EditMinutes', '45');
    custom('x', 1);
    check('applyTimerCustom +45 -> applyTimerAdjust(45)', G._lastDelta === 45, G._lastDelta);

    setG('ps5EditMinutes', '');
    custom('x', 1);
    check('applyTimerCustom rejects empty', toasts.length === 1 && G._lastDelta === 45, toasts.join(','));

    setG('ps5EditMinutes', '0');
    custom('x', 1);
    check('applyTimerCustom rejects 0 with toast', toasts.length === 2, toasts.join(','));

    setG('ps5EditMinutes', 'abc');
    custom('x', 1);
    check('applyTimerCustom rejects NaN', toasts.length === 3, toasts.join(','));

    setG('ps5EditMinutes', '45');
    custom('x', -1);
    check('applyTimerCustom -45 -> applyTimerAdjust(-45)', G._lastDelta === -45, G._lastDelta);

    setG('ps5EditMinutes', '1200');
    custom('x', 1);
    check('applyTimerCustom caps at 999', G._lastDelta === 999, G._lastDelta);
}

console.log();

// ── 5. dismissedTimerChanged (5-min watchdog snapshot comparison) ──
{
    const chk = run(extract('dismissedTimerChanged'));
    const snap = { startTime: '18:00', duration: 1 };
    check('dismissedTimerChanged unchanged -> false', chk(snap, '18:00', '1') === false, '');
    check('dismissedTimerChanged duration +1 -> true', chk(snap, '18:00', '2') === true, '');
    check('dismissedTimerChanged start edited -> true', chk(snap, '19:00', '1') === true, '');
    check('dismissedTimerChanged both -> true', chk(snap, '19:00', '3') === true, '');
    check('dismissedTimerChanged null snapshot -> false', chk(null, '18:00', '1') === false, '');
    check('dismissedTimerChanged coerces string duration', chk({ startTime: '18:00', duration: '1' }, '18:00', '1') === false, '');
    check('dismissedTimerChanged start only differs -> true', chk({ startTime: '20:00', duration: 2 }, '18:00', '2') === true, '');
}

console.log();

// ── 6. computePS5SessionEndMs (Midnight & Noon boundary testing) ──
{
    const computeEndMs = run(extract('computePS5SessionEndMs'));
    const DS = dayStart();

    // 11:59 AM start, 1 hr duration, tested at 11:58 AM
    const now1158am = DS + (11 * 60 + 58) * 60000;
    const end1 = computeEndMs('11:59', 1, now1158am);
    const rem1 = (end1 - now1158am) / 1000;
    check('11:59 AM + 1 hr tested at 11:58 AM -> ~61 mins', rem1 === 3660, rem1);

    // 11:59 AM start, 1 hr duration, tested at 12:15 PM
    const now1215pm = DS + (12 * 60 + 15) * 60000;
    const end2 = computeEndMs('11:59', 1, now1215pm);
    const rem2 = (end2 - now1215pm) / 1000;
    check('11:59 AM + 1 hr tested at 12:15 PM -> 44 mins', rem2 === 44 * 60, rem2);

    // 11:59 AM start, 1 hr duration, tested at 14:00 PM (past end)
    const now1400pm = DS + (14 * 60) * 60000;
    const end3 = computeEndMs('11:59', 1, now1400pm);
    const rem3 = Math.max(0, (end3 - now1400pm) / 1000);
    check('11:59 AM + 1 hr tested at 14:00 PM -> 0 remaining (ended, no 24h jump)', rem3 === 0, rem3);

    // 23:59 PM start, 1 hr duration, tested at 23:58 PM (before midnight)
    const now2358pm = DS + (23 * 60 + 58) * 60000;
    const end4 = computeEndMs('23:59', 1, now2358pm);
    const rem4 = (end4 - now2358pm) / 1000;
    check('23:59 PM + 1 hr tested at 23:58 PM -> ~61 mins (into next day)', rem4 === 3660, rem4);

    // 23:59 PM start, 1 hr duration, tested at 00:05 AM (after midnight)
    const now0005am = DS + (5) * 60000;
    const end5 = computeEndMs('23:59', 1, now0005am);
    const rem5 = (end5 - now0005am) / 1000;
    check('23:59 PM + 1 hr tested at 00:05 AM -> 54 mins (no 24h jump)', rem5 === 54 * 60, rem5);

    // 23:59 PM start, 1 hr duration, tested at 02:00 AM (2h after midnight, past end)
    const now0200am = DS + (120) * 60000;
    const end6 = computeEndMs('23:59', 1, now0200am);
    const rem6 = Math.max(0, (end6 - now0200am) / 1000);
    check('23:59 PM + 1 hr tested at 02:00 AM -> 0 remaining (ended, no 23h jump)', rem6 === 0, rem6);
}

// --- Section 5: sortInventoryItems logic tests ---
{
    const sortInv = run(extract('sortInventoryItems'));
    
    // 1. Simple strings
    const res1 = sortInv(['Water', 'Sting', 'Apples', 'Bananas']);
    check('sortInventoryItems sorts strings alphabetically', JSON.stringify(res1) === JSON.stringify(['Apples', 'Bananas', 'Sting', 'Water']), res1);

    // 2. Case-insensitive sorting
    const res2 = sortInv(['water', 'Apples', 'STING', 'bananas']);
    check('sortInventoryItems sorts case-insensitively', JSON.stringify(res2.map(s => s.toLowerCase())) === JSON.stringify(['apples', 'bananas', 'sting', 'water']), res2);

    // 3. Object array with .name
    const res3 = sortInv([{name: 'Water', stock: 5}, {name: 'Apples', stock: 10}, {name: 'Sting', stock: 2}]);
    check('sortInventoryItems sorts object array with .name', JSON.stringify(res3.map(o => o.name)) === JSON.stringify(['Apples', 'Sting', 'Water']), res3);

    // 4. Tuples [name, opening, restock, closing]
    const res4 = sortInv([['Water', 1, 0, 1], ['Apples', 5, 2, 3], ['Sting', 10, 0, 5]]);
    check('sortInventoryItems sorts tuple inventory array', JSON.stringify(res4.map(t => t[0])) === JSON.stringify(['Apples', 'Sting', 'Water']), res4);

    // 5. Handles empty/null/non-array gracefully
    const res5 = sortInv(null);
    check('sortInventoryItems handles null without crashing', Array.isArray(res5) && res5.length === 0, res5);
}

const failed = results.filter(r => !r[0]);
console.log(failed.length === 0 ? 'RESULT: ALL PASS (' + results.length + ' checks)' : 'RESULT: ' + failed.length + ' FAILED');
process.exit(failed.length === 0 ? 0 : 1);
