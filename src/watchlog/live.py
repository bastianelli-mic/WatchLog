"""Inserimento delle visioni dal bot: dal testo di un messaggio alla visione salvata, con le conferme necessarie.

Non dipende da discord.py: l'adattatore mostra gli esiti e raccoglie le risposte dei bottoni.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from watchlog.db import Database
from watchlog.parser import WRONG_DATE_REASON, parse_line
from watchlog.resolver import resolve
from watchlog.tmdb import TmdbError

MAX_CANDIDATES = 5
_ALREADY_RECORDED = "Questa visione era già registrata."
_TMDB_DOWN = "TMDB non risponde, riprova tra poco."


@dataclass(frozen=True)
class Draft:
    """Una visione in attesa di essere salvata: manca il film, o la conferma del doppione."""

    user_id: int
    title: str
    year: int
    rating: float | None
    watched_on: date
    watched_on_source: str
    wrong_date: bool
    sent_at: datetime
    source_ref: str
    tmdb_id: int | None = None


@dataclass(frozen=True)
class Option:
    label: str
    value: str


@dataclass(frozen=True)
class Ask:
    # "film": scegliere il film; "duplicate": confermare un doppione; "cancel": confermare un annullamento;
    # "edit_film": scegliere il film di una modifica; "edit": confermare una modifica
    kind: str
    text: str
    options: tuple[Option, ...]
    draft: Draft | None = None  # inserimento
    viewing_id: int | None = None  # annullamento
    actor: str | None = None  # ID Discord di chi ha chiesto l'annullamento o la modifica
    new_date: date | None = None  # modifica: la nuova data, se cambia
    new_tmdb_id: int | None = None  # modifica: il nuovo film, se cambia


@dataclass(frozen=True)
class Recorded:
    text: str


@dataclass(frozen=True)
class Rejected:
    text: str


@dataclass(frozen=True)
class Cancelled:
    text: str


@dataclass(frozen=True)
class Unrecognized:
    """Il messaggio non ha il formato di una visione: nessuna risposta, solo un segnale."""


Outcome = Ask | Recorded | Rejected | Cancelled | Unrecognized


class LiveService:
    def __init__(self, db_path: Path, client):
        self._db_path = db_path
        self._client = client

    def handle(self, discord_id: str, text: str, sent_at: datetime, message_id: str) -> Outcome:
        with self._open() as db:
            user_id = db.user_id_by_discord(discord_id)
            if user_id is None:
                return Rejected("Non ti riconosco: chiedi di aggiungere il tuo discord_id a users.yaml.")
            source_ref = f"discord:{message_id}"
            if db.has_viewing(source_ref):
                return Rejected(_ALREADY_RECORDED)

            parsed = parse_line("discord", sent_at, text)
            if not parsed.entries:
                if any(a.reason == "voto non valido" for a in parsed.anomalies):
                    return Rejected("Voto non valido: usa un valore da 0,5 a 5 a passi di 0,5, per esempio [3.5].")
                return Unrecognized()
            entry = parsed.entries[0]
            draft = Draft(
                user_id=user_id,
                title=entry.title,
                year=entry.year,
                rating=entry.rating,
                watched_on=entry.watched_on,
                watched_on_source=entry.watched_on_source,
                wrong_date=any(a.reason == WRONG_DATE_REASON for a in parsed.anomalies),
                sent_at=sent_at,
                source_ref=source_ref,
            )
            try:
                return self._resolve_film(db, draft)
            except TmdbError:
                return Rejected(_TMDB_DOWN)

    def answer(self, ask: Ask, value: str) -> Outcome:
        if value not in {option.value for option in ask.options}:
            return Rejected("Scelta non valida.")
        if value in ("none", "no"):
            return Cancelled("Va bene, non ho registrato nulla.")
        with self._open() as db:
            if db.has_viewing(ask.draft.source_ref):
                return Rejected(_ALREADY_RECORDED)
            try:
                if ask.kind == "film":
                    return self._after_film_is_known(db, replace(ask.draft, tmdb_id=int(value)))
                return self._record(db, ask.draft)
            except TmdbError:
                return Rejected(_TMDB_DOWN)

    @contextmanager
    def _open(self) -> Iterator[Database]:
        db = Database.open(self._db_path)
        try:
            yield db
        finally:
            db.close()

    def _resolve_film(self, db: Database, draft: Draft) -> Outcome:
        label = f"{draft.title} ({draft.year})"
        resolution = resolve(draft.title, draft.year, self._client.search(draft.title))
        if resolution.status == "resolved":
            return self._after_film_is_known(db, replace(draft, tmdb_id=resolution.best.candidate.tmdb_id))
        if resolution.status == "not_found":
            return Rejected(f"Non ho trovato «{label}» su TMDB: controlla il titolo e riscrivilo.")
        options = tuple(
            Option(f"{s.candidate.display_title} ({s.candidate.year})", str(s.candidate.tmdb_id))
            for s in resolution.scored[:MAX_CANDIDATES]
        )
        text = (
            f"Intendevi questo film per «{label}»?"
            if len(options) == 1
            else f"Non sono sicuro del film «{label}»: quale intendevi?"
        )
        return Ask("film", text, (*options, Option("Nessuno di questi", "none")), draft)

    def _after_film_is_known(self, db: Database, draft: Draft) -> Outcome:
        if db.has_viewing_same_day(draft.user_id, draft.tmdb_id, draft.watched_on):
            text = f"Hai già registrato «{draft.title} ({draft.year})» per il {italian_date(draft.watched_on)}. Lo registro di nuovo?"
            return Ask("duplicate", text, (Option("Registra di nuovo", "yes"), Option("Annulla", "no")), draft)
        return self._record(db, draft)

    def _record(self, db: Database, draft: Draft) -> Outcome:
        if not db.has_movie(draft.tmdb_id):
            db.save_movie(self._client.details(draft.tmdb_id))
        added = db.add_viewing(
            user_id=draft.user_id,
            tmdb_id=draft.tmdb_id,
            watched_on=draft.watched_on,
            watched_on_source=draft.watched_on_source,
            rating=draft.rating,
            sent_at=draft.sent_at,
            source_ref=draft.source_ref,
        )
        db.commit()
        if not added:
            return Rejected(_ALREADY_RECORDED)

        movie = db.query("SELECT title, year FROM movie WHERE tmdb_id = ?", (draft.tmdb_id,))[0]
        text = f"Registrato: {movie['title']} ({movie['year']}), visto il {italian_date(draft.watched_on)}"
        if draft.rating is not None:
            text += f", voto {draft.rating:g}".replace(".", ",")
        if draft.watched_on_source == "sent_at":
            reason = "la data nel messaggio non era valida" if draft.wrong_date else "nessuna data nel messaggio"
            text += f" ({reason}: ho usato la data di invio)"
        return Recorded(text)


def italian_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")
