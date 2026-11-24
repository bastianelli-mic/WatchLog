"""API HTTP in sola lettura per la pagina web (e un domani l'app): JSON, date in formato ISO."""

import threading
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from watchlog.config import ConfigError, load_corrections, load_users
from watchlog.dates import local_today
from watchlog.db import Database
from watchlog.edits import FilmChoice, WebEditor
from watchlog.importer import ImportReport, import_chat, render_import_report
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

MAX_IMPORT_CHARS = 20 * 1024 * 1024
_IMPORT_LOCK = threading.Lock()  # due import veri in parallelo si intralcerebbero sulle stesse righe


def _check_rating(value: float | None) -> float | None:
    if value is not None and (not 0.5 <= value <= 5 or abs(value * 2 - round(value * 2)) > 1e-9):
        raise ValueError("il voto va da 0,5 a 5 a passi di 0,5")
    return value


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
        return _check_rating(value)


class ViewingPatch(BaseModel):
    """I campi cambiati di una visione: almeno uno tra data e film."""

    watched_on: date | None = None
    film: str | None = None  # "Titolo (anno)", come nell'inserimento
    tmdb_id: int | None = Field(default=None, gt=0)  # scelto tra i candidati, se il titolo è ambiguo


class RatingIn(BaseModel):
    rating: float

    @field_validator("rating")
    @classmethod
    def _rating_is_half_steps(cls, value: float) -> float:
        return _check_rating(value)


class MessageOut(BaseModel):
    message: str


class ImportIn(BaseModel):
    chat: str


class ImportSummary(BaseModel):
    entries: int
    inserted: int
    duplicates: int
    new_movies: int
    unmapped: int
    unresolved: int
    unresolved_viewings: int
    probable_duplicates: int
    suspicious_dates: int
    anomalies: int


class ImportResponse(BaseModel):
    summary: ImportSummary
    text: str


def create_app(
    db_path: Path,
    web_dir: Path | None = None,
    client_factory: Callable[[], TmdbClient] | None = None,
    users_path: Path | None = None,
    corrections_path: Path | None = None,
) -> FastAPI:
    """L'API su `db_path`; se `web_dir` esiste, alla radice si serve anche la pagina web già compilata."""
    app = FastAPI(title="WatchLog")
    users_path = users_path or Path("config/users.yaml")
    corrections_path = corrections_path or Path("config/corrections.yaml")

    def open_db() -> Iterator[Database]:
        if not db_path.is_file():
            raise HTTPException(503, "Database non trovato")
        # FastAPI può creare, usare e chiudere la dependency in thread diversi del pool.
        db = Database.open(db_path, check_same_thread=False)
        try:
            yield db
        finally:
            db.close()

    def get_client() -> TmdbClient:
        return client_factory() if client_factory is not None else TmdbClient(http_fetch(load_api_key()))

    def require_viewing(db: Database, viewing_id: int) -> None:
        if db.get_viewing(viewing_id) is None:
            raise HTTPException(404, f"Non esiste la visione ID {viewing_id}")

    def rejection(outcome: Rejected) -> HTTPException:
        return HTTPException(409, detail={"status": "rejected", "message": outcome.text})

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

    @app.post("/api/viewings", status_code=201, response_model=MessageOut)
    def add_viewing(body: ViewingIn, db: Database = Depends(open_db)) -> MessageOut:
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
            return MessageOut(message=outcome.text)
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
            raise rejection(outcome)
        raise HTTPException(400, "Richiesta non valida")

    @app.patch("/api/viewings/{viewing_id}", response_model=MessageOut)
    def edit_viewing(viewing_id: int, body: ViewingPatch, db: Database = Depends(open_db)) -> MessageOut:
        require_viewing(db, viewing_id)
        if body.watched_on is None and body.film is None and body.tmdb_id is None:
            raise HTTPException(422, "Dimmi cosa cambiare: la data, il film o entrambi")
        client = None
        if body.film is not None or body.tmdb_id is not None:  # solo per cambiare film
            try:
                client = get_client()
            except TmdbError as error:
                raise HTTPException(502, str(error)) from error
        try:
            outcome = WebEditor(db_path, client).edit(
                viewing_id,
                watched_on=body.watched_on,
                film_text=body.film,
                tmdb_id=body.tmdb_id,
            )
        except TmdbError as error:
            raise HTTPException(502, str(error)) from error
        if isinstance(outcome, FilmChoice):
            candidates = [{"tmdb_id": tmdb_id, "label": label} for tmdb_id, label in outcome.candidates]
            raise HTTPException(
                409, detail={"status": "ambiguous", "message": outcome.text, "candidates": candidates}
            )
        if isinstance(outcome, Rejected):
            raise rejection(outcome)
        return MessageOut(message=outcome)

    @app.delete("/api/viewings/{viewing_id}", response_model=MessageOut)
    def cancel_viewing(viewing_id: int, db: Database = Depends(open_db)) -> MessageOut:
        require_viewing(db, viewing_id)
        outcome = WebEditor(db_path).cancel(viewing_id)
        if isinstance(outcome, Rejected):
            raise rejection(outcome)
        return MessageOut(message=outcome)

    @app.put("/api/viewings/{viewing_id}/rating", response_model=MessageOut)
    def rate_viewing(viewing_id: int, body: RatingIn, db: Database = Depends(open_db)) -> MessageOut:
        require_viewing(db, viewing_id)
        outcome = WebEditor(db_path).set_rating(viewing_id, body.rating)
        if isinstance(outcome, Rejected):
            raise rejection(outcome)
        return MessageOut(message=outcome)

    @app.post("/api/import", response_model=ImportResponse)
    def import_chat_endpoint(body: ImportIn, dry_run: bool = False) -> ImportResponse:
        if len(body.chat) > MAX_IMPORT_CHARS:
            raise HTTPException(413, "File troppo grande: il massimo è 20 MB.")
        if not db_path.is_file():
            raise HTTPException(503, "Database non trovato")
        try:
            users = load_users(users_path)
            corrections = load_corrections(corrections_path)
        except ConfigError as error:
            raise HTTPException(503, str(error)) from error
        try:
            client = get_client()
        except TmdbError as error:
            raise HTTPException(503, str(error)) from error

        db = Database.in_memory(copy_of=db_path) if dry_run else Database.open(db_path)
        try:
            db.sync_users(users)
            db.commit()  # gli utenti non devono tenere il lock durante le chiamate TMDB
            lock = nullcontext() if dry_run else _IMPORT_LOCK
            with lock:
                report = import_chat(body.chat, db, client, corrections)
        except TmdbError as error:
            raise HTTPException(502, str(error)) from error
        finally:
            db.close()

        return ImportResponse(summary=_import_summary(report), text=render_import_report(report, dry_run))

    if web_dir is not None and web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")  # dopo le rotte: /api ha la precedenza
    return app


def serve(
    db_path: Path,
    web_dir: Path | None,
    host: str,
    port: int,
    users_path: Path | None = None,
    corrections_path: Path | None = None,
) -> None:
    import uvicorn  # import tardivo: ai test basta create_app

    uvicorn.run(
        create_app(db_path, web_dir, users_path=users_path, corrections_path=corrections_path),
        host=host,
        port=port,
    )


def _import_summary(report: ImportReport) -> ImportSummary:
    return ImportSummary(
        entries=report.entries,
        inserted=report.inserted,
        duplicates=report.duplicates,
        new_movies=report.new_movies,
        unmapped=len(report.unmapped_authors),
        unresolved=len(report.unresolved),
        unresolved_viewings=report.unresolved_viewings,
        probable_duplicates=len(report.probable_duplicates),
        suspicious_dates=len(report.suspicious_dates),
        anomalies=len(report.anomalies),
    )


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
