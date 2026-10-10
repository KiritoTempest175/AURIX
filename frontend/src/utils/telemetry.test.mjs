import { describe, expect, it } from "vitest";
import { summarizeMetric } from "./telemetry.mjs";

describe("native telemetry summary", () => {
  it("computes minimum, average and maximum of genuine samples", () => {
    expect(summarizeMetric([{ cpu: 10 }, { cpu: 30 }, { cpu: 50 }], "cpu"))
      .toEqual({ min: 10, avg: 30, max: 50, count: 3 });
  });
  it("preserves the distinction between unavailable and zero", () => {
    expect(summarizeMetric([{ gpu: null }, { gpu: null }], "gpu"))
      .toEqual({ min: null, avg: null, max: null, count: 0 });
    expect(summarizeMetric([{ gpu: 0 }], "gpu").min).toBe(0);
  });
});
