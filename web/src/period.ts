// I periodi rapidi del filtro, calcolati sulla data locale del browser.

export const PERIODS = ["tutto", "anno", "mese", "settimana", "oggi"] as const;
export type Period = (typeof PERIODS)[number];

export interface Range {
  since?: string; // ISO, incluso
  until?: string; // ISO, incluso
}

export function periodRange(period: Period, today: Date): Range {
  const y = today.getFullYear();
  const m = today.getMonth();
  const d = today.getDate();
  switch (period) {
    case "tutto":
      return {};
    case "oggi":
      return { since: isoDate(today), until: isoDate(today) };
    case "settimana": {
      const fromMonday = (today.getDay() + 6) % 7; // getDay conta da domenica
      return { since: isoDate(new Date(y, m, d - fromMonday)), until: isoDate(new Date(y, m, d - fromMonday + 6)) };
    }
    case "mese":
      return { since: isoDate(new Date(y, m, 1)), until: isoDate(new Date(y, m + 1, 0)) };
    case "anno":
      return { since: `${y}-01-01`, until: `${y}-12-31` };
  }
}

/** La data locale in formato ISO: `toISOString` userebbe UTC e la sera sbaglierebbe giorno. */
export function isoDate(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}
