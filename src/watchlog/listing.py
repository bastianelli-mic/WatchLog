"""Elenco delle singole visioni, filtrabile, e il testo delle sue pagine."""

from dataclasses import dataclass
from datetime import date

from watchlog.dates import format_iso
from watchlog.db import Database
from watchlog.resolver import normalize
from watchlog.stats import UnknownUser, viewing_filters

MAX_ROWS = 20  # righe per pagina
PAGE_CHARS = 1800  # un messaggio Discord arriva a 2000 caratteri, il resto serve ai blocchi di codice
TITLE_MAX = 60


@dataclass(frozen=True)
class ViewingRow:
    id: int
    watched_on: str
    user: str
    title: str
    year: int | None
    rating: float | None


def list_viewings(
    db: Database,
    user: str | None = None,
    since: date | None = None,
    until: date | None = None,
    title: str | None = None,
) -> list[ViewingRow]:
    """Visioni dalla più recente. `title` cerca una parte del titolo, anche originale, senza badare a maiuscole e accenti."""
    if user is not None and not db.query("SELECT 1 FROM users WHERE name = ?", (user,)):
        raise UnknownUser(f"Utente {user!r} non trovato")
    where, params = viewing_filters(user, since, until)
    rows = db.query(
        "SELECT v.id AS id, v.watched_on AS watched_on, u.name AS user, m.title AS title, "
        "m.original_title AS original_title, m.year AS year, v.rating AS rating "
        "FROM viewing v JOIN movie m ON m.tmdb_id = v.movie_id JOIN users u ON u.id = v.user_id "
        f"WHERE v.deleted_at IS NULL{where} ORDER BY v.watched_on DESC, v.id DESC",
        params,
    )
    if title:
        needle = normalize(title)
        rows = [r for r in rows if needle in normalize(r["title"]) or needle in normalize(r["original_title"] or "")]
    return [ViewingRow(r["id"], r["watched_on"], r["user"], r["title"], r["year"], r["rating"]) for r in rows]


def render_pages(
    rows: list[ViewingRow], header: str, show_user: bool, max_rows: int = MAX_ROWS, limit: int = PAGE_CHARS
) -> list[str]:
    """Pagine pronte per Discord, in blocco di codice: al massimo `max_rows` righe e `limit` caratteri ciascuna."""
    if not rows:
        return []
    id_width = max(len(str(row.id)) for row in rows)
    user_width = max(len(row.user) for row in rows) if show_user else 0
    lines = [_line(row, id_width, user_width) for row in rows]

    reserve = len(header) + 60  # spazio per il contatore delle pagine e dei blocchi di codice
    pages: list[list[str]] = []
    current: list[str] = []
    size = reserve
    for line in lines:
        if current and (len(current) >= max_rows or size + len(line) + 1 > limit):
            pages.append(current)
            current, size = [], reserve
        current.append(line)
        size += len(line) + 1
    pages.append(current)

    noun = "visione" if len(rows) == 1 else "visioni"
    return [
        f"```\n{header}  [{len(rows)} {noun}, pagina {number}/{len(pages)}]\n" + "\n".join(page) + "\n```"
        for number, page in enumerate(pages, start=1)
    ]


def _line(row: ViewingRow, id_width: int, user_width: int) -> str:
    title = row.title if len(row.title) <= TITLE_MAX else row.title[: TITLE_MAX - 1] + "…"
    label = f"{title} ({row.year})" if row.year else title
    parts = [f"#{row.id:<{id_width}}", format_iso(row.watched_on)]
    if user_width:
        parts.append(f"{row.user:<{user_width}}")
    parts.append(label)
    line = "  ".join(parts)
    if row.rating is not None:
        line += f"  ★{row.rating:g}".replace(".", ",")
    return line
