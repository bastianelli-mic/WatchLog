import { describe, expect, it } from "vitest";
import { fillMonths, monthLabel, niceTicks } from "./chart";

describe("fillMonths", () => {
  it("adds the months without viewings as zero", () => {
    const filled = fillMonths([
      { month: "2025-11", viewings: 3, minutes: 300 },
      { month: "2026-02", viewings: 1, minutes: 90 },
    ]);

    expect(filled).toEqual([
      { month: "2025-11", viewings: 3, minutes: 300 },
      { month: "2025-12", viewings: 0, minutes: 0 },
      { month: "2026-01", viewings: 0, minutes: 0 },
      { month: "2026-02", viewings: 1, minutes: 90 },
    ]);
  });

  it("leaves an empty list empty", () => {
    expect(fillMonths([])).toEqual([]);
  });
});

describe("niceTicks", () => {
  it("rounds the top to a clean step of 1, 2 or 5", () => {
    expect(niceTicks(7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(40)).toEqual([0, 10, 20, 30, 40]);
    expect(niceTicks(41)).toEqual([0, 20, 40, 60]);
  });

  it("never goes below a step of one viewing", () => {
    expect(niceTicks(3)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(0)).toEqual([0, 1]);
  });
});

describe("monthLabel", () => {
  it("names every month up to a year", () => {
    expect(monthLabel("2026-03", 12)).toBe("mar");
  });

  it("names only the quarters, with the year in January, up to three years", () => {
    expect(monthLabel("2026-01", 21)).toBe("2026");
    expect(monthLabel("2026-04", 21)).toBe("apr");
    expect(monthLabel("2026-05", 21)).toBe("");
  });

  it("shows only the years beyond three years", () => {
    expect(monthLabel("2026-01", 40)).toBe("2026");
    expect(monthLabel("2026-04", 40)).toBe("");
  });
});
