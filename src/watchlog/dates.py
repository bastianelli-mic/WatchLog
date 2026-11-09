"""Le date come le leggono e le scrivono gli utenti: gg/mm/aaaa. Nel database restano in formato ISO."""

import re
from datetime import date

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def format_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def format_iso(text: str) -> str:
    """Una data ISO del database (`2026-07-05`) come la si mostra."""
    return format_date(date.fromisoformat(text))


def parse_date(text: str) -> date | None:
    """La data scritta come gg/mm/aaaa; None se non lo è o non esiste."""
    match = _DATE.match(text.strip())
    if not match:
        return None
    day, month, year = (int(number) for number in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
