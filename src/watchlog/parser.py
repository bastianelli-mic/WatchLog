"""Parser dell'export di una chat WhatsApp (formati Android e iPhone, date gg/mm/aa).

Ogni messaggio utente ha la forma `data - titolo (anno)` con voto opzionale
`[3.5]`. La data nel corpo è la data di visione; se manca si ripiega sulla
data di invio del messaggio.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

EDITED_MARKERS = ("<Questo messaggio è stato modificato>", "<This message was edited>")

_HEADERS = (
    # Android: `06/07/26, 00:45 - Nome: testo`
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}) - (.*)$"),
    # iPhone: `[06/07/26, 00:45:12] Nome: testo`
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?::\d{2})?)\] (.*)$"),
)
_BODY_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+-\s+(.*)$")
# Prefisso che sembra una data ma non lo è (`0000`, `2203/2026`, `05/07/26`): non va letto come titolo.
# Un numero semplice come `2001 - Odissea nello spazio` resta invece un titolo.
_MALFORMED_DATE = re.compile(r"^(?:0+|\d+(?:/\d+)+)\s+-\s+")
# Testi che WhatsApp mette al posto di un messaggio cancellato.
_DELETED = {
    "Hai eliminato questo messaggio.",
    "Questo messaggio è stato eliminato.",
    "You deleted this message",
    "This message was deleted",
}
_FILM = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*(?:\[(?P<rating>[^\]]*)\])?$")
_RATING = re.compile(r"^\d(?:[.,][05])?$")
_STRIP_INVISIBLE = {ord(char): None for char in "﻿‎‏"}


@dataclass(frozen=True)
class Entry:
    author: str
    sent_at: datetime
    watched_on: date
    watched_on_source: str  # "body" oppure "sent_at"
    title: str
    year: int
    rating: float | None
    edited: bool


@dataclass(frozen=True)
class Anomaly:
    line_no: int
    author: str
    raw: str
    reason: str


@dataclass
class ParseResult:
    entries: list[Entry] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)


@dataclass
class _Message:
    line_no: int
    sent_at: datetime
    author: str | None
    lines: list[str]


def parse_film_text(text: str) -> tuple[str, int] | None:
    """Estrae (titolo, anno) da un testo libero come `Roofman (2025)`."""
    match = _FILM.match(" ".join(text.split()))
    return (match.group("title"), int(match.group("year"))) if match else None


def parse_export(text: str) -> ParseResult:
    result = ParseResult()
    for message in _group_messages(text):
        if message.author is None:
            continue
        _parse_message(message, result)
    return result


def _group_messages(text: str) -> list[_Message]:
    messages: list[_Message] = []
    for line_no, line in enumerate(text.translate(_STRIP_INVISIBLE).splitlines(), start=1):
        match = next((m for header in _HEADERS if (m := header.match(line))), None)
        if match:
            author, separator, payload = match.group(3).partition(": ")
            messages.append(
                _Message(
                    line_no=line_no,
                    sent_at=_parse_sent_at(match.group(1), match.group(2)),
                    author=author if separator else None,
                    lines=[payload] if separator else [],
                )
            )
        elif messages:
            messages[-1].lines.append(line)
    return messages


def _parse_sent_at(day: str, time: str) -> datetime:
    year_format = "%Y" if len(day.rsplit("/", 1)[1]) == 4 else "%y"
    time_format = "%H:%M:%S" if time.count(":") == 2 else "%H:%M"
    return datetime.strptime(f"{day}, {time}", f"%d/%m/{year_format}, {time_format}")


def _parse_message(message: _Message, result: ParseResult) -> None:
    payload = " ".join(" ".join(message.lines).split())
    edited = any(marker in payload for marker in EDITED_MARKERS)
    for marker in EDITED_MARKERS:
        payload = payload.replace(marker, "")
    payload = payload.strip()
    if payload in _DELETED:
        return

    def anomaly(reason: str) -> None:
        result.anomalies.append(Anomaly(message.line_no, message.author, payload, reason))

    # Data assente o errata nel corpo: si ripiega sulla data di invio, segnalando l'errata.
    watched_on, source, rest, wrong_date = message.sent_at.date(), "sent_at", payload, False
    date_match = _BODY_DATE.match(payload)
    malformed_date = _MALFORMED_DATE.match(payload)
    if date_match:
        day, month, year, rest = date_match.groups()
        try:
            watched_on, source = date(int(year), int(month), int(day)), "body"
        except ValueError:
            wrong_date = True
    elif malformed_date:
        rest, wrong_date = payload[malformed_date.end():], True

    film = _FILM.match(rest)
    if not film:
        anomaly("non è una visualizzazione")
        return

    rating = None
    if film.group("rating") is not None:
        rating = _parse_rating(film.group("rating"))
        if rating is None:
            anomaly("voto non valido")
            return

    result.entries.append(
        Entry(
            author=message.author,
            sent_at=message.sent_at,
            watched_on=watched_on,
            watched_on_source=source,
            title=film.group("title"),
            year=int(film.group("year")),
            rating=rating,
            edited=edited,
        )
    )
    if wrong_date:
        anomaly("data non valida, usata la data di invio")


def _parse_rating(raw: str) -> float | None:
    if not _RATING.match(raw):
        return None
    value = float(raw.replace(",", "."))
    return value if 0.5 <= value <= 5 else None
