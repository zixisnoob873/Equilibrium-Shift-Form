// Advisory close-time inventory check — extracts the REAL function source out
// of static/js/app.js and runs it against DOM stubs, the same approach as
// test_timer_logic.js. Run:  node tests\test_ui_logic.js
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

const G = globalThis;
const results = [];
function check(name, cond, detail) {
  results.push([!!cond, name, detail]);
  console.log((cond ? '[PASS] ' : '[FAIL] ') + name + (cond ? '' : '  << ' + JSON.stringify(detail)));
}

const getZeroClosing = Function('return (' + extract('getZeroClosingInventory') + ')')();

// ── DOM stub ────────────────────────────────────────────────────────────────
// One inventory row: .inv-opening carries the item name in data-item.
function row(name, opening, restock, closing, dropName) {
  const mk = (v, ds) => ({ value: v, dataset: ds || {} });
  return {
    _dropName: !!dropName,
    querySelector(sel) {
      if (sel === '.inv-opening') return mk(opening, dropName ? {} : { item: name });
      if (sel === '.inv-restock') return mk(restock);
      if (sel === '.inv-closing') return mk(closing);
      return null;
    }
  };
}

function setRows(rows) {
  G.document = {
    querySelectorAll: sel => (sel === '#inventoryBody tr' ? rows : [])
  };
}

// ── 1. all closings zero -> warns ───────────────────────────────────────────
setRows([
  row('Sting', 10, 5, 0),
  row('Water', 20, 0, 0),
  row('Lays', 6, 4, 0)
]);
let r = getZeroClosing();
check('W1 all-zero closings -> warning fires', r !== null, r);
check('W2 itemCount is correct', r && r.itemCount === 3, r && r.itemCount);
check('W3 expectedUnits = sum(opening+restock) = 45', r && r.expectedUnits === 45, r && r.expectedUnits);
check('W4 items array returned for detail', r && Array.isArray(r.items) && r.items.length === 3, r && r.items);

// ── 2. a single non-zero closing suppresses the warning ─────────────────────
setRows([row('Sting', 10, 5, 0), row('Water', 20, 0, 7), row('Lays', 6, 4, 0)]);
check('W5 one counted item -> no warning', getZeroClosing() === null, getZeroClosing());

// ── 3. every item counted ───────────────────────────────────────────────────
setRows([row('Sting', 10, 5, 4), row('Water', 20, 0, 7), row('Lays', 6, 4, 0)]);
check('W6 all counted -> no warning', getZeroClosing() === null, getZeroClosing());

// ── 4. empty inventory -> no warning (nothing to count) ─────────────────────
setRows([]);
check('W7 empty tbody -> no warning', getZeroClosing() === null, getZeroClosing());
setRows([row('NoName', 1, 1, 0, true)]);   // row present but no data-item
check('W8 row without a data-item name -> no warning', getZeroClosing() === null, getZeroClosing());

// ── 5. negative closing is NOT "zero" ───────────────────────────────────────
setRows([row('Sting', 10, 5, -2), row('Water', 20, 0, 0)]);
check('W9 negative closing -> no warning (someone typed something)', getZeroClosing() === null, getZeroClosing());
setRows([row('Sting', 10, 5, -0), row('Water', 0, 0, 0)]);
check('W10 -0 is exactly zero -> warns', getZeroClosing() !== null, getZeroClosing());

// ── 6. blank / garbage closings count as zero ───────────────────────────────
setRows([row('Sting', 10, 5, ''), row('Water', 20, 0, 'abc'), row('Lays', 6, 4, null)]);
r = getZeroClosing();
check('W11 blank/garbage closing treated as 0 -> warns', r !== null, r);
// opening+restock are all valid here (15 + 20 + 10), so the garbage closing
// values must not leak into the "expected on hand" figure.
check('W12 expectedUnits uses opening+restock only = 45', r && r.expectedUnits === 45, r && r.expectedUnits);

// ── 7. genuinely empty cafe still warns (per spec), expectedUnits = 0 ───────
setRows([row('Sting', 0, 0, 0), row('Water', 0, 0, 0)]);
r = getZeroClosing();
check('W13 empty cafe (opening 0, restock 0) -> still warns', r !== null, r);
check('W14 expectedUnits is 0 for an empty cafe', r && r.expectedUnits === 0, r && r.expectedUnits);
check('W15 itemCount still reported for an empty cafe', r && r.itemCount === 2, r && r.itemCount);

// ── 8. negative expected units can cancel out ───────────────────────────────
setRows([row('A', 10, 0, 0), row('B', 0, 0, 0)]);
r = getZeroClosing();
check('W16 expectedUnits is a plain sum (no clamping)', r && r.expectedUnits === 10, r && r.expectedUnits);

// ── 9. the function must not touch any money total ──────────────────────────
const s = src.slice(src.indexOf('function getZeroClosingInventory'),
                    src.indexOf('function showInventoryWarnModal'));
check('W17 predicate never references grand total / payment fields',
  !/grandTotal|summaryExpenses|cashInput|onlineInput|actualPosInput/.test(s), 'leaked a money field');
check('W18 predicate never calls triggerAutoSave or recalc',
  !/triggerAutoSave|recalc/.test(s), 'caused a side effect');

const failed = results.filter(x => !x[0]).length;
console.log('\nRESULT: ' + (failed === 0
  ? 'ALL PASS (' + results.length + ' checks)'
  : failed + ' FAILED -> ' + JSON.stringify(results.filter(x => !x[0]).map(x => x[1]))));
process.exit(failed ? 1 : 0);