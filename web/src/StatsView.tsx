import type { ReactNode } from "react";
import { apiUrl, useApi, type PeriodRecord, type Stats, type StatsResponse } from "./api";
import { fillMonths, monthLabel } from "./chart";
import { BarList, ColumnChart, type Column } from "./charts";
import { formatDate, formatDuration, formatMonth, formatNumber, formatRating } from "./format";
import type { Range } from "./period";

const WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"];

export function StatsView({ user, range }: { user: string; range: Range }) {
  const { data, error, loading } = useApi<StatsResponse>(apiUrl("/api/stats", { user, ...range }));
  if (error) return <p className="notice">{error}</p>;
  if (!data) return <p className="notice muted">Caricamento…</p>;
  const { stats, group } = data;
  return (
    <div className={loading ? "dim" : undefined}>
      {stats.viewings === 0 ? (
        <p className="notice muted">Nessuna visione in questo periodo.</p>
      ) : (
        <>
          <Tiles stats={stats} />
          <div className="cards">
            <Card title="Visioni per mese" wide>
              <MonthChart stats={stats} />
            </Card>
            {group && (
              <>
                <Card title="Classifica utenti">
                  <BarList
                    title="Classifica utenti"
                    items={group.users.map((row) => ({
                      key: row.name,
                      label: row.name,
                      value: row.viewings,
                      display: `${visions(row.viewings)} · ${formatDuration(row.runtime_minutes)}`,
                    }))}
                  />
                </Card>
                <Card title="Film più visti">
                  <BarList
                    title="Film più visti"
                    items={group.most_watched.map((row) => ({
                      key: row.title,
                      label: row.title,
                      value: row.views,
                      display: `${visions(row.views)} · ${row.viewers === 1 ? "1 persona" : `${row.viewers} persone`}`,
                    }))}
                  />
                </Card>
              </>
            )}
            <Card title="Generi">
              <BarList title="Generi" items={stats.top_genres.map(named)} />
            </Card>
            <Card title="Registi">
              <BarList title="Registi" items={stats.top_directors.map(named)} />
            </Card>
            <Card title="Giorni della settimana">
              <WeekdayChart weekdays={stats.weekdays} />
            </Card>
            <Card title="Decenni">
              <BarList
                title="Decenni"
                items={stats.decades.map((row) => ({
                  key: String(row.decade),
                  label: decadeName(row.decade),
                  value: row.count,
                  display: formatNumber(row.count),
                }))}
              />
            </Card>
            <Card title="Durata">
              <Facts
                rows={[
                  ["Durata media", stats.average_runtime_minutes === null ? "—" : formatDuration(stats.average_runtime_minutes)],
                  ["Film più lungo", stats.longest_film ? <Film {...stats.longest_film} /> : "—"],
                  ["Film più corto", stats.shortest_film ? <Film {...stats.shortest_film} /> : "—"],
                  ...(stats.viewings_without_runtime > 0
                    ? [["Senza durata", visions(stats.viewings_without_runtime)] as [string, ReactNode]]
                    : []),
                ]}
              />
            </Card>
            <Card title="Record">
              <Facts rows={stats.records.map((record) => [recordName(record), <RecordValue record={record} />])} />
            </Card>
            <Card title="Giorni più intensi">
              <BarList
                title="Giorni più intensi"
                items={stats.busiest_days.map((row) => ({
                  key: row.day,
                  label: formatDate(row.day),
                  value: row.count,
                  display: visions(row.count),
                }))}
              />
            </Card>
            <Card title="Più rivisti">
              {stats.most_rewatched.length === 0 ? (
                <p className="empty">Nessun film rivisto.</p>
              ) : (
                <BarList
                  title="Più rivisti"
                  items={stats.most_rewatched.map((row) => ({
                    key: `${row.user}:${row.title}`,
                    label: group ? `${row.title} · ${row.user}` : row.title,
                    value: row.times,
                    display: `${row.times} volte`,
                  }))}
                />
              )}
            </Card>
            {group && (
              <Card title="Visti da tutti" wide>
                {group.seen_by_all.length === 0 ? (
                  <p className="empty">Nessun film visto da tutti.</p>
                ) : (
                  <ul className="chips">
                    {group.seen_by_all.map((title) => (
                      <li key={title}>{title}</li>
                    ))}
                  </ul>
                )}
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Tiles({ stats }: { stats: Stats }) {
  const streak = stats.longest_streak;
  return (
    <div className="tiles">
      <Tile label="Visioni" value={formatNumber(stats.viewings)} detail={`${formatNumber(stats.distinct_films)} film diversi`} />
      <Tile
        label="Tempo totale"
        value={formatDuration(stats.runtime_minutes)}
        detail={stats.average_runtime_minutes === null ? undefined : `in media ${formatDuration(stats.average_runtime_minutes)}`}
      />
      <Tile
        label="Voto medio"
        value={stats.average_rating === null ? "—" : formatRating(stats.average_rating)}
        detail={stats.rated_viewings === 0 ? "nessun voto" : `su 5 · ${formatNumber(stats.rated_viewings)} votate`}
      />
      <Tile
        label="Serie più lunga"
        value={streak ? (streak.days === 1 ? "1 giorno" : `${streak.days} giorni`) : "—"}
        detail={streak ? span(streak.start, streak.end) : undefined}
      />
    </div>
  );
}

function Tile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {detail && <span className="tile-detail">{detail}</span>}
    </div>
  );
}

function Card({ title, wide, children }: { title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section className={wide ? "card wide" : "card"}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="facts">
      {rows.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Film({ title, minutes }: { title: string; minutes: number }) {
  return (
    <>
      {title} <span className="muted">· {formatDuration(minutes)}</span>
    </>
  );
}

function MonthChart({ stats }: { stats: Stats }) {
  const months = fillMonths(stats.per_month);
  const columns: Column[] = months.map((row) => ({
    key: row.month,
    label: monthLabel(row.month, months.length),
    value: row.viewings,
    tip: `${formatMonth(row.month)}: ${visions(row.viewings)}, ${formatDuration(row.minutes)}`,
  }));
  return (
    <>
      <ColumnChart title="Visioni per mese" columns={columns} />
      <details className="table-view">
        <summary>Tabella</summary>
        <table>
          <thead>
            <tr>
              <th>Mese</th>
              <th className="num">Visioni</th>
              <th className="num">Tempo</th>
            </tr>
          </thead>
          <tbody>
            {months.map((row) => (
              <tr key={row.month}>
                <td>{formatMonth(row.month)}</td>
                <td className="num">{formatNumber(row.viewings)}</td>
                <td className="num">{formatDuration(row.minutes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function WeekdayChart({ weekdays }: { weekdays: number[] }) {
  const columns: Column[] = weekdays.map((count, index) => ({
    key: WEEKDAYS[index],
    label: WEEKDAYS[index].slice(0, 3),
    value: count,
    tip: `${WEEKDAYS[index]}: ${visions(count)}`,
  }));
  return (
    <>
      <ColumnChart title="Giorni della settimana" columns={columns} />
      <details className="table-view">
        <summary>Tabella</summary>
        <table>
          <tbody>
            {weekdays.map((count, index) => (
              <tr key={WEEKDAYS[index]}>
                <td>{WEEKDAYS[index]}</td>
                <td className="num">{formatNumber(count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function RecordValue({ record }: { record: PeriodRecord }) {
  const when =
    record.period === "giorno"
      ? formatDate(record.start)
      : record.period === "settimana"
        ? span(record.start, record.end)
        : record.period === "mese"
          ? formatMonth(record.start.slice(0, 7))
          : record.start.slice(0, 4);
  return (
    <>
      {visions(record.count)} <span className="muted">· {when}</span>
    </>
  );
}

function recordName(record: PeriodRecord): string {
  return { giorno: "Giorno", settimana: "Settimana", mese: "Mese", anno: "Anno" }[record.period];
}

function named(row: { name: string; count: number }) {
  return { key: row.name, label: row.name, value: row.count, display: formatNumber(row.count) };
}

function visions(count: number): string {
  return count === 1 ? "1 visione" : `${formatNumber(count)} visioni`;
}

function decadeName(decade: number): string {
  return decade >= 2000 ? `Anni ${decade}` : `Anni ${String(decade % 100).padStart(2, "0")}`;
}

function span(start: string, end: string): string {
  return start === end ? formatDate(start) : `${formatDate(start)} – ${formatDate(end)}`;
}
