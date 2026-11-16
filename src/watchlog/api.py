"""API HTTP in sola lettura per la pagina web (e un domani l'app): JSON, date in formato ISO."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from watchlog.db import Database
from watchlog.listing import ViewingRow, list_viewings
from watchlog.stats import (
    FilmCount,
    FilmRuntime,
    Record,
    Rewatch,
    Stats,
    Streak,
    UnknownUser,
    UserTotals,
    compute_stats,
    group_extras,
)


class NameCount(BaseModel):
    name: str
    count: int


class DecadeCount(BaseModel):
    decade: int
    count: int


class MonthCount(BaseModel):
    month: str  # aaaa-mm
    viewings: int
    minutes: int


class DayCount(BaseModel):
    day: str
    count: int


class StatsOut(BaseModel):
    viewings: int
    distinct_films: int
    rewatches: int
    runtime_minutes: int
    viewings_without_runtime: int
    average_rating: float | None
    rated_viewings: int
    average_runtime_minutes: int | None
    longest_film: FilmRuntime | None
    shortest_film: FilmRuntime | None
    longest_streak: Streak | None
    top_genres: list[NameCount]
    top_directors: list[NameCount]
    decades: list[DecadeCount]
    per_month: list[MonthCount]
    weekdays: list[int]  # da lunedì a domenica
    busiest_days: list[DayCount]
    most_rewatched: list[Rewatch]
    records: list[Record]


class GroupOut(BaseModel):
    users: list[UserTotals]
    most_watched: list[FilmCount]
    seen_by_all: list[str]


class StatsResponse(BaseModel):
    stats: StatsOut
    group: GroupOut | None  # solo senza `user`: le classifiche del gruppo


def create_app(db_path: Path, web_dir: Path | None = None) -> FastAPI:
    """L'API su `db_path`; se `web_dir` esiste, alla radice si serve anche la pagina web già compilata."""
    app = FastAPI(title="WatchLog")

    def open_db() -> Iterator[Database]:
        if not db_path.is_file():
            raise HTTPException(503, "Database non trovato")
        db = Database.open(db_path)
        try:
            yield db
        finally:
            db.close()

    @app.get("/api/users")
    def users(db: Database = Depends(open_db)) -> list[str]:
        return [row["name"] for row in db.query("SELECT name FROM users ORDER BY name")]

    @app.get("/api/stats")
    def stats(
        user: str | None = None,
        since: date | None = None,
        until: date | None = None,
        db: Database = Depends(open_db),
    ) -> StatsResponse:
        try:
            computed = compute_stats(db, user=user, since=since, until=until)
        except UnknownUser as error:
            raise HTTPException(404, str(error)) from error
        group = group_extras(db, since=since, until=until) if user is None else None
        return StatsResponse(stats=_stats_out(computed), group=None if group is None else GroupOut(**vars(group)))

    @app.get("/api/viewings")
    def viewings(
        user: str | None = None,
        since: date | None = None,
        until: date | None = None,
        title: str | None = None,
        db: Database = Depends(open_db),
    ) -> list[ViewingRow]:
        try:
            return list_viewings(db, user=user, since=since, until=until, title=(title or "").strip() or None)
        except UnknownUser as error:
            raise HTTPException(404, str(error)) from error

    if web_dir is not None and web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")  # dopo le rotte: /api ha la precedenza
    return app


def serve(db_path: Path, web_dir: Path | None, host: str, port: int) -> None:
    import uvicorn  # import tardivo: ai test basta create_app

    uvicorn.run(create_app(db_path, web_dir), host=host, port=port)


def _stats_out(stats: Stats) -> StatsOut:
    """Le coppie e le terne di `Stats` diventano oggetti con i campi nominati."""
    return StatsOut(
        **vars(stats)
        | {
            "top_genres": [NameCount(name=name, count=count) for name, count in stats.top_genres],
            "top_directors": [NameCount(name=name, count=count) for name, count in stats.top_directors],
            "decades": [DecadeCount(decade=decade, count=count) for decade, count in stats.decades],
            "per_month": [MonthCount(month=month, viewings=n, minutes=minutes) for month, n, minutes in stats.per_month],
            "busiest_days": [DayCount(day=day, count=count) for day, count in stats.busiest_days],
        }
    )
