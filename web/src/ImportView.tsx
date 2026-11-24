import { useState, type ChangeEvent } from "react";
import { errorMessage, postJson, type ImportResponse } from "./api";
import { formatNumber } from "./format";

const MAX_BYTES = 20 * 1024 * 1024;

type Result = { data: ImportResponse; dryRun: boolean };

export function ImportView({ onChanged }: { onChanged: () => void }) {
  const [fileName, setFileName] = useState("");
  const [chat, setChat] = useState<string | null>(null);
  const [busy, setBusy] = useState<"dry" | "real" | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    setFileName(selected?.name ?? "");
    setChat(null);
    setResult(null);
    setError(null);
    setCopied(false);
    if (!selected) return;
    if (selected.size > MAX_BYTES) {
      setError("File troppo grande: il massimo è 20 MB.");
      return;
    }
    try {
      setChat(await selected.text());
    } catch {
      setError("Impossibile leggere il file.");
    }
  }

  async function run(dryRun: boolean) {
    if (chat === null || busy !== null) return;
    setBusy(dryRun ? "dry" : "real");
    setError(null);
    setResult(null);
    setCopied(false);
    try {
      const data = await postJson<ImportResponse>(`/api/import${dryRun ? "?dry_run=true" : ""}`, { chat });
      setResult({ data, dryRun });
      if (!dryRun) onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function copyReport() {
    if (!result) return;
    setCopied(await copyText(result.data.text));
  }

  return (
    <section className="card">
      <h2>Importa una chat WhatsApp</h2>
      <p className="card-intro muted">
        Esporta la chat senza media e scegli il file <code>.txt</code>. Puoi prima analizzarlo, senza scrivere nulla:
        l'import vero è sicuro da rilanciare e aggiunge solo le visioni nuove.
      </p>
      <div className="form">
        <label className="field">
          <span>File</span>
          <input type="file" accept=".txt,text/plain" onChange={choose} disabled={busy !== null} />
        </label>
        {fileName && (
          <p className="muted">
            {fileName}
            {chat !== null && ` · ${formatNumber(chat.length)} caratteri`}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="button"
            onClick={() => void run(true)}
            disabled={chat === null || busy !== null}
          >
            {busy === "dry" ? "Analisi…" : "Analizza"}
          </button>
          <button
            type="button"
            className="button primary"
            onClick={() => void run(false)}
            disabled={chat === null || busy !== null}
          >
            {busy === "real" ? "Importazione…" : "Importa"}
          </button>
        </div>
        {busy && (
          <p className="form-notice">
            {busy === "dry" ? "Analisi in corso" : "Importazione in corso"}: la prima volta il server interroga TMDB per
            ogni film nuovo e può servire qualche minuto.
          </p>
        )}
        {error && (
          <p className="form-notice error" role="alert">
            {error}
          </p>
        )}
      </div>

      {result && (
        <div className="import-result">
          <div className="tiles import-tiles">
            <Tile label="Righe nel file" value={result.data.summary.entries} />
            <Tile label={result.dryRun ? "Da inserire" : "Inserite"} value={result.data.summary.inserted} />
            <Tile label="Già presenti" value={result.data.summary.duplicates} />
            <Tile label="Film nuovi" value={result.data.summary.new_movies} />
            {result.data.summary.unmapped > 0 && (
              <Tile label="Utenti non mappati" value={result.data.summary.unmapped} />
            )}
            {result.data.summary.unresolved > 0 && (
              <Tile label="Film da risolvere" value={result.data.summary.unresolved} />
            )}
            {result.data.summary.probable_duplicates > 0 && (
              <Tile label="Doppioni probabili" value={result.data.summary.probable_duplicates} />
            )}
            {result.data.summary.suspicious_dates > 0 && (
              <Tile label="Date sospette" value={result.data.summary.suspicious_dates} />
            )}
            {result.data.summary.anomalies > 0 && <Tile label="Anomalie" value={result.data.summary.anomalies} />}
          </div>
          <div className="report-head">
            <h3>Report</h3>
            <button type="button" className="button" onClick={() => void copyReport()}>
              {copied ? "Copiato" : "Copia report"}
            </button>
          </div>
          <pre className="report" tabIndex={0}>
            {result.data.text}
          </pre>
        </div>
      )}
    </section>
  );
}

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{formatNumber(value)}</span>
    </div>
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // sulla LAN in HTTP il browser può negare la clipboard: si prova il vecchio metodo
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  return copied;
}
