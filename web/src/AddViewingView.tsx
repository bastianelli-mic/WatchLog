import { useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  errorMessage,
  isConflictDetail,
  postJson,
  type Candidate,
  type ViewingCreated,
  type ViewingIn,
} from "./api";

const RATINGS = Array.from({ length: 10 }, (_, index) => (index + 1) / 2);

type Pending =
  | { kind: "candidates"; message: string; candidates: Candidate[] }
  | { kind: "duplicate"; message: string };

export function AddViewingView({ user, users, onChanged }: { user: string; users: string[]; onChanged: () => void }) {
  const [chosenUser, setChosenUser] = useState("");
  const [film, setFilm] = useState("");
  const [watchedOn, setWatchedOn] = useState(todayIso);
  const [rating, setRating] = useState("");
  const [chosenTmdbId, setChosenTmdbId] = useState<number | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chosenUser && users.length > 0) setChosenUser(users[0]);
  }, [chosenUser, users]);

  const author = user || chosenUser || users[0] || "";

  function resetFeedback() {
    setPending(null);
    setSaved(null);
    setError(null);
    setChosenTmdbId(undefined);
  }

  async function send(overrides: { tmdb_id?: number; confirm_duplicate?: boolean } = {}) {
    if (!author || !film.trim()) return;
    const body: ViewingIn = {
      user: author,
      film: film.trim(),
      watched_on: watchedOn || null,
      rating: rating === "" ? null : Number(rating),
      tmdb_id: overrides.tmdb_id ?? chosenTmdbId,
      confirm_duplicate: overrides.confirm_duplicate,
    };
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const result = await postJson<ViewingCreated>("/api/viewings", body);
      setSaved(result.message);
      setPending(null);
      setChosenTmdbId(undefined);
      setFilm("");
      setRating("");
      onChanged();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409 && isConflictDetail(caught.detail)) {
        const detail = caught.detail;
        if (detail.status === "ambiguous" && detail.candidates && detail.candidates.length > 0) {
          setPending({ kind: "candidates", message: detail.message, candidates: detail.candidates });
        } else if (detail.status === "duplicate") {
          setPending({ kind: "duplicate", message: detail.message });
        } else {
          setError(detail.message);
        }
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  return (
    <section className="card">
      <h2>Nuova visione</h2>
      <form className="form" onSubmit={submit}>
        {user ? (
          <p className="form-author">
            Inserisci come <strong>{user}</strong>
          </p>
        ) : (
          <label className="field">
            <span>Utente</span>
            <select
              value={author}
              onChange={(event) => {
                setChosenUser(event.target.value);
                resetFeedback();
              }}
              disabled={users.length === 0}
            >
              {users.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="field">
          <span>Film</span>
          <input
            type="text"
            value={film}
            placeholder="Titolo (anno)"
            required
            onChange={(event) => {
              setFilm(event.target.value);
              resetFeedback();
            }}
          />
        </label>

        <div className="form-row">
          <label className="field">
            <span>Data</span>
            <input
              type="date"
              value={watchedOn}
              onChange={(event) => {
                setWatchedOn(event.target.value);
                resetFeedback();
              }}
            />
          </label>
          <label className="field">
            <span>Voto</span>
            <select
              value={rating}
              onChange={(event) => {
                setRating(event.target.value);
                resetFeedback();
              }}
            >
              <option value="">Nessun voto</option>
              {RATINGS.map((value) => (
                <option key={value} value={value}>
                  {String(value).replace(".", ",")}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="form-actions">
          <button type="submit" className="button primary" disabled={busy || !author || !film.trim()}>
            {busy ? "Salvataggio…" : "Registra visione"}
          </button>
          <span className="muted">Con la data vuota si usa oggi.</span>
        </div>

        {saved && (
          <p className="form-notice success" role="status">
            {saved}
          </p>
        )}
        {error && (
          <p className="form-notice error" role="alert">
            {error}
          </p>
        )}

        {pending?.kind === "candidates" && (
          <div className="form-notice">
            <p>{pending.message}</p>
            <ul className="candidates">
              {pending.candidates.map((candidate) => (
                <li key={candidate.tmdb_id}>
                  <button
                    type="button"
                    className="button"
                    disabled={busy}
                    onClick={() => {
                      setChosenTmdbId(candidate.tmdb_id);
                      void send({ tmdb_id: candidate.tmdb_id });
                    }}
                  >
                    {candidate.label}
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="button" disabled={busy} onClick={() => setPending(null)}>
              Nessuno di questi
            </button>
          </div>
        )}

        {pending?.kind === "duplicate" && (
          <div className="form-notice">
            <p>{pending.message}</p>
            <div className="form-actions">
              <button
                type="button"
                className="button primary"
                disabled={busy}
                onClick={() => void send({ confirm_duplicate: true })}
              >
                Registra di nuovo
              </button>
              <button type="button" className="button" disabled={busy} onClick={() => setPending(null)}>
                Annulla
              </button>
            </div>
          </div>
        )}
      </form>
    </section>
  );
}

function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
