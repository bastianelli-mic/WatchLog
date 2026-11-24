import { describe, expect, it } from "vitest";
import { buildEditBody, filmLabel } from "./viewingEdit";

const viewing = { watched_on: "2026-07-05", title: "Heat", year: 1995 };

describe("filmLabel", () => {
  it("adds the year when there is one", () => {
    expect(filmLabel(viewing)).toBe("Heat (1995)");
  });

  it("uses only the title when the year is missing", () => {
    expect(filmLabel({ ...viewing, year: null })).toBe("Heat");
  });
});

describe("buildEditBody", () => {
  it("returns null when nothing changed", () => {
    expect(buildEditBody(viewing, { watched_on: "2026-07-05", film: "Heat (1995)" })).toBeNull();
  });

  it("sends only the date when the film is untouched", () => {
    expect(buildEditBody(viewing, { watched_on: "2026-07-06", film: "Heat (1995)" })).toEqual({
      watched_on: "2026-07-06",
    });
  });

  it("sends only the film when the date is untouched", () => {
    expect(buildEditBody(viewing, { watched_on: "2026-07-05", film: "Heat - La sfida (1995)" })).toEqual({
      film: "Heat - La sfida (1995)",
    });
  });

  it("sends both when both changed", () => {
    expect(buildEditBody(viewing, { watched_on: "2026-07-06", film: "Il sorpasso (1962)" })).toEqual({
      watched_on: "2026-07-06",
      film: "Il sorpasso (1962)",
    });
  });

  it("ignores spaces around the film", () => {
    expect(buildEditBody(viewing, { watched_on: "2026-07-05", film: "  Heat (1995)  " })).toBeNull();
  });

  it("does not send an empty date or film", () => {
    expect(buildEditBody(viewing, { watched_on: "", film: "  " })).toBeNull();
  });

  it("compares the film with the title alone when the year is missing", () => {
    expect(buildEditBody({ ...viewing, year: null }, { watched_on: "2026-07-05", film: "Heat" })).toBeNull();
  });
});
