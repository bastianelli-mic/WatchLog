import { Fragment, useEffect, useState } from "react";
import { apiUrl, useApi, type Viewing } from "./api";
import { formatDate, formatNumber, formatRating } from "./format";
import type { Range } from "./period";
import { ViewingPanel, type PanelMode } from "./ViewingPanel";

export function ViewingsView({
  user,
  range,
  onEdited,
}: {
  user: string;
  range: Range;
  onEdited: (message: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [active, setActive] = useState<{ id: number; mode: PanelMode } | null>(null);
  const search = useDebounced(title.trim(), 250);
  const { data, error, loading } = useApi<Viewing[]>(apiUrl("/api/viewings", { user, ...range, title: search }));
  const showUser = user === "";
  const columns = showUser ? 7 : 6;

  function pick(id: number, mode: PanelMode) {
    setActive((current) => (current?.id === id && current.mode === mode ? null : { id, mode }));
  }

  return (
    <section className="card">
      <div className="list-head">
        <input
          type="search"
          className="search"
          placeholder="Cerca un titolo"
          aria-label="Cerca un titolo"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setActive(null);
          }}
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
        <>
          <p className="list-legend muted">
            <code>#</code> è la posizione in questo elenco (<code>1</code> = la più vecchia). <code>ID</code>{" "}
            identifica la visione: non cambia con i filtri ed è lo stesso numero di <code>/visioni</code>,{" "}
            <code>/modifica</code> e <code>/annulla</code>.
          </p>
          <div className={loading ? "table-scroll dim" : "table-scroll"}>
            <table className="viewings">
              <thead>
                <tr>
                  <th className="num fit" title="Posizione nell'elenco filtrato: 1 = la più vecchia">
                    #
                  </th>
                  <th className="num fit" title="Identificativo fisso della visione: non cambia con i filtri">
                    ID
                  </th>
                  <th className="fit">Data</th>
                  {showUser && <th className="fit">Utente</th>}
                  <th>Film</th>
                  <th className="num fit">Voto</th>
                  <th className="fit">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {data.map((row, index) => (
                  <Fragment key={row.id}>
                    <tr>
                      <td className="num fit muted">#{data.length - index}</td>
                      <td className="num fit muted">{row.id}</td>
                      <td className="num-text fit">{formatDate(row.watched_on)}</td>
                      {showUser && <td className="fit">{row.user}</td>}
                      <td>
                        {row.title}
                        {row.year !== null && <span className="muted"> ({row.year})</span>}
                      </td>
                      <td className="num fit">
                        {row.rating === null ? <span className="muted">—</span> : formatRating(row.rating)}
                      </td>
                      <td className="fit actions">
                        <div className="row-actions">
                          <button
                            type="button"
                            className="button small"
                            aria-expanded={active?.id === row.id && active.mode === "edit"}
                            onClick={() => pick(row.id, "edit")}
                          >
                            Modifica
                          </button>
                          <button
                            type="button"
                            className="button small"
                            aria-expanded={active?.id === row.id && active.mode === "rating"}
                            onClick={() => pick(row.id, "rating")}
                          >
                            Voto
                          </button>
                          <button
                            type="button"
                            className="button small"
                            aria-expanded={active?.id === row.id && active.mode === "cancel"}
                            onClick={() => pick(row.id, "cancel")}
                          >
                            Annulla
                          </button>
                        </div>
                      </td>
                    </tr>
                    {active?.id === row.id && (
                      <tr className="panel-row">
                        <td colSpan={columns}>
                          <ViewingPanel
                            key={`${row.id}-${active.mode}`}
                            viewing={row}
                            mode={active.mode}
                            onClose={() => setActive(null)}
                            onDone={(message) => {
                              setActive(null);
                              onEdited(message);
                            }}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
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
