import { describe, expect, it } from "vitest";
import { formatDate, formatDuration, formatMonth, formatRating } from "./format";

describe("formatDate", () => {
  it("shows an ISO date as dd/mm/yyyy", () => {
    expect(formatDate("2026-07-05")).toBe("05/07/2026");
  });
});

describe("formatMonth", () => {
  it("shows an ISO month with the short Italian name", () => {
    expect(formatMonth("2026-07")).toBe("lug 2026");
  });
});

describe("formatDuration", () => {
  it("shows hours and minutes", () => {
    expect(formatDuration(170)).toBe("2 h 50 min");
  });

  it("drops the part that is zero", () => {
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(0)).toBe("0 min");
  });

  it("groups thousands of hours the Italian way, only from five digits", () => {
    expect(formatDuration(1234 * 60)).toBe("1234 h");
    expect(formatDuration(12345 * 60)).toBe("12.345 h");
  });
});

describe("formatRating", () => {
  it("uses the decimal comma and drops a zero decimal", () => {
    expect(formatRating(3.5)).toBe("3,5");
    expect(formatRating(4)).toBe("4");
  });

  it("rounds averages to one decimal", () => {
    expect(formatRating(3.6666)).toBe("3,7");
  });
});
