import { describe, expect, it } from "vitest";
import { periodRange } from "./period";

const today = new Date(2026, 10, 12); // giovedì 12 novembre 2026, ora locale

describe("periodRange", () => {
  it("has no bounds for the whole history", () => {
    expect(periodRange("tutto", today)).toEqual({});
  });

  it("covers today only", () => {
    expect(periodRange("oggi", today)).toEqual({ since: "2026-11-12", until: "2026-11-12" });
  });

  it("covers the week from Monday to Sunday", () => {
    expect(periodRange("settimana", today)).toEqual({ since: "2026-11-09", until: "2026-11-15" });
  });

  it("starts the week on the previous Monday when today is Sunday", () => {
    expect(periodRange("settimana", new Date(2026, 10, 15))).toEqual({ since: "2026-11-09", until: "2026-11-15" });
  });

  it("covers the whole month", () => {
    expect(periodRange("mese", today)).toEqual({ since: "2026-11-01", until: "2026-11-30" });
    expect(periodRange("mese", new Date(2028, 1, 10))).toEqual({ since: "2028-02-01", until: "2028-02-29" });
  });

  it("covers the whole year", () => {
    expect(periodRange("anno", today)).toEqual({ since: "2026-01-01", until: "2026-12-31" });
  });

  it("uses the local date even late in the evening", () => {
    expect(periodRange("oggi", new Date(2026, 10, 12, 23, 59))).toEqual({ since: "2026-11-12", until: "2026-11-12" });
  });
});
