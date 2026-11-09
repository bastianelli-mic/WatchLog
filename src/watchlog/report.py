"""Testo delle statistiche, in blocchi: la CLI li stampa uno sotto l'altro, il bot li impacchetta in messaggi."""

from datetime import date

from watchlog.dates import format_date, format_iso
from watchlog.stats import GroupExtras, Stats

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
) -> list[str]:
    """Il primo blocco è il titolo con i totali, ogni sezione successiva è un blocco a sé."""
    blocks = ["\n".join([f"Statistiche: {user or 'gruppo'}{period_text(since, until)}", *_summary(stats)])]
    sections = _sections(stats) + (_extras_sections(extras) if extras else [])
    blocks += [f"{title}\n" + "\n".join(f"  {row}" for row in rows) for title, rows in sections if rows]
    return blocks


def _duration(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60} min"


def _summary(stats: Stats) -> list[str]:
    lines = [f"visualizzazioni: {stats.viewings}  (film distinti: {stats.distinct_films}, rivisioni: {stats.rewatches})"]
    missing = f" ({stats.viewings_without_runtime} visualizzazioni senza durata non incluse)"
    lines.append(f"tempo totale: {_duration(stats.runtime_minutes)}{missing if stats.viewings_without_runtime else ''}")
    if stats.average_runtime_minutes is not None:
        lines.append(f"durata media: {_duration(stats.average_runtime_minutes)}")
        lines.append(f"film più lungo: {stats.longest_film.title} ({_duration(stats.longest_film.minutes)})")
        lines.append(f"film più corto: {stats.shortest_film.title} ({_duration(stats.shortest_film.minutes)})")
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


def _sections(stats: Stats) -> list[tuple[str, list[str]]]:
    return [
        ("Generi più visti:", [f"{name}: {count}" for name, count in stats.top_genres]),
        ("Registi più visti:", [f"{name}: {count}" for name, count in stats.top_directors]),
        ("Per decennio di uscita:", [f"{decade}-{decade + 9}: {count}" for decade, count in stats.decades]),
        (
            "Visualizzazioni per mese:",
            [f"{month}: {count} visualizzazioni, {_duration(minutes)}" for month, count, minutes in stats.per_month],
        ),
        (
            "Giorni della settimana:",
            [f"{name}: {count}" for name, count in zip(_WEEKDAYS, stats.weekdays)] if any(stats.weekdays) else [],
        ),
        ("Giorni con più film:", [f"{format_iso(day)}: {count} film" for day, count in stats.busiest_days]),
        ("Film rivisti più volte:", [f"{r.user}: {r.title} ×{r.times}" for r in stats.most_rewatched]),
    ]


def _extras_sections(extras: GroupExtras) -> list[tuple[str, list[str]]]:
    shown = extras.seen_by_all[:10]
    hidden = len(extras.seen_by_all) - len(shown)
    return [
        (
            "Classifica utenti:",
            [f"{u.name}: {u.viewings} visualizzazioni, {_duration(u.runtime_minutes)}" for u in extras.users],
        ),
        (
            "Film più visti dal gruppo:",
            [f"{f.title}: {f.views} visualizzazioni ({f.viewers} utenti)" for f in extras.most_watched],
        ),
        (
            f"Film visti da tutti gli utenti ({len(extras.seen_by_all)}):",
            shown + ([f"… e altri {hidden}"] if hidden else []),
        ),
    ]
