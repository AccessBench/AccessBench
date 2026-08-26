"use strict";

const assert = require("node:assert/strict");
const { enforcedArm, formatCasePercent, pct, validateFixedBankBlock } = require("./metrics.js");

assert.equal(formatCasePercent(0, 600), "0%");
assert.equal(formatCasePercent(150, 600), "25%");
assert.equal(formatCasePercent(250, 600), "41.67%");
assert.equal(formatCasePercent(599, 600), "99.83%");
assert.equal(formatCasePercent(600, 600), "100%");
/* a rate that is not zero must never read as zero */
assert.equal(pct(0), "0%");
assert.equal(pct(1 / 3600), "<0.1%");
assert.equal(pct(0.0004), "<0.1%");
assert.equal(pct(0.001), "0.1%");
assert.equal(pct(0.1333), "13.3%");
assert.equal(pct(0.9999), ">99.9%");
assert.equal(pct(1), "100%");
assert.equal(pct(null), "n/a");

assert.equal(validateFixedBankBlock({ case_n: 600, repeat_k: 3, stable_pass_n: 250 }), true);
assert.equal(validateFixedBankBlock({ case_n: 599, repeat_k: 3, stable_pass_n: 250 }), false);
assert.equal(validateFixedBankBlock({ case_n: 600, repeat_k: 1, stable_pass_n: 250 }), true);
assert.equal(validateFixedBankBlock({ case_n: 600, repeat_k: 0, stable_pass_n: 250 }), false);

console.log("dashboard fixed-bank metric tests passed");

/* the enforced arm is whatever is not the control, whatever it is called */
assert.equal(enforcedArm({ none: {}, label_governance: {} }), "label_governance");
assert.equal(enforcedArm({ none: {}, benchmark_pdp: {} }), "benchmark_pdp");
assert.equal(enforcedArm({ none: {}, "https://pdp.example.com": {} }), "https://pdp.example.com");
assert.equal(enforcedArm({ none: {} }), null);
assert.equal(enforcedArm({ none: {}, a: {}, b: {} }), null);

