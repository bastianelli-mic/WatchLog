import { useEffect, useState } from "react";
import { apiUrl, useApi, type Viewing } from "./api";
import { formatDate, formatNumber, formatRating } from "./format";
import type { Range } from "./period";

export function ViewingsView({ user, range }: { user: string; range: Range }) {
  const [title, setTitle] = useState("");
  const search = useDebounced(title.trim(), 250);
  const { data, error, loading } = useApi<Viewing[]>(apiUrl("/api/viewings", { user, ...range, title: search }));
  const showUser = user === "";
  return (
    <section className="card">
      <div className="list-head">
        <input
          type="search"
          className="search"
          placeholder="Cerca un titolo"
          aria-label="Cerca un titolo"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        {data && <span className="muted">{data.length === 1 ? "1 visione" : `${formatNumber(data.length)} visioni`}</span>}
      </div>
      {error ? (
        <p className="notice">{error}</p>
      ) : !data ? (
        <p className="notice muted">Caricamento…</p>
      ) : data.length === 0 ? (
        <p className="notice muted">Nessuna visione trovata con questi filtri.</p>
      ) : (
        <div className={loading ? "table-scroll dim" : "table-scroll"}>
          <table className="viewings">
            <thead>
              <tr>
                <th className="num fit">#</th>
                <th className="fit">Data</th>
                {showUser && <th className="fit">Utente</th>}
                <th>Film</th>
                <th className="num fit">Voto</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, index) => (
                <tr key={row.id}>
                  <td className="num-text fit muted">#{data.length - index}</td>
                  <td className="num-text fit">{formatDate(row.watched_on)}</td>
                  {showUser && <td className="fit">{row.user}</td>}
                  <td>
                    {row.title}
                    {row.year !== null && <span className="muted"> ({row.year})</span>}
                  </td>
                  <td className="num fit">{row.rating === null ? <span className="muted">—</span> : formatRating(row.rating)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
