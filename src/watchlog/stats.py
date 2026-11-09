"""Statistiche sulle visualizzazioni, per un utente o per tutto il gruppo, in un periodo opzionale."""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from watchlog.db import Database

TOP_N = 5

_BASE = "FROM viewing v JOIN movie m ON m.tmdb_id = v.movie_id JOIN users u ON u.id = v.user_id"
_GENRES = "JOIN movie_genre mg ON mg.movie_id = m.tmdb_id JOIN genre g ON g.id = mg.genre_id"
_DIRECTORS = "JOIN movie_director md ON md.movie_id = m.tmdb_id JOIN person p ON p.id = md.person_id"
_LIVE = "WHERE v.deleted_at IS NULL"


class UnknownUser(Exception):
    pass


@dataclass(frozen=True)
class Rewatch:
    user: str
    title: str
    times: int


@dataclass(frozen=True)
class FilmRuntime:
    title: str
    minutes: int


@dataclass(frozen=True)
class Streak:
    days: int
    start: str  # ISO, primo giorno della serie
    end: str  # ISO, ultimo giorno della serie


@dataclass(frozen=True)
class Record:
    """Il periodo (giorno, settimana, mese o anno) con più visioni, e quante."""

    period: str
    count: int
    start: str  # ISO, primo giorno del periodo
    end: str  # ISO, ultimo giorno del periodo


@dataclass(frozen=True)
class Stats:
    viewings: int
    distinct_films: int
    rewatches: int  # visualizzazioni di un film già visto dallo stesso utente
    runtime_minutes: int
    viewings_without_runtime: int
    average_rating: float | None
    rated_viewings: int
    top_genres: list[tuple[str, int]] = field(default_factory=list)
    top_directors: list[tuple[str, int]] = field(default_factory=list)
    decades: list[tuple[int, int]] = field(default_factory=list)
    per_month: list[tuple[str, int, int]] = field(default_factory=list)  # mese, visualizzazioni, minuti
    most_rewatched: list[Rewatch] = field(default_factory=list)
    average_runtime_minutes: int | None = None
    longest_film: FilmRuntime | None = None
    shortest_film: FilmRuntime | None = None
    longest_streak: Streak | None = None
    weekdays: list[int] = field(default_factory=lambda: [0] * 7)  # da lunedì a domenica
    busiest_days: list[tuple[str, int]] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)  # giorno, settimana, mese, anno


@dataclass(frozen=True)
class UserTotals:
    name: str
    viewings: int
    runtime_minutes: int


@dataclass(frozen=True)
class FilmCount:
    title: str
    views: int
    viewers: int


@dataclass(frozen=True)
class GroupExtras:
    users: list[UserTotals]
    most_watched: list[FilmCount]
    seen_by_all: list[str]


def compute_stats(
    db: Database,
    user: str | None = None,
    top_n: int = TOP_N,
    since: date | None = None,
    until: date | None = None,
) -> Stats:
    """Statistiche del gruppo, o di un solo utente se `user` è indicato (nome interno).

    `since` e `until` limitano per data di visione, estremi inclusi.
    """
    if user is not None and not db.query("SELECT 1 FROM users WHERE name = ?", (user,)):
        raise UnknownUser(f"Utente {user!r} non trovato")
    where, params = viewing_filters(user, since, until)
    limited = {**params, "limit": top_n}

    totals = db.query(
        "SELECT COUNT(*) AS views, COUNT(DISTINCT m.tmdb_id) AS films, "
        "COUNT(DISTINCT v.user_id || ':' || m.tmdb_id) AS pairs, "
        "COALESCE(SUM(m.runtime_minutes), 0) AS minutes, COALESCE(SUM(m.runtime_minutes IS NULL), 0) AS missing, "
        f"AVG(m.runtime_minutes) AS avg_runtime, AVG(v.rating) AS rating, COUNT(v.rating) AS rated "
        f"{_BASE} {_LIVE}{where}",
        params,
    )[0]

    return Stats(
        viewings=totals["views"],
        distinct_films=totals["films"],
        rewatches=totals["views"] - totals["pairs"],
        runtime_minutes=totals["minutes"],
        viewings_without_runtime=totals["missing"],
        average_rating=totals["rating"],
        rated_viewings=totals["rated"],
        top_genres=_pairs(
            db,
            f"SELECT g.name AS label, COUNT(*) AS n {_BASE} {_GENRES} {_LIVE}{where} "
            "GROUP BY g.id ORDER BY n DESC, g.name LIMIT :limit",
            limited,
        ),
        top_directors=_pairs(
            db,
            f"SELECT p.name AS label, COUNT(*) AS n {_BASE} {_DIRECTORS} {_LIVE}{where} "
            "GROUP BY p.id ORDER BY n DESC, p.name LIMIT :limit",
            limited,
        ),
        decades=_pairs(
            db,
            f"SELECT (m.year / 10) * 10 AS label, COUNT(*) AS n {_BASE} {_LIVE}{where} AND m.year IS NOT NULL "
            "GROUP BY label ORDER BY label",
            params,
        ),
        per_month=[
            (row["label"], row["n"], row["minutes"])
            for row in db.query(
                "SELECT substr(v.watched_on, 1, 7) AS label, COUNT(*) AS n, "
                f"COALESCE(SUM(m.runtime_minutes), 0) AS minutes {_BASE} {_LIVE}{where} "
                "GROUP BY label ORDER BY label",
                params,
            )
        ],
        most_rewatched=[
            Rewatch(row["user"], row["title"], row["n"])
            for row in db.query(
                f"SELECT u.name AS user, m.title AS title, COUNT(*) AS n {_BASE} {_LIVE}{where} "
                "GROUP BY u.id, m.tmdb_id HAVING n > 1 ORDER BY n DESC, m.title, u.name LIMIT :limit",
                limited,
            )
        ],
        average_runtime_minutes=None if totals["avg_runtime"] is None else round(totals["avg_runtime"]),
        longest_film=_extreme_film(db, where, params, "DESC"),
        shortest_film=_extreme_film(db, where, params, "ASC"),
        longest_streak=_longest_streak(db, where, params),
        weekdays=_weekdays(db, where, params),
        busiest_days=_pairs(
            db,
            f"SELECT v.watched_on AS label, COUNT(*) AS n {_BASE} {_LIVE}{where} "
            "GROUP BY label ORDER BY n DESC, label LIMIT :limit",
            limited,
        ),
        records=_records(db, where, params),
    )


def group_extras(
    db: Database, top_n: int = TOP_N, since: date | None = None, until: date | None = None
) -> GroupExtras:
    where, params = viewing_filters(None, since, until)
    users = [
        UserTotals(row["name"], row["views"], row["minutes"])
        for row in db.query(
            "SELECT u.name AS name, COUNT(*) AS views, COALESCE(SUM(m.runtime_minutes), 0) AS minutes "
            f"{_BASE} {_LIVE}{where} GROUP BY u.id ORDER BY views DESC, u.name",
            params,
        )
    ]
    most_watched = [
        FilmCount(row["title"], row["views"], row["viewers"])
        for row in db.query(
            f"SELECT m.title AS title, COUNT(*) AS views, COUNT(DISTINCT v.user_id) AS viewers "
            f"{_BASE} {_LIVE}{where} GROUP BY m.tmdb_id ORDER BY views DESC, m.title LIMIT :limit",
            {**params, "limit": top_n},
        )
    ]
    seen_by_all = []
    if len(users) > 1:
        seen_by_all = [
            row["title"]
            for row in db.query(
                f"SELECT m.title AS title {_BASE} {_LIVE}{where} GROUP BY m.tmdb_id "
                "HAVING COUNT(DISTINCT v.user_id) = :users ORDER BY m.title",
                {**params, "users": len(users)},
            )
        ]
    return GroupExtras(users, most_watched, seen_by_all)


def viewing_filters(user: str | None, since: date | None, until: date | None) -> tuple[str, dict]:
    clauses, params = [], {}
    if user is not None:
        clauses.append("u.name = :user")
        params["user"] = user
    if since is not None:
        clauses.append("v.watched_on >= :since")
        params["since"] = since.isoformat()
    if until is not None:
        clauses.append("v.watched_on <= :until")
        params["until"] = until.isoformat()
    return "".join(f" AND {clause}" for clause in clauses), params


def _pairs(db: Database, sql: str, params: dict) -> list[tuple]:
    return [(row["label"], row["n"]) for row in db.query(sql, params)]


def _extreme_film(db: Database, where: str, params: dict, direction: str) -> FilmRuntime | None:
    rows = db.query(
        f"SELECT m.title AS title, m.runtime_minutes AS minutes {_BASE} {_LIVE}{where} "
        f"AND m.runtime_minutes IS NOT NULL ORDER BY m.runtime_minutes {direction}, m.title LIMIT 1",
        params,
    )
    return FilmRuntime(rows[0]["title"], rows[0]["minutes"]) if rows else None


def _weekdays(db: Database, where: str, params: dict) -> list[int]:
    counts = [0] * 7
    rows = db.query(
        f"SELECT CAST(strftime('%w', v.watched_on) AS INTEGER) AS sunday_first, COUNT(*) AS n "
        f"{_BASE} {_LIVE}{where} GROUP BY sunday_first",
        params,
    )
    for row in rows:
        counts[(row["sunday_first"] + 6) % 7] = row["n"]  # SQLite conta da domenica, noi da lunedì
    return counts


def _records(db: Database, where: str, params: dict) -> list[Record]:
    """Il giorno, la settimana (da lunedì a domenica), il mese e l'anno con più visioni; a parità vince il primo."""
    days = [
        (date.fromisoformat(row["day"]), row["n"])
        for row in db.query(f"SELECT v.watched_on AS day, COUNT(*) AS n {_BASE} {_LIVE}{where} GROUP BY day", params)
    ]
    spans = {
        "giorno": lambda day: (day, day),
        "settimana": lambda day: (day - timedelta(days=day.weekday()), day + timedelta(days=6 - day.weekday())),
        "mese": lambda day: (day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])),
        "anno": lambda day: (date(day.year, 1, 1), date(day.year, 12, 31)),
    }
    records = []
    for period, span in spans.items():
        totals: dict[tuple[date, date], int] = {}
        for day, count in days:
            totals[span(day)] = totals.get(span(day), 0) + count
        if totals:
            (start, end), count = min(totals.items(), key=lambda item: (-item[1], item[0]))
            records.append(Record(period, count, start.isoformat(), end.isoformat()))
    return records


def _longest_streak(db: Database, where: str, params: dict) -> Streak | None:
    days = [
        date.fromisoformat(row["day"])
        for row in db.query(f"SELECT DISTINCT v.watched_on AS day {_BASE} {_LIVE}{where} ORDER BY day", params)
    ]
    best: tuple[int, date, date] | None = None
    run_start = previous = None
    for day in days:
        if previous is None or day - previous != timedelta(days=1):
            run_start = day
        previous = day
        length = (day - run_start).days + 1
        if best is None or length > best[0]:
            best = (length, run_start, day)
    return None if best is None else Streak(best[0], best[1].isoformat(), best[2].isoformat())
