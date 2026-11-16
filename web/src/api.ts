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
      .then(async (response) => {
        if (!response.ok) throw new Error(await errorText(response));
        return (await response.json()) as T;
      })
      .then((data) => setState({ data, loading: false }))
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setState({ error: error instanceof TypeError ? "API non raggiungibile." : error.message, loading: false });
      });
    return () => controller.abort();
  }, [url]);
  return state;
}

async function errorText(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // risposta senza JSON: basta lo stato
  }
  return `Errore ${response.status}`;
}
