/** Pure telemetry math. Null values are excluded, not silently replaced by zero. */
export function summarizeMetric(rows, key) {
  const values = rows.map((x) => x[key]).filter((x) => typeof x === "number" && Number.isFinite(x));
  if (!values.length) return { min: null, avg: null, max: null, count: 0 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = values.reduce((total, x) => total + x, 0) / values.length;
  return { min, avg, max, count: values.length };
}
