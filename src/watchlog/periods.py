"""Intervalli di date per i filtri rapidi: oggi, settimana, mese, anno."""

from calendar import monthrange
from datetime import date, timedelta

PERIOD_NAMES = ("oggi", "settimana", "mese", "anno")


def period_range(name: str, today: date) -> tuple[date, date]:
    """Primo e ultimo giorno del periodo che contiene `today`. La settimana va da lunedì a domenica."""
    if name == "oggi":
        return today, today
    if name == "settimana":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=6)
    if name == "mese":
        return today.replace(day=1), today.replace(day=monthrange(today.year, today.month)[1])
    if name == "anno":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    raise ValueError(f"Periodo sconosciuto: {name!r}")
