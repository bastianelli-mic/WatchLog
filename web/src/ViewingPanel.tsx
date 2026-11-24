import { useState, type FormEvent } from "react";
import {
  ApiError,
  errorMessage,
  isConflictDetail,
  sendJson,
  type Candidate,
  type Viewing,
  type ViewingCreated,
  type ViewingPatch,
} from "./api";
import { formatDate } from "./format";
import { buildEditBody, filmLabel } from "./viewingEdit";

export type PanelMode = "edit" | "rating" | "cancel";

const RATINGS = Array.from({ length: 10 }, (_, index) => (index + 1) / 2);

export function ViewingPanel({
  viewing,
  mode,
  onClose,
  onDone,
}: {
  viewing: Viewing;
  mode: PanelMode;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [watchedOn, setWatchedOn] = useState(viewing.watched_on);
  const [film, setFilm] = useState(filmLabel(viewing));
  const [rating, setRating] = useState(viewing.rating === null ? "" : String(viewing.rating));

  async function run(write: () => Promise<ViewingCreated>) {
    setBusy(true);
    setError(null);
    try {
      onDone((await write()).message);
    } catch (caught) {
      setCandidates(null);
      if (caught instanceof ApiError && caught.status === 409 && isConflictDetail(caught.detail)) {
        if (caught.detail.status === "ambiguous" && caught.detail.candidates?.length) {
          setCandidates(caught.detail.candidates);
        }
        setError(caught.detail.message);
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  function saveEdit(event: FormEvent) {
    event.preventDefault();
    const body = buildEditBody(viewing, { watched_on: watchedOn, film });
    if (body === null) {
      setError("Non hai cambiato nulla.");
      return;
    }
    void run(() => sendJson<ViewingCreated>(`/api/viewings/${viewing.id}`, "PATCH", body));
  }

  function chooseCandidate(candidate: Candidate) {
    const body = buildEditBody(viewing, { watched_on: watchedOn, film });
    if (body === null) {
      setError("Non hai cambiato nulla.");
      return;
    }
    const withId: ViewingPatch = { ...body, tmdb_id: candidate.tmdb_id };
    void run(() => sendJson<ViewingCreated>(`/api/viewings/${viewing.id}`, "PATCH", withId));
  }

  function saveRating() {
    if (rating === "") {
      setError("Scegli un voto.");
      return;
    }
    void run(() =>
      sendJson<ViewingCreated>(`/api/viewings/${viewing.id}/rating`, "PUT", { rating: Number(rating) }),
    );
  }

  return (
    <div className="viewing-panel">
      <div className="panel-head">
        <span className="muted">
          Visione <strong>ID {viewing.id}</strong> · {viewing.user} · {filmLabel(viewing)} del{" "}
          {formatDate(viewing.watched_on)}
        </span>
        <button type="button" className="button small" onClick={onClose} disabled={busy}>
          Chiudi
        </button>
      </div>

      {mode === "edit" && (
        <form className="form" onSubmit={saveEdit}>
          <div className="form-row">
            <label className="field">
              <span>Data</span>
              <input type="date" value={watchedOn} onChange={(event) => setWatchedOn(event.target.value)} />
            </label>
            <label className="field">
              <span>Film</span>
              <input
                type="text"
                value={film}
                placeholder="Titolo (anno)"
                onChange={(event) => setFilm(event.target.value)}
              />
            </label>
          </div>
          <div className="form-actions">
            <button type="submit" className="button primary" disabled={busy}>
              {busy ? "Salvataggio…" : "Salva modifica"}
            </button>
            <span className="muted">Lascia il film com'è per cambiare solo la data.</span>
          </div>
        </form>
      )}

      {mode === "rating" && (
        <div className="form">
          <label className="field">
            <span>Voto</span>
            <select value={rating} onChange={(event) => setRating(event.target.value)}>
              <option value="" disabled>
                Scegli un voto
              </option>
              {RATINGS.map((value) => (
                <option key={value} value={value}>
                  {String(value).replace(".", ",")}
                </option>
              ))}
            </select>
          </label>
          <div className="form-actions">
            <button type="button" className="button primary" onClick={saveRating} disabled={busy || rating === ""}>
              {busy ? "Salvataggio…" : "Salva voto"}
            </button>
            {viewing.rating !== null && (
              <span className="muted">Ora ha {String(viewing.rating).replace(".", ",")}.</span>
            )}
          </div>
        </div>
      )}

      {mode === "cancel" && (
        <div className="form">
          <p className="form-notice">
            La visione sparirà da elenco e statistiche. L'annullamento non si può annullare dalla pagina.
          </p>
          <div className="form-actions">
            <button
              type="button"
              className="button danger"
              disabled={busy}
              onClick={() => void run(() => sendJson<ViewingCreated>(`/api/viewings/${viewing.id}`, "DELETE"))}
            >
              {busy ? "Annullamento…" : "Annulla visione"}
            </button>
            <button type="button" className="button" onClick={onClose} disabled={busy}>
              No
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="form-notice error" role="alert">
          {error}
        </p>
      )}

      {candidates && (
        <ul className="candidates">
          {candidates.map((candidate) => (
            <li key={candidate.tmdb_id}>
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => chooseCandidate(candidate)}
              >
                {candidate.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
