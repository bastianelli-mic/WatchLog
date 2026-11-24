"""Correzioni alle visioni già registrate: annullamento, modifica e voto.

`ViewingEditor` serve al bot: controlla chi agisce e chiede conferma con i bottoni. `WebEditor` serve al
sito, che non ha login: non controlla l'autore e non chiede conferma, perché il pulsante «Salva» è la conferma.
Nessuno dei due dipende da discord.py; TMDB serve solo per cambiare il film.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from watchlog.dates import format_date, format_iso, local_today, parse_date
from watchlog.db import Database
from watchlog.live import MAX_CANDIDATES, Ask, Cancelled, Option, Rejected
from watchlog.parser import parse_film_text
from watchlog.resolver import resolve
from watchlog.tmdb import TmdbError

_TMDB_DOWN = "TMDB non risponde, riprova tra poco."
_UNKNOWN_USER = "Non ti riconosco: chiedi di aggiungere il tuo discord_id a users.yaml."


@dataclass(frozen=True)
class Done:
    text: str  # per chi ha dato il comando
    announcement: str  # per il canale: i cambiamenti restano visibili al gruppo


@dataclass(frozen=True)
class FilmChoice:
    """Il film scritto dal sito è ambiguo: i candidati tra cui scegliere, con l'id di TMDB e l'etichetta."""

    text: str
    candidates: tuple[tuple[int, str], ...]


@contextmanager
def _open_db(path: Path) -> Iterator[Database]:
    db = Database.open(path)
    try:
        yield db
    finally:
        db.close()


class ViewingEditor:
    def __init__(
        self,
        db_path: Path,
        superusers: frozenset[str] = frozenset(),
        client=None,  # TMDB: serve solo per cambiare il film
        today: Callable[[], date] = date.today,
    ):
        self._db_path = db_path
        self._superusers = superusers  # ID Discord, come testo
        self._client = client
        self._today = today

    def request_cancel(self, discord_id: str, viewing_id: int) -> Ask | Rejected:
        with self._open() as db:
            checked = self._check(db, discord_id, viewing_id)
            if isinstance(checked, Rejected):
                return checked
            actor, viewing = checked
            owner = "" if viewing["user_id"] == actor["id"] else f", di {viewing['user']}"
            text = f"Annullare la visione ID {viewing_id}: {_label(viewing)} del {format_iso(viewing["watched_on"])}{owner}?"
            options = (Option("Sì, annulla", "yes"), Option("No", "no"))
            return Ask("cancel", text, options, viewing_id=viewing_id, actor=discord_id)

    def answer(self, ask: Ask, value: str) -> Done | Cancelled | Rejected:
        if value not in {option.value for option in ask.options}:
            return Rejected("Scelta non valida.")
        if value in ("no", "none"):
            return Cancelled(f"Va bene, non ho {'annullato' if ask.kind == 'cancel' else 'modificato'} nulla.")
        if ask.kind == "edit_film":
            return self._after_film_choice(ask, value)
        if ask.kind == "edit":
            return self._apply_edit(ask)
        with self._open() as db:
            checked = self._check(db, ask.actor, ask.viewing_id)  # lo stato può essere cambiato dopo la domanda
            if isinstance(checked, Rejected):
                return checked
            actor, viewing = checked
            db.cancel_viewing(ask.viewing_id)
            db.commit()
            owner = "" if viewing["user_id"] == actor["id"] else f" di {viewing['user']}"
            announcement = (
                f"{actor['name']} ha annullato la visione ID {ask.viewing_id}: "
                f"{_label(viewing)} del {format_iso(viewing["watched_on"])}{owner}."
            )
            return Done(f"Annullata la visione ID {ask.viewing_id}.", announcement)

    def request_edit(
        self, discord_id: str, viewing_id: int, date_text: str | None = None, film_text: str | None = None
    ) -> Ask | Rejected:
        """Chiede conferma per cambiare la data e/o il film di una visione; il voto non cambia."""
        if date_text is None and film_text is None:
            return Rejected("Dimmi cosa cambiare: la data, il film o entrambi.")
        new_date = None
        if date_text is not None:
            new_date = parse_date(date_text)
            if new_date is None:
                return Rejected("Data non valida: scrivila come gg/mm/aaaa, per esempio 05/07/2026.")
            if new_date > self._today():
                return Rejected("La data non può essere nel futuro.")
        film = None
        if film_text is not None:
            film = parse_film_text(film_text)
            if film is None:
                return Rejected("Scrivi il film come Titolo (anno), per esempio Heat (1995).")
            if self._client is None:
                return Rejected("Per cambiare il film serve la chiave TMDB: il bot non l'ha trovata.")
        with self._open() as db:
            checked = self._check(db, discord_id, viewing_id, "modificare")
            if isinstance(checked, Rejected):
                return checked
            _, viewing = checked
            base = Ask("edit", "", (), viewing_id=viewing_id, actor=discord_id, new_date=new_date)
            if film is None:
                return self._confirm_edit(db, viewing, base)
            title, year = film
            try:
                resolution = resolve(title, year, self._client.search(title))
            except TmdbError:
                return Rejected(_TMDB_DOWN)
            label = f"{title} ({year})"
            if resolution.status == "resolved":
                candidate = resolution.best.candidate
                found = replace(base, new_tmdb_id=candidate.tmdb_id)
                return self._confirm_edit(db, viewing, found, f"{candidate.display_title} ({candidate.year})")
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
            return replace(base, kind="edit_film", text=text, options=(*options, Option("Nessuno di questi", "none")))

    def _after_film_choice(self, ask: Ask, value: str) -> Ask | Rejected:
        label = next(option.label for option in ask.options if option.value == value)
        with self._open() as db:
            checked = self._check(db, ask.actor, ask.viewing_id, "modificare")
            if isinstance(checked, Rejected):
                return checked
            return self._confirm_edit(db, checked[1], replace(ask, new_tmdb_id=int(value)), label)

    def _confirm_edit(self, db: Database, viewing: dict, ask: Ask, new_label: str | None = None) -> Ask | Rejected:
        after_day = ask.new_date or date.fromisoformat(viewing["watched_on"])
        problem = _edit_problem(db, viewing, ask.new_tmdb_id or viewing["tmdb_id"], after_day)
        if problem:
            return problem
        owner = "" if viewing["user"] == self._actor_name(db, ask.actor) else f", di {viewing['user']}"
        text = (
            f"Modificare la visione ID {ask.viewing_id}{owner}: {_label(viewing)} del {format_iso(viewing["watched_on"])} → "
            f"{new_label or _label(viewing)} del {format_date(after_day)}?"
        )
        return replace(ask, kind="edit", text=text, options=(Option("Sì, modifica", "yes"), Option("No", "no")))

    def _apply_edit(self, ask: Ask) -> Done | Rejected:
        with self._open() as db:
            checked = self._check(db, ask.actor, ask.viewing_id, "modificare")  # lo stato può essere cambiato dopo la domanda
            if isinstance(checked, Rejected):
                return checked
            actor, viewing = checked
            tmdb_id = ask.new_tmdb_id or viewing["tmdb_id"]
            day = ask.new_date or date.fromisoformat(viewing["watched_on"])
            problem = _edit_problem(db, viewing, tmdb_id, day)
            if problem:
                return problem
            if not db.has_movie(tmdb_id):
                try:
                    db.save_movie(self._client.details(tmdb_id))
                except TmdbError:
                    return Rejected(_TMDB_DOWN)
            source = "body" if ask.new_date else viewing["watched_on_source"]
            db.update_viewing(ask.viewing_id, tmdb_id, day, source)
            db.commit()
            after = db.get_viewing(ask.viewing_id)
            owner = "" if viewing["user_id"] == actor["id"] else f" di {viewing['user']}"
            announcement = (
                f"{actor['name']} ha modificato la visione ID {ask.viewing_id}{owner}: "
                f"{_label(viewing)} del {format_iso(viewing["watched_on"])} → {_label(after)} del {format_iso(after["watched_on"])}."
            )
            return Done(f"Modificata la visione ID {ask.viewing_id}.", announcement)

    @staticmethod
    def _actor_name(db: Database, discord_id: str) -> str:
        return db.query("SELECT name FROM users WHERE discord_id = ?", (discord_id,))[0]["name"]

    def set_rating(self, discord_id: str, rating: float, viewing_id: int | None = None) -> Done | Rejected:
        """Imposta il voto di una visione, o dell'ultima di chi scrive se manca l'ID. Senza conferma: si può riscrivere."""
        if not _is_valid_rating(rating):
            return Rejected("Il voto va da 0,5 a 5, a passi di 0,5.")
        with self._open() as db:
            if viewing_id is None:
                users = db.query("SELECT id FROM users WHERE discord_id = ?", (discord_id,))
                if not users:
                    return Rejected(_UNKNOWN_USER)
                viewing_id = db.last_viewing_id(users[0]["id"])
                if viewing_id is None:
                    return Rejected("Non hai nessuna visione a cui dare un voto.")
            checked = self._check(db, discord_id, viewing_id, "votare")
            if isinstance(checked, Rejected):
                return checked
            actor, viewing = checked
            db.set_rating(viewing_id, rating)
            db.commit()
            owner = "" if viewing["user_id"] == actor["id"] else f" di {viewing['user']}"
            previous = f" (da {_number(viewing['rating'])} a {_number(rating)})" if viewing["rating"] is not None else ""
            announcement = (
                f"{actor['name']} ha dato {_number(rating)} a {_label(viewing)}, "
                f"visione ID {viewing_id} del {format_iso(viewing["watched_on"])}{owner}{previous}."
            )
            return Done(f"Voto {_number(rating)} registrato per la visione ID {viewing_id}.", announcement)

    @contextmanager
    def _open(self) -> Iterator[Database]:
        with _open_db(self._db_path) as db:
            yield db

    def _check(
        self, db: Database, discord_id: str, viewing_id: int, action: str = "annullare"
    ) -> tuple[dict, dict] | Rejected:
        """Chi chiede e la visione, se esistono, non è già annullata e chi chiede può agire su di essa."""
        users = db.query("SELECT id, name FROM users WHERE discord_id = ?", (discord_id,))
        if not users:
            return Rejected(_UNKNOWN_USER)
        viewing = _existing(db, viewing_id)
        if isinstance(viewing, Rejected):
            return viewing
        if viewing["user_id"] != users[0]["id"] and discord_id not in self._superusers:
            return Rejected(f"Puoi {action} solo le tue visioni.")
        return users[0], viewing


class WebEditor:
    """Le stesse correzioni dal sito, senza controllo dell'autore e senza domande: la conferma è il pulsante.

    I metodi restituiscono il testo da mostrare, oppure `Rejected` con il motivo. `edit` può anche
    restituire `FilmChoice`, quando TMDB non sa scegliere il film: il sito mostra i candidati e ripete la
    richiesta con il `tmdb_id` scelto.
    """

    def __init__(
        self,
        db_path: Path,
        client=None,  # TMDB: serve solo per cambiare il film
        today: Callable[[], date] = local_today,
    ):
        self._db_path = db_path
        self._client = client
        self._today = today

    def cancel(self, viewing_id: int) -> str | Rejected:
        with _open_db(self._db_path) as db:
            viewing = _existing(db, viewing_id)
            if isinstance(viewing, Rejected):
                return viewing
            db.cancel_viewing(viewing_id)
            db.commit()
            return f"Annullata la visione ID {viewing_id}: {_label(viewing)} del {_watched_on(viewing)}."

    def set_rating(self, viewing_id: int, rating: float) -> str | Rejected:
        if not _is_valid_rating(rating):
            return Rejected("Il voto va da 0,5 a 5, a passi di 0,5.")
        with _open_db(self._db_path) as db:
            viewing = _existing(db, viewing_id)
            if isinstance(viewing, Rejected):
                return viewing
            db.set_rating(viewing_id, rating)
            db.commit()
            return f"Voto {_number(rating)} registrato per la visione ID {viewing_id}."

    def edit(
        self,
        viewing_id: int,
        *,
        watched_on: date | None = None,
        film_text: str | None = None,
        tmdb_id: int | None = None,
    ) -> str | Rejected | FilmChoice:
        """Cambia la data e/o il film. Con `tmdb_id` non si interroga TMDB per scegliere il film."""
        if watched_on is None and film_text is None and tmdb_id is None:
            return Rejected("Dimmi cosa cambiare: la data, il film o entrambi.")
        if watched_on is not None and watched_on > self._today():
            return Rejected("La data non può essere nel futuro.")

        new_tmdb_id = tmdb_id
        if film_text is not None and tmdb_id is None:
            film = parse_film_text(film_text)
            if film is None:
                return Rejected("Scrivi il film come Titolo (anno), per esempio Heat (1995).")
            if self._client is None:
                return Rejected("Per cambiare il film serve la chiave TMDB.")
            title, year = film
            resolution = resolve(title, year, self._client.search(title))
            label = f"{title} ({year})"
            if resolution.status == "resolved":
                new_tmdb_id = resolution.best.candidate.tmdb_id
            elif resolution.status == "not_found":
                return Rejected(f"Non ho trovato «{label}» su TMDB: controlla il titolo e riscrivilo.")
            else:
                candidates = tuple(
                    (scored.candidate.tmdb_id, f"{scored.candidate.display_title} ({scored.candidate.year})")
                    for scored in resolution.scored[:MAX_CANDIDATES]
                )
                text = (
                    f"Intendevi questo film per «{label}»?"
                    if len(candidates) == 1
                    else f"Non sono sicuro del film «{label}»: quale intendevi?"
                )
                return FilmChoice(text, candidates)

        with _open_db(self._db_path) as db:
            viewing = _existing(db, viewing_id)
            if isinstance(viewing, Rejected):
                return viewing
            final_tmdb_id = new_tmdb_id or viewing["tmdb_id"]
            day = watched_on or date.fromisoformat(viewing["watched_on"])
            problem = _edit_problem(db, viewing, final_tmdb_id, day)
            if problem:
                return problem
            if not db.has_movie(final_tmdb_id):
                if self._client is None:
                    return Rejected("Per cambiare il film serve la chiave TMDB.")
                db.save_movie(self._client.details(final_tmdb_id))
            source = "body" if watched_on else viewing["watched_on_source"]
            db.update_viewing(viewing_id, final_tmdb_id, day, source)
            db.commit()
            after = db.get_viewing(viewing_id)
            return f"Modificata la visione ID {viewing_id}: {_label(after)} del {format_date(day)}."


def _existing(db: Database, viewing_id: int) -> dict | Rejected:
    """La visione, se esiste e non è già annullata."""
    viewing = db.get_viewing(viewing_id)
    if viewing is None:
        return Rejected(f"Non esiste la visione ID {viewing_id}.")
    if viewing["deleted_at"] is not None:
        return Rejected(f"La visione ID {viewing_id} è già stata annullata.")
    return viewing


def _watched_on(viewing: dict) -> str:
    return format_date(date.fromisoformat(viewing["watched_on"]))


def _edit_problem(db: Database, viewing: dict, tmdb_id: int, day: date) -> Rejected | None:
    """Perché la modifica non ha senso: non cambia nulla, o la visione risulterebbe uguale a un'altra."""
    if tmdb_id == viewing["tmdb_id"] and day.isoformat() == viewing["watched_on"]:
        return Rejected("Con questi valori la visione non cambia.")
    if db.has_viewing_same_day(viewing["user_id"], tmdb_id, day, exclude_id=viewing["id"]):
        return Rejected(f"C'è già una visione di {viewing['user']} dello stesso film in quel giorno.")
    return None


def _is_valid_rating(rating: float) -> bool:
    return 0.5 <= rating <= 5 and rating * 2 == int(rating * 2)


def _number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _label(viewing: dict) -> str:
    return f"{viewing['title']} ({viewing['year']})" if viewing["year"] else viewing["title"]

