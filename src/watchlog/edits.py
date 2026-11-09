"""Correzioni alle visioni già registrate: annullamento (con conferma) e voto, per l'autore o un super user.

Non dipende da discord.py né da TMDB: l'adattatore mostra gli esiti e raccoglie la risposta dei bottoni.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from watchlog.db import Database
from watchlog.live import Ask, Cancelled, Option, Rejected, italian_date

_UNKNOWN_USER = "Non ti riconosco: chiedi di aggiungere il tuo discord_id a users.yaml."


@dataclass(frozen=True)
class Done:
    text: str  # per chi ha dato il comando
    announcement: str  # per il canale: i cambiamenti restano visibili al gruppo


class ViewingEditor:
    def __init__(self, db_path: Path, superusers: frozenset[str] = frozenset()):
        self._db_path = db_path
        self._superusers = superusers  # ID Discord, come testo

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
        if value == "no":
            return Cancelled("Va bene, non ho annullato nulla.")
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


def _is_valid_rating(rating: float) -> bool:
    return 0.5 <= rating <= 5 and rating * 2 == int(rating * 2)


def _number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _label(viewing: dict) -> str:
    return f"{viewing['title']} ({viewing['year']})" if viewing["year"] else viewing["title"]


def italian_date_of(viewing: dict) -> str:
    return italian_date(date.fromisoformat(viewing["watched_on"]))
