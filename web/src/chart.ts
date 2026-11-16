// Calcoli dei grafici, senza DOM.
import type { MonthCount } from "./api";
import { monthName } from "./format";

/** I mesi da primo a ultimo senza buchi: quelli senza visioni valgono zero. */
export function fillMonths(months: MonthCount[]): MonthCount[] {
  if (months.length === 0) return [];
  const known = new Map(months.map((month) => [month.month, month]));
  const [firstYear, firstMonth] = months[0].month.split("-").map(Number);
  const last = months[months.length - 1].month;
  const filled: MonthCount[] = [];
  for (let index = 0; ; index++) {
    const date = new Date(firstYear, firstMonth - 1 + index, 1);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    filled.push(known.get(key) ?? { month: key, viewings: 0, minutes: 0 });
    if (key === last) return filled;
  }
}

/** Tacche dell'asse da zero: passo pulito (1, 2 o 5 per una potenza di dieci, almeno 1), al massimo cinque. */
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const raw = Math.max(max / 4, 1);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= raw)!;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: top / step + 1 }, (_, index) => index * step);
}

/** L'etichetta di un mese sull'asse, secondo quanti mesi ci sono: tutti fino a un anno, i trimestri fino a tre, poi
 * solo gli anni. Gennaio mostra l'anno; vuota dove non serve. */
export function monthLabel(isoMonth: string, count: number): string {
  if (count <= 12) return monthName(isoMonth);
  const month = Number(isoMonth.slice(5));
  if (month === 1) return isoMonth.slice(0, 4);
  return count <= 36 && month % 3 === 1 ? monthName(isoMonth) : "";
}
