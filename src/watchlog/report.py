"""Testo delle statistiche, in blocchi: la CLI li stampa uno sotto l'altro, il bot li impacchetta in messaggi."""

from collections.abc import Collection
from datetime import date

from watchlog.dates import format_date, format_iso
from watchlog.stats import GroupExtras, Record, Stats

# Gruppi di statistiche che si possono chiedere oltre al riepilogo (`base`, sempre in testa); `tutto` le mostra tutte.
DETAILS = ("base", "durata", "gusti", "tempo", "rivisti", "classifiche", "tutto")

_WEEKDAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def period_text(since: date | None, until: date | None) -> str:
    if since and until:
        return f" (dal {format_date(since)} al {format_date(until)})"
    if since:
        return f" (dal {format_date(since)})"
    if until:
        return f" (fino al {format_date(until)})"
    return ""


def render_stats(
    stats: Stats,
    extras: GroupExtras | None = None,
    user: str | None = None,
    since: date | None = None,
    until: date | None = None,
    details: Collection[str] | None = None,
) -> list[str]:
    """Il primo blocco è il titolo con i totali, ogni sezione successiva è un blocco a sé.

    `details` sceglie i gruppi di statistiche (vedi `DETAILS`); senza, o con `tutto`, il report è completo.
    """
    unknown = [name for name in details or () if name not in DETAILS]
    if unknown:
        raise ValueError(f"Dettaglio sconosciuto: {unknown[0]}")
    everything = not details or "tutto" in details
    header = f"Statistiche: {user or 'gruppo'}{period_text(since, until)}"
    blocks = ["\n".join([header, *_summary(stats, with_duration=everything)])]

    sections = [("durata", "Durata:", _duration_lines(stats))] if not everything and "durata" in details else []
    sections += _sections(stats) + (_extras_sections(extras) if extras else [])
    blocks += [
        f"{title}\n" + "\n".join(f"  {row}" for row in rows)
        for detail, title, rows in sections
        if rows and (everything or detail in details or detail == "durata")
    ]
    return blocks


def _duration(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60} min"


def _duration_lines(stats: Stats) -> list[str]:
    if stats.average_runtime_minutes is None:
        return []
    return [
        f"durata media: {_duration(stats.average_runtime_minutes)}",
        f"film più lungo: {stats.longest_film.title} ({_duration(stats.longest_film.minutes)})",
        f"film più corto: {stats.shortest_film.title} ({_duration(stats.shortest_film.minutes)})",
    ]


def _summary(stats: Stats, with_duration: bool = True) -> list[str]:
    lines = [f"visualizzazioni: {stats.viewings}  (film distinti: {stats.distinct_films}, rivisioni: {stats.rewatches})"]
    missing = f" ({stats.viewings_without_runtime} visualizzazioni senza durata non incluse)"
    lines.append(f"tempo totale: {_duration(stats.runtime_minutes)}{missing if stats.viewings_without_runtime else ''}")
    if with_duration:
        lines += _duration_lines(stats)
    if stats.longest_streak is not None:
        streak = stats.longest_streak
        span = f"dal {format_iso(streak.start)} al {format_iso(streak.end)}" if streak.days > 1 else format_iso(streak.start)
        lines.append(f"serie consecutiva più lunga: {streak.days} {'giorni' if streak.days != 1 else 'giorno'} ({span})")
    if stats.average_rating is None:
        lines.append("voto medio: nessuna visualizzazione votata")
    else:
        average = f"{stats.average_rating:.1f}".replace(".", ",")
        lines.append(f"voto medio: {average} ({stats.rated_viewings} visualizzazioni votate)")
    return lines


def _sections(stats: Stats) -> list[tuple[str, str, list[str]]]:
    """(gruppo di statistiche, titolo, righe)."""
    return [
        ("gusti", "Generi più visti:", [f"{name}: {count}" for name, count in stats.top_genres]),
        ("gusti", "Registi più visti:", [f"{name}: {count}" for name, count in stats.top_directors]),
        ("gusti", "Per decennio di uscita:", [f"{decade}-{decade + 9}: {count}" for decade, count in stats.decades]),
        (
            "tempo",
            "Visualizzazioni per mese:",
            [f"{month}: {count} visualizzazioni, {_duration(minutes)}" for month, count, minutes in stats.per_month],
        ),
        (
            "tempo",
            "Giorni della settimana:",
            [f"{name}: {count}" for name, count in zip(_WEEKDAYS, stats.weekdays)] if any(stats.weekdays) else [],
        ),
        ("tempo", "Giorni con più film:", [f"{format_iso(day)}: {count} film" for day, count in stats.busiest_days]),
        ("tempo", "Record di film visti:", _record_rows(stats.records)),
        ("rivisti", "Film rivisti più volte:", [f"{r.user}: {r.title} ×{r.times}" for r in stats.most_rewatched]),
    ]


_RECORD_NAMES = {"giorno": "in un giorno", "settimana": "in una settimana", "mese": "in un mese", "anno": "in un anno"}


def _record_rows(records: list[Record]) -> list[str]:
    rows = []
    for record in records:
        start, end = date.fromisoformat(record.start), date.fromisoformat(record.end)
        if record.period == "giorno":
            when = format_date(start)
        elif record.period == "settimana":
            when = f"dal {format_date(start)} al {format_date(end)}"
        elif record.period == "mese":
            when = f"{start.month:02d}/{start.year}"
        else:
            when = str(start.year)
        rows.append(f"{_RECORD_NAMES[record.period]}: {record.count} film ({when})")
    return rows


def _extras_sections(extras: GroupExtras) -> list[tuple[str, str, list[str]]]:
    shown = extras.seen_by_all[:10]
    hidden = len(extras.seen_by_all) - len(shown)
    return [
        (
            "classifiche",
            "Classifica utenti:",
            [f"{u.name}: {u.viewings} visualizzazioni, {_duration(u.runtime_minutes)}" for u in extras.users],
        ),
        (
            "classifiche",
            "Film più visti dal gruppo:",
            [f"{f.title}: {f.views} visualizzazioni ({f.viewers} utenti)" for f in extras.most_watched],
        ),
        (
            "classifiche",
            f"Film visti da tutti gli utenti ({len(extras.seen_by_all)}):",
            shown + ([f"… e altri {hidden}"] if hidden else []),
        ),
    ]
