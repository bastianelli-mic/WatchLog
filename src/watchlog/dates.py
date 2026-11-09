"""Le date come le leggono e le scrivono gli utenti: gg/mm/aaaa. Nel database restano in formato ISO."""

import calendar
import re
from datetime import date

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTH = re.compile(r"^(\d{1,2})/(\d{4})$")
_YEAR = re.compile(r"^(\d{4})$")


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


def parse_bound(text: str, end: bool) -> date | None:
    """Estremo di un periodo: `gg/mm/aaaa`, `mm/aaaa` (primo o ultimo giorno del mese) o `aaaa` (primo o ultimo
    dell'anno). `end` dice se è la fine del periodo; None se il testo non è una data valida."""
    text = text.strip()
    full = parse_date(text)
    if full is not None:
        return full
    try:
        if match := _MONTH.match(text):
            month, year = int(match.group(1)), int(match.group(2))
            return date(year, month, calendar.monthrange(year, month)[1] if end else 1)
        if match := _YEAR.match(text):
            year = int(match.group(1))
            return date(year, 12, 31) if end else date(year, 1, 1)
    except (ValueError, calendar.IllegalMonthError):
        return None
    return None
