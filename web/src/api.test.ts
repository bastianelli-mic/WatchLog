import { describe, expect, it } from "vitest";
import { detailMessage, isConflictDetail } from "./api";

describe("detailMessage", () => {
  it("uses a string detail", () => {
    expect(detailMessage("utente non trovato")).toBe("utente non trovato");
  });

  it("uses the first validation message without the pydantic prefix", () => {
    expect(detailMessage([{ msg: "Value error, il voto va da 0,5 a 5 a passi di 0,5" }])).toBe(
      "il voto va da 0,5 a 5 a passi di 0,5",
    );
  });

  it("uses the message of a conflict detail", () => {
    expect(detailMessage({ status: "duplicate", message: "Hai già registrato il film." })).toBe(
      "Hai già registrato il film.",
    );
  });

  it("falls back when the detail is missing", () => {
    expect(detailMessage(null)).toBe("Errore imprevisto.");
  });
});

describe("isConflictDetail", () => {
  it("accepts an object with status and message", () => {
    expect(isConflictDetail({ status: "ambiguous", message: "quale?", candidates: [] })).toBe(true);
  });

  it("rejects other values", () => {
    expect(isConflictDetail("nope")).toBe(false);
    expect(isConflictDetail({ status: "ambiguous" })).toBe(false);
    expect(isConflictDetail(null)).toBe(false);
  });
});
