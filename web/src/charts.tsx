// Grafici a una serie, in HTML: colonne con asse e tooltip, barre orizzontali con il valore scritto.
import type { ReactNode } from "react";
import { niceTicks } from "./chart";
import { formatNumber } from "./format";

export interface Column {
  key: string;
  label: string; // sotto l'asse; vuoto per non affollarlo
  value: number;
  tip: string; // tooltip e nome accessibile
}

export function ColumnChart({ title, columns }: { title: string; columns: Column[] }) {
  const peak = Math.max(0, ...columns.map((column) => column.value));
  const ticks = niceTicks(peak);
  const top = ticks[ticks.length - 1];
  const peakIndex = columns.findIndex((column) => column.value === peak);
  return (
    <div className="columns" role="group" aria-label={title}>
      <div className="columns-axis" aria-hidden="true">
        {ticks.map((tick) => (
          <span key={tick} style={{ bottom: `${(tick / top) * 100}%` }}>
            {formatNumber(tick)}
          </span>
        ))}
      </div>
      <div className="columns-plot">
        {ticks.slice(1).map((tick) => (
          <div key={tick} className="gridline" style={{ bottom: `${(tick / top) * 100}%` }} />
        ))}
        {columns.map((column, index) => (
          <div key={column.key} className={`column ${edge(index, columns.length)}`} tabIndex={0} aria-label={column.tip}>
            <div className="column-bar" style={{ height: `${(column.value / top) * 100}%` }}>
              {index === peakIndex && peak > 0 && <span className="column-cap">{formatNumber(peak)}</span>}
            </div>
            <span className="tip" role="tooltip">
              {column.tip}
            </span>
          </div>
        ))}
      </div>
      <div className="columns-labels" aria-hidden="true">
        {columns.map((column) => (
          <span key={column.key}>{column.label}</span>
        ))}
      </div>
    </div>
  );
}

function edge(index: number, count: number): string {
  if (index < 2) return "start";
  if (index >= count - 2) return "end";
  return "";
}

export interface BarItem {
  key: string;
  label: ReactNode;
  value: number;
  display: string;
}

export function BarList({ title, items }: { title: string; items: BarItem[] }) {
  if (items.length === 0) return <p className="empty">Nessun dato.</p>;
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <ul className="bars" aria-label={title}>
      {items.map((item) => (
        <li key={item.key}>
          <span className="bars-label">{item.label}</span>
          <span className="bars-value">{item.display}</span>
          <span className="bars-track" aria-hidden="true">
            <span className="bars-bar" style={{ width: `${(item.value / max) * 100}%` }} />
          </span>
        </li>
      ))}
    </ul>
  );
}
