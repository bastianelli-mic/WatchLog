"""Correzioni alle visioni già registrate: annullamento e modifica (con conferma) e voto, per l'autore o un super user.

Non dipende da discord.py né da TMDB: l'adattatore mostra gli esiti e raccoglie la risposta dei bottoni.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from watchlog.db import Database
from watchlog.live import MAX_CANDIDATES, Ask, Cancelled, Option, Rejected, italian_date
from watchlog.parser import parse_film_text
from watchlog.resolver import resolve
from watchlog.tmdb import TmdbError

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TMDB_DOWN = "TMDB non risponde, riprova tra poco."
_UNKNOWN_USER = "Non ti riconosco: chiedi di aggiungere il tuo discord_id a users.yaml."


@dataclass(frozen=True)
class Done:
    text: str  # per chi ha dato il comando
    announcement: str  # per il canale: i cambiamenti restano visibili al gruppo


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
            text = f"Annullare la visione #{viewing_id}: {_label(viewing)} del {italian_date_of(viewing)}{owner}?"
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
                f"{actor['name']} ha annullato la visione #{ask.viewing_id}: "
                f"{_label(viewing)} del {italian_date_of(viewing)}{owner}."
            )
            return Done(f"Annullata la visione #{ask.viewing_id}.", announcement)

    def request_edit(
        self, discord_id: str, viewing_id: int, date_text: str | None = None, film_text: str | None = None
    ) -> Ask | Rejected:
        """Chiede conferma per cambiare la data e/o il film di una visione; il voto non cambia."""
        if date_text is None and film_text is None:
            return Rejected("Dimmi cosa cambiare: la data, il film o entrambi.")
        new_date = None
        if date_text is not None:
            new_date = _parse_date(date_text)
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
        problem = _edit_problem(db, viewing, ask)
        if problem:
            return problem
        owner = "" if viewing["user"] == self._actor_name(db, ask.actor) else f", di {viewing['user']}"
        after_day = ask.new_date or date.fromisoformat(viewing["watched_on"])
        text = (
            f"Modificare la visione #{ask.viewing_id}{owner}: {_label(viewing)} del {italian_date_of(viewing)} → "
            f"{new_label or _label(viewing)} del {italian_date(after_day)}?"
        )
        return replace(ask, kind="edit", text=text, options=(Option("Sì, modifica", "yes"), Option("No", "no")))

    def _apply_edit(self, ask: Ask) -> Done | Rejected:
        with self._open() as db:
            checked = self._check(db, ask.actor, ask.viewing_id, "modificare")  # lo stato può essere cambiato dopo la domanda
            if isinstance(checked, Rejected):
                return checked
            actor, viewing = checked
            problem = _edit_problem(db, viewing, ask)
            if problem:
                return problem
            tmdb_id = ask.new_tmdb_id or viewing["tmdb_id"]
            if not db.has_movie(tmdb_id):
                try:
                    db.save_movie(self._client.details(tmdb_id))
                except TmdbError:
                    return Rejected(_TMDB_DOWN)
            day = ask.new_date or date.fromisoformat(viewing["watched_on"])
            source = "body" if ask.new_date else viewing["watched_on_source"]
            db.update_viewing(ask.viewing_id, tmdb_id, day, source)
            db.commit()
            after = db.get_viewing(ask.viewing_id)
            owner = "" if viewing["user_id"] == actor["id"] else f" di {viewing['user']}"
            announcement = (
                f"{actor['name']} ha modificato la visione #{ask.viewing_id}{owner}: "
                f"{_label(viewing)} del {italian_date_of(viewing)} → {_label(after)} del {italian_date_of(after)}."
            )
            return Done(f"Modificata la visione #{ask.viewing_id}.", announcement)

    @staticmethod
    def _actor_name(db: Database, discord_id: str) -> str:
        return db.query("SELECT name FROM users WHERE discord_id = ?", (discord_id,))[0]["name"]

    def set_rating(self, discord_id: str, rating: float, viewing_id: int | None = None) -> Done | Rejected:
        """Imposta il voto di una visione, o dell'ultima di chi scrive se manca il numero. Senza conferma: si può riscrivere."""
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
                f"visione #{viewing_id} del {italian_date_of(viewing)}{owner}{previous}."
            )
            return Done(f"Voto {_number(rating)} registrato per la visione #{viewing_id}.", announcement)

    @contextmanager
    def _open(self) -> Iterator[Database]:
        db = Database.open(self._db_path)
        try:
            yield db
        finally:
            db.close()

    def _check(
        self, db: Database, discord_id: str, viewing_id: int, action: str = "annullare"
    ) -> tuple[dict, dict] | Rejected:
        """Chi chiede e la visione, se esistono, non è già annullata e chi chiede può agire su di essa."""
        users = db.query("SELECT id, name FROM users WHERE discord_id = ?", (discord_id,))
        if not users:
            return Rejected(_UNKNOWN_USER)
        viewing = db.get_viewing(viewing_id)
        if viewing is None:
            return Rejected(f"Non esiste la visione numero {viewing_id}.")
        if viewing["deleted_at"] is not None:
            return Rejected(f"La visione #{viewing_id} è già stata annullata.")
        if viewing["user_id"] != users[0]["id"] and discord_id not in self._superusers:
            return Rejected(f"Puoi {action} solo le tue visioni.")
        return users[0], viewing


def _parse_date(text: str) -> date | None:
    match = _DATE.match(text.strip())
    if not match:
        return None
    day, month, year = (int(number) for number in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _edit_problem(db: Database, viewing: dict, ask: Ask) -> Rejected | None:
    """Perché la modifica non ha senso: non cambia nulla, o la visione risulterebbe uguale a un'altra."""
    tmdb_id = ask.new_tmdb_id or viewing["tmdb_id"]
    day = ask.new_date or date.fromisoformat(viewing["watched_on"])
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


def italian_date_of(viewing: dict) -> str:
    return italian_date(date.fromisoformat(viewing["watched_on"]))
