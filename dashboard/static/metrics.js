/* Pure display math for the fixed 600-case dashboard. */
(function exposeMetrics(root, factory) {
  const metrics = factory();
  if (typeof module === "object" && module.exports) module.exports = metrics;
  else root.AccessBenchMetrics = metrics;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildMetrics() {
  function formatCasePercent(k, n) {
    if (!Number.isInteger(k) || !Number.isInteger(n) || n <= 0 || k < 0 || k > n) {
      throw new RangeError("case percentage requires integers with 0 <= k <= n");
    }
    const rendered = ((100 * k) / n).toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
    return `${rendered}%`;
  }

  /* Percent for every non-case metric. A security number that is not zero must
     never render as zero: one leak in three thousand episodes is not "0%". */
  function pct(r) {
    if (r === null || r === undefined || Number.isNaN(r)) return "n/a";
    const v = 100 * r;
    if (v === 0) return "0%";
    if (v > 0 && v < 0.05) return "<0.1%";
    if (v >= 99.95 && v < 100) return ">99.9%";
    if (v === 100) return "100%";
    return v.toFixed(1) + "%";
  }

  /* The enforced arm of a run is whatever arm is not the control. It may be a
     built-in gate, the Benchmark PDP, or an AuthZEN URL; the dashboard must
     not keep a list of names it happens to know. */
  function enforcedArm(summary) {
    if (!summary || typeof summary !== "object") return null;
    const arms = Object.keys(summary).filter((k) => k !== "none");
    return arms.length === 1 ? arms[0] : null;
  }

  function validateFixedBankBlock(block) {
    return Boolean(
      block &&
      block.case_n === 600 &&
      block.repeat_k >= 1 &&
      Number.isInteger(block.stable_pass_n) &&
      block.stable_pass_n >= 0 &&
      block.stable_pass_n <= block.case_n
    );
  }

  return { enforcedArm, formatCasePercent, pct, validateFixedBankBlock };
});
