"""Statistiche sulle visualizzazioni, per un utente o per tutto il gruppo."""

from dataclasses import dataclass, field

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
    per_month: list[tuple[str, int]] = field(default_factory=list)
    most_rewatched: list[Rewatch] = field(default_factory=list)


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


def compute_stats(db: Database, user: str | None = None, top_n: int = TOP_N) -> Stats:
    """Statistiche del gruppo, o di un solo utente se `user` è indicato (nome interno)."""
    if user is not None and not db.query("SELECT 1 FROM users WHERE name = ?", (user,)):
        raise UnknownUser(f"Utente {user!r} non trovato")
    where = " AND u.name = :user" if user is not None else ""
    params = {"user": user} if user is not None else {}
    limited = {**params, "limit": top_n}

    totals = db.query(
        "SELECT COUNT(*) AS views, COUNT(DISTINCT m.tmdb_id) AS films, "
        "COUNT(DISTINCT v.user_id || ':' || m.tmdb_id) AS pairs, "
        "COALESCE(SUM(m.runtime_minutes), 0) AS minutes, COALESCE(SUM(m.runtime_minutes IS NULL), 0) AS missing, "
        f"AVG(v.rating) AS rating, COUNT(v.rating) AS rated {_BASE} {_LIVE}{where}",
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
            "SELECT g.name AS label, COUNT(*) AS n "
            f"{_BASE} {_GENRES} {_LIVE}{where} GROUP BY g.id ORDER BY n DESC, g.name LIMIT :limit",
            limited,
        ),
        top_directors=_pairs(
            db,
            "SELECT p.name AS label, COUNT(*) AS n "
            f"{_BASE} {_DIRECTORS} {_LIVE}{where} GROUP BY p.id ORDER BY n DESC, p.name LIMIT :limit",
            limited,
        ),
        decades=_pairs(
            db,
            f"SELECT (m.year / 10) * 10 AS label, COUNT(*) AS n {_BASE} {_LIVE}{where} AND m.year IS NOT NULL "
            "GROUP BY label ORDER BY label",
            params,
        ),
        per_month=_pairs(
            db,
            f"SELECT substr(v.watched_on, 1, 7) AS label, COUNT(*) AS n {_BASE} {_LIVE}{where} GROUP BY label ORDER BY label",
            params,
        ),
        most_rewatched=[
            Rewatch(row["user"], row["title"], row["n"])
            for row in db.query(
                f"SELECT u.name AS user, m.title AS title, COUNT(*) AS n {_BASE} {_LIVE}{where} "
                "GROUP BY u.id, m.tmdb_id HAVING n > 1 ORDER BY n DESC, m.title, u.name LIMIT :limit",
                limited,
            )
        ],
    )


def group_extras(db: Database, top_n: int = TOP_N) -> GroupExtras:
    users = [
        UserTotals(row["name"], row["views"], row["minutes"])
        for row in db.query(
            "SELECT u.name AS name, COUNT(*) AS views, COALESCE(SUM(m.runtime_minutes), 0) AS minutes "
            f"{_BASE} {_LIVE} GROUP BY u.id ORDER BY views DESC, u.name"
        )
    ]
    most_watched = [
        FilmCount(row["title"], row["views"], row["viewers"])
        for row in db.query(
            f"SELECT m.title AS title, COUNT(*) AS views, COUNT(DISTINCT v.user_id) AS viewers {_BASE} {_LIVE} "
            "GROUP BY m.tmdb_id ORDER BY views DESC, m.title LIMIT ?",
            (top_n,),
        )
    ]
    seen_by_all = []
    if len(users) > 1:
        seen_by_all = [
            row["title"]
            for row in db.query(
                f"SELECT m.title AS title {_BASE} {_LIVE} GROUP BY m.tmdb_id "
                "HAVING COUNT(DISTINCT v.user_id) = ? ORDER BY m.title",
                (len(users),),
            )
        ]
    return GroupExtras(users, most_watched, seen_by_all)


def _pairs(db: Database, sql: str, params: dict) -> list[tuple]:
    return [(row["label"], row["n"]) for row in db.query(sql, params)]
