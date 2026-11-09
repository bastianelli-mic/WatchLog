"""Parser dell'export di una chat WhatsApp (formati Android e iPhone, ora a 24 o a 12 ore, date gg/mm/aa o mm/gg/aa).

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
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?: ?[AP]M)?) - (.*)$"),
    # iPhone: `[06/07/26, 00:45:12] Nome: testo`, anche con ora a 12 ore (`[12/18/25, 2:52:52 PM] Nome: testo`);
    # le righe di sistema hanno un trattino dopo la parentesi: `[12/18/25, 2:52:52 PM] - testo`
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?::\d{2})?(?: ?[AP]M)?)\] (.*)$"),
)
_TIME = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?(?: ?(?P<meridiem>[AP]M))?$")
_BODY_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+-\s+(.*)$")
# Prefisso che sembra una data ma non lo è (`0000`, `2203/2026`, `05/07/26`): non va letto come titolo.
# Un numero semplice come `2001 - Odissea nello spazio` resta invece un titolo.
_MALFORMED_DATE = re.compile(r"^(?:0+|\d+(?:/\d+)+)\s+-\s+")
WRONG_DATE_REASON = "data non valida, usata la data di invio"
# Testi che WhatsApp mette al posto di un messaggio cancellato.
_DELETED = {
    "Hai eliminato questo messaggio.",
    "Questo messaggio è stato eliminato.",
    "You deleted this message",
    "This message was deleted",
}
_FILM = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*(?:\[(?P<rating>[^\]]*)\])?$")
_RATING = re.compile(r"^\d(?:[.,][05])?$")
# Caratteri invisibili da togliere; lo spazio stretto che alcuni telefoni mettono prima di AM/PM diventa uno spazio.
_CLEAN_CHARS = {**{ord(char): None for char in "\ufeff\u200e\u200f"}, ord("\u202f"): " "}


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
    line_no: int


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


def parse_line(author: str, sent_at: datetime, text: str) -> ParseResult:
    """Interpreta il testo di un solo messaggio (per esempio dal bot) come una riga d'export."""
    result = ParseResult()
    lines = text.translate(_CLEAN_CHARS).splitlines() or [""]
    _parse_message(_Message(line_no=1, sent_at=sent_at, author=author, lines=lines), result)
    return result


def parse_export(text: str) -> ParseResult:
    result = ParseResult()
    for message in _group_messages(text):
        if message.author is None:
            continue
        _parse_message(message, result)
    return result


def _group_messages(text: str) -> list[_Message]:
    lines = text.translate(_CLEAN_CHARS).splitlines()
    matches = [next((m for header in _HEADERS if (m := header.match(line))), None) for line in lines]
    month_first = _month_first([m.group(1) for m in matches if m])
    messages: list[_Message] = []
    for line_no, (line, match) in enumerate(zip(lines, matches), start=1):
        if match:
            rest = match.group(3)
            author, separator, payload = rest.partition(": ")
            is_system = rest.startswith("- ") or not separator
            messages.append(
                _Message(
                    line_no=line_no,
                    sent_at=_parse_sent_at(match.group(1), match.group(2), month_first),
                    author=None if is_system else author,
                    lines=[] if is_system else [payload],
                )
            )
        elif messages:
            messages[-1].lines.append(line)
    return messages


def _month_first(dates: list[str]) -> bool:
    """Ordine della data d'invio, dedotto da tutto il file: un primo numero sopra 12 è un giorno, un secondo sopra 12
    è un giorno e quindi il mese viene prima. Senza indizi si resta su giorno prima, come nei telefoni italiani."""
    pairs = [tuple(int(number) for number in date_text.split("/")[:2]) for date_text in dates]
    if any(first > 12 for first, _ in pairs):
        return False
    return any(second > 12 for _, second in pairs)


def _parse_sent_at(date_text: str, time_text: str, month_first: bool) -> datetime:
    first, second, year = (int(number) for number in date_text.split("/"))
    day, month = (second, first) if month_first else (first, second)
    time = _TIME.match(time_text)
    hour = int(time["hour"])
    if time["meridiem"]:
        hour = hour % 12 + (12 if time["meridiem"] == "PM" else 0)
    return datetime(year + 2000 if year < 100 else year, month, day, hour, int(time["minute"]), int(time["second"] or 0))


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
            line_no=message.line_no,
        )
    )
    if wrong_date:
        anomaly(WRONG_DATE_REASON)


def _parse_rating(raw: str) -> float | None:
    if not _RATING.match(raw):
        return None
    value = float(raw.replace(",", "."))
    return value if 0.5 <= value <= 5 else None
