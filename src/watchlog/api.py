"""API HTTP in sola lettura per la pagina web (e un domani l'app): JSON, date in formato ISO."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from watchlog.dates import local_today
from watchlog.db import Database
from watchlog.listing import ViewingRow, list_viewings
from watchlog.live import Ask, LiveService, Recorded, Rejected
from watchlog.parser import parse_film_text
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
from watchlog.tmdb import TmdbClient, TmdbError, http_fetch, load_api_key


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


class ViewingIn(BaseModel):
    user: str
    film: str  # "Titolo (anno)", come nel canale delle visioni
    watched_on: date | None = None  # senza, oggi
    rating: float | None = None
    tmdb_id: int | None = Field(default=None, gt=0)  # scelto tra i candidati, se il titolo è ambiguo
    confirm_duplicate: bool = False

    @field_validator("rating")
    @classmethod
    def _rating_is_half_steps(cls, value: float | None) -> float | None:
        if value is not None and (not 0.5 <= value <= 5 or abs(value * 2 - round(value * 2)) > 1e-9):
            raise ValueError("il voto va da 0,5 a 5 a passi di 0,5")
        return value


class ViewingCreated(BaseModel):
    message: str


def create_app(
    db_path: Path,
    web_dir: Path | None = None,
    client_factory: Callable[[], TmdbClient] | None = None,
) -> FastAPI:
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

    def get_client() -> TmdbClient:
        return client_factory() if client_factory is not None else TmdbClient(http_fetch(load_api_key()))

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

    @app.post("/api/viewings", status_code=201, response_model=ViewingCreated)
    def add_viewing(body: ViewingIn, db: Database = Depends(open_db)) -> ViewingCreated:
        parsed = parse_film_text(body.film)
        if parsed is None:
            raise HTTPException(422, "Formato non valido: usa 'Titolo (anno)'")
        user_id = db.user_id_by_name(body.user)
        if user_id is None:
            raise HTTPException(404, f"Utente {body.user!r} non trovato")
        title, year = parsed

        try:
            outcome = LiveService(db_path, get_client()).insert(
                user_id,
                title=title,
                year=year,
                rating=body.rating,
                watched_on=body.watched_on or local_today(),
                watched_on_source="body" if body.watched_on is not None else "sent_at",
                tmdb_id=body.tmdb_id,
                confirm_duplicate=body.confirm_duplicate,
            )
        except TmdbError as error:
            raise HTTPException(502, str(error)) from error

        if isinstance(outcome, Recorded):
            return ViewingCreated(message=outcome.text)
        if isinstance(outcome, Ask):
            if outcome.kind == "film":
                candidates = [
                    {"tmdb_id": int(option.value), "label": option.label}
                    for option in outcome.options
                    if option.value != "none"
                ]
                raise HTTPException(
                    409,
                    detail={"status": "ambiguous", "message": outcome.text, "candidates": candidates},
                )
            if outcome.kind == "duplicate":
                raise HTTPException(409, detail={"status": "duplicate", "message": outcome.text})
        if isinstance(outcome, Rejected):
            raise HTTPException(409, detail={"status": "rejected", "message": outcome.text})
        raise HTTPException(400, "Richiesta non valida")

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
