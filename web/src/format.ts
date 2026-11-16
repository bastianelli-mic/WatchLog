// Come si mostrano i dati dell'API: date gg/mm/aaaa e numeri all'italiana.

const integer = new Intl.NumberFormat("it-IT");
const oneDecimal = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 1 });
const shortMonth = new Intl.DateTimeFormat("it-IT", { month: "short" });

export function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
}

/** Il mese abbreviato (`lug`) di un mese ISO `aaaa-mm`. */
export function monthName(isoMonth: string): string {
  const [year, month] = isoMonth.split("-").map(Number);
  return shortMonth.format(new Date(year, month - 1, 1));
}

export function formatMonth(isoMonth: string): string {
  return `${monthName(isoMonth)} ${isoMonth.slice(0, 4)}`;
}

export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${integer.format(hours)} h` : `${integer.format(hours)} h ${rest} min`;
}

export function formatRating(rating: number): string {
  return oneDecimal.format(rating);
}

export function formatNumber(value: number): string {
  return integer.format(value);
}
