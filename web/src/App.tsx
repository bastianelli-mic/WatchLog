import { useState } from "react";
import { AddViewingView } from "./AddViewingView";
import { useApi } from "./api";
import { formatDate } from "./format";
import { ImportView } from "./ImportView";
import { PERIODS, periodRange, type Period, type Range } from "./period";
import { StatsView } from "./StatsView";
import { ViewingsView } from "./ViewingsView";

const GROUP = ""; // nessun utente: i dati di tutti
const USER_KEY = "watchlog.user";
const PERIOD_LABELS: Record<Period | "intervallo", string> = {
  tutto: "Sempre",
  anno: "Anno",
  mese: "Mese",
  settimana: "Settimana",
  oggi: "Oggi",
  intervallo: "Intervallo",
};

type Tab = "statistiche" | "visioni" | "aggiungi";
const TABS: { id: Tab; label: string }[] = [
  { id: "statistiche", label: "Statistiche" },
  { id: "visioni", label: "Visioni" },
  { id: "aggiungi", label: "Aggiungi" },
];

export function App() {
  const [refresh, setRefresh] = useState(0);
  const users = useApi<string[]>(refresh ? `/api/users?r=${refresh}` : "/api/users");
  const [chosen, setChosen] = useState(() => readStored(USER_KEY) ?? GROUP);
  const [period, setPeriod] = useState<Period | "intervallo">("tutto");
  const [custom, setCustom] = useState<Range>({});
  const [tab, setTab] = useState<Tab>("statistiche");
  const onChanged = () => setRefresh((value) => value + 1);

  // Un nome ricordato che non esiste più (rinominato in users.yaml) vale come gruppo.
  const user = users.data && !users.data.includes(chosen) ? GROUP : chosen;
  const range = period === "intervallo" ? custom : periodRange(period, new Date());

  const chooseUser = (name: string) => {
    setChosen(name);
    writeStored(USER_KEY, name);
  };

  return (
    <div className="page">
      <header className="top">
        <div className="brand">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect width="24" height="24" rx="6" />
            <path d="M10 7.5v9l7-4.5z" />
          </svg>
          WatchLog
        </div>
        <nav className="tabs" role="tablist" aria-label="Sezioni">
          {TABS.map(({ id, label }) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>

      <div className="filters">
        <label className="field">
          <span>Utente</span>
          <select value={user} onChange={(event) => chooseUser(event.target.value)}>
            <option value={GROUP}>Gruppo</option>
            {users.data?.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {tab !== "aggiungi" && (
          <>
            <div className="segmented" role="radiogroup" aria-label="Periodo">
              {[...PERIODS, "intervallo" as const].map((name) => (
                <button key={name} role="radio" aria-checked={period === name} onClick={() => setPeriod(name)}>
                  {PERIOD_LABELS[name]}
                </button>
              ))}
            </div>
            {period === "intervallo" && (
              <div className="range">
                <label className="field">
                  <span>Dal</span>
                  <input
                    type="date"
                    value={custom.since ?? ""}
                    onChange={(event) => setCustom({ ...custom, since: event.target.value || undefined })}
                  />
                </label>
                <label className="field">
                  <span>Al</span>
                  <input
                    type="date"
                    value={custom.until ?? ""}
                    onChange={(event) => setCustom({ ...custom, until: event.target.value || undefined })}
                  />
                </label>
              </div>
            )}
          </>
        )}
      </div>
      {tab !== "aggiungi" && <p className="scope">{describe(user, range)}</p>}

      <main>
        {tab === "statistiche" && <StatsView key={`stats-${refresh}`} user={user} range={range} />}
        {tab === "visioni" && <ViewingsView key={`viewings-${refresh}`} user={user} range={range} />}
        {tab === "aggiungi" && (
          <div className="cards">
            <AddViewingView user={user} users={users.data ?? []} onChanged={onChanged} />
            <ImportView onChanged={onChanged} />
          </div>
        )}
      </main>
    </div>
  );
}

function describe(user: string, range: Range): string {
  const who = user === GROUP ? "Tutto il gruppo" : user;
  if (range.since && range.until) {
    return range.since === range.until
      ? `${who} · ${formatDate(range.since)}`
      : `${who} · dal ${formatDate(range.since)} al ${formatDate(range.until)}`;
  }
  if (range.since) return `${who} · dal ${formatDate(range.since)}`;
  if (range.until) return `${who} · fino al ${formatDate(range.until)}`;
  return `${who} · da sempre`;
}

// Il browser può negare l'accesso alla memoria locale (navigazione privata): allora non si ricorda nulla.
function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // niente memoria: pazienza
  }
}
