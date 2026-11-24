// Tipi e chiamate dell'API di WatchLog (`watchlog api`). Date ISO; le mostra format.ts.
import { useEffect, useState } from "react";

export interface NameCount { name: string; count: number }
export interface DecadeCount { decade: number; count: number }
export interface MonthCount { month: string; viewings: number; minutes: number }
export interface DayCount { day: string; count: number }
export interface FilmRuntime { title: string; minutes: number }
export interface Streak { days: number; start: string; end: string }
export interface Rewatch { user: string; title: string; times: number }
export interface PeriodRecord { period: "giorno" | "settimana" | "mese" | "anno"; count: number; start: string; end: string }

export interface Stats {
  viewings: number;
  distinct_films: number;
  rewatches: number;
  runtime_minutes: number;
  viewings_without_runtime: number;
  average_rating: number | null;
  rated_viewings: number;
  average_runtime_minutes: number | null;
  longest_film: FilmRuntime | null;
  shortest_film: FilmRuntime | null;
  longest_streak: Streak | null;
  top_genres: NameCount[];
  top_directors: NameCount[];
  decades: DecadeCount[];
  per_month: MonthCount[];
  weekdays: number[]; // da lunedì a domenica
  busiest_days: DayCount[];
  most_rewatched: Rewatch[];
  records: PeriodRecord[];
}

export interface Group {
  users: { name: string; viewings: number; runtime_minutes: number }[];
  most_watched: { title: string; views: number; viewers: number }[];
  seen_by_all: string[];
}

export interface StatsResponse { stats: Stats; group: Group | null }

export interface Viewing {
  id: number;
  watched_on: string;
  user: string;
  title: string;
  year: number | null;
  rating: number | null;
}

export interface Candidate {
  tmdb_id: number;
  label: string;
}

export interface ViewingIn {
  user: string;
  film: string;
  watched_on?: string | null;
  rating?: number | null;
  tmdb_id?: number;
  confirm_duplicate?: boolean;
}

export interface ViewingCreated {
  message: string;
}

export interface ViewingPatch {
  watched_on?: string;
  film?: string;
  tmdb_id?: number;
}

export interface ImportSummary {
  entries: number;
  inserted: number;
  duplicates: number;
  new_movies: number;
  unmapped: number;
  unresolved: number;
  unresolved_viewings: number;
  probable_duplicates: number;
  suspicious_dates: number;
  anomalies: number;
}

export interface ImportResponse {
  summary: ImportSummary;
  text: string;
}

export interface ConflictDetail {
  status: "ambiguous" | "duplicate" | "rejected";
  message: string;
  candidates?: Candidate[];
}

export function isConflictDetail(detail: unknown): detail is ConflictDetail {
  if (typeof detail !== "object" || detail === null) return false;
  const value = detail as Partial<ConflictDetail>;
  return typeof value.status === "string" && typeof value.message === "string";
}

/** Il testo da mostrare per un `detail` dell'API: stringa, errore di validazione o conflitto. */
export function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown };
    if (typeof first?.msg === "string") return first.msg.replace(/^Value error,\s*/, "");
  }
  if (isConflictDetail(detail)) return detail.message;
  return "Errore imprevisto.";
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(detailMessage(detail));
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) return "API non raggiungibile.";
  return error instanceof Error ? error.message : "Errore imprevisto.";
}

export function apiUrl(path: string, params: Record<string, string | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

export interface Loaded<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

/** Carica `url` e lo ricarica quando cambia; durante il caricamento tiene i dati precedenti. */
export function useApi<T>(url: string): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true }));
    fetch(url, { signal: controller.signal })
      .then((response) => readJson<T>(response))
      .then((data) => setState({ data, loading: false }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ error: errorMessage(error), loading: false });
      });
    return () => controller.abort();
  }, [url]);
  return state;
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>(path, "POST", body);
}

/** Una scrittura con il metodo indicato; senza corpo, come DELETE, non manda il Content-Type. */
export async function sendJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return readJson<T>(response);
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let detail: unknown = `Errore ${response.status}`;
  try {
    const body = await response.json();
    detail = "detail" in body ? body.detail : body;
  } catch {
    // risposta senza JSON: basta lo stato
  }
  throw new ApiError(response.status, detail);
}
