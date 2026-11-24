import type { ViewingPatch } from "./api";

export interface EditableViewing {
  watched_on: string;
  title: string;
  year: number | null;
}

export interface EditDraft {
  watched_on: string;
  film: string;
}

/** Il film come si scrive in chat: `Titolo (anno)`, o solo il titolo se l'anno manca. */
export function filmLabel(viewing: EditableViewing): string {
  return viewing.year === null ? viewing.title : `${viewing.title} (${viewing.year})`;
}

/** Solo i campi cambiati; `null` se non è cambiato nulla. Il film non viene risolto di nuovo se è uguale. */
export function buildEditBody(viewing: EditableViewing, draft: EditDraft): ViewingPatch | null {
  const body: ViewingPatch = {};
  if (draft.watched_on && draft.watched_on !== viewing.watched_on) body.watched_on = draft.watched_on;
  const film = draft.film.trim();
  if (film && film !== filmLabel(viewing)) body.film = film;
  return Object.keys(body).length === 0 ? null : body;
}
