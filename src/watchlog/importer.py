"""Importa nel database le visualizzazioni di un export WhatsApp."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from watchlog.config import Corrections
from watchlog.dates import format_date
from watchlog.db import Database
from watchlog.parser import Anomaly, Entry, parse_export
from watchlog.resolver import Resolution, resolve
from watchlog.tmdb import Candidate, MovieDetails

MAX_DAYS_BEFORE_SEND = 31  # oltre, la data di visione scritta in chat è probabilmente un refuso


@dataclass
class ImportReport:
    entries: int = 0
    inserted: int = 0
    duplicates: int = 0
    new_movies: int = 0
    anomalies: list[Anomaly] = field(default_factory=list)
    unmapped_authors: dict[str, int] = field(default_factory=dict)
    unresolved: list[Resolution] = field(default_factory=list)  # un film distinto per voce
    unresolved_viewings: int = 0
    suspicious_dates: list[Entry] = field(default_factory=list)
    probable_duplicates: list[Entry] = field(default_factory=list)  # non inseriti: la visione c'era già


@dataclass(frozen=True)
class PlannedViewing:
    user_id: int
    tmdb_id: int
    watched_on: date
    watched_on_source: str
    rating: float | None
    sent_at: datetime
    source_ref: str


@dataclass
class ImportPlan:
    """Cosa l'import inserirebbe, deciso senza scrivere nel database."""

    report: ImportReport
    movies: dict[int, MovieDetails]  # solo i film nuovi, da salvare
    viewings: list[PlannedViewing]


def plan_import(text: str, db: Database, client, corrections: Corrections) -> ImportPlan:
    """Legge l'export e prepara l'import, senza scrivere: risolve i film su TMDB e decide cosa inserire.

    Le chiamate di rete avvengono qui, fuori dalla transazione di scrittura: `apply_import` poi
    tiene il lock SQLite solo per il tempo delle INSERT.
    """
    parsed = parse_export(text)
    report = ImportReport(entries=len(parsed.entries), anomalies=parsed.anomalies)
    report.suspicious_dates = [entry for entry in parsed.entries if _is_suspicious_date(entry)]
    film_ids: dict[tuple[str, int], int | None] = {}
    movies: dict[int, MovieDetails] = {}
    planned_refs: set[str] = set()
    planned_same_day: set[tuple[int, int, date]] = set()
    viewings: list[PlannedViewing] = []

    for entry in parsed.entries:
        found = db.find_user_by_chat_name(entry.author)
        if found is None:
            report.unmapped_authors[entry.author] = report.unmapped_authors.get(entry.author, 0) + 1
            continue
        user_id, chat_name = found

        source_ref = _source_ref(entry, chat_name)
        if source_ref in planned_refs or db.has_viewing(source_ref):
            report.duplicates += 1
            continue

        key = (entry.title, entry.year)
        if key not in film_ids:
            film_ids[key] = _resolve_film(entry, client, corrections, report)
        tmdb_id = film_ids[key]
        if tmdb_id is None:
            report.unresolved_viewings += 1
            continue

        same_day = (user_id, tmdb_id, entry.watched_on)
        if same_day in planned_same_day or db.has_viewing_same_day(user_id, tmdb_id, entry.watched_on):
            # Di solito è un messaggio modificato e riesportato (cambia il testo, quindi la chiave): non lo si raddoppia.
            report.probable_duplicates.append(entry)
            continue

        if not db.has_movie(tmdb_id) and tmdb_id not in movies:
            movies[tmdb_id] = client.details(tmdb_id)
            report.new_movies += 1

        planned_refs.add(source_ref)
        planned_same_day.add(same_day)
        viewings.append(
            PlannedViewing(
                user_id=user_id,
                tmdb_id=tmdb_id,
                watched_on=entry.watched_on,
                watched_on_source=entry.watched_on_source,
                rating=entry.rating,
                sent_at=entry.sent_at,
                source_ref=source_ref,
            )
        )
        report.inserted += 1

    return ImportPlan(report, movies, viewings)


def apply_import(db: Database, plan: ImportPlan) -> ImportReport:
    """Scrive il piano in un'unica transazione breve. Restituisce il report, aggiornato con gli inserimenti reali."""
    for movie in plan.movies.values():
        db.save_movie(movie)
    inserted = 0
    for viewing in plan.viewings:
        if db.add_viewing(
            user_id=viewing.user_id,
            tmdb_id=viewing.tmdb_id,
            watched_on=viewing.watched_on,
            watched_on_source=viewing.watched_on_source,
            rating=viewing.rating,
            sent_at=viewing.sent_at,
            source_ref=viewing.source_ref,
        ):
            inserted += 1
        else:
            plan.report.duplicates += 1
    db.commit()
    plan.report.inserted = inserted
    return plan.report


def import_chat(text: str, db: Database, client, corrections: Corrections) -> ImportReport:
    """Importa l'export in due fasi. Idempotente: una riga già importata non viene riletta né risolta di nuovo.

    L'import è atomico: se TMDB fallisce durante il piano, nessuna visione viene salvata.
    """
    return apply_import(db, plan_import(text, db, client, corrections))


def render_import_report(report: ImportReport, dry_run: bool) -> str:
    """Il report dell'import come testo, uguale per CLI e sito."""
    lines = [
        "Import (dry-run: nessuna scrittura)" if dry_run else "Import",
        f"visualizzazioni nel file: {report.entries}",
        f"inseriti: {report.inserted}",
        f"già presenti: {report.duplicates}",
        f"nuovi film: {report.new_movies}",
    ]

    if report.unmapped_authors:
        lines.append("")
        lines.append("Utenti non mappati (aggiungili a users.yaml):")
        for author, count in report.unmapped_authors.items():
            lines.append(f"  {author}: {count} visualizzazioni escluse")

    if report.unresolved:
        lines.append("")
        lines.append(
            f"Film da risolvere ({len(report.unresolved)} distinti, "
            f"{report.unresolved_viewings} visualizzazioni escluse).\n"
            "Controlla ogni riga e copiala in corrections.yaml; le righe commentate vanno prima completate:\n"
        )
        lines.append(corrections_template(report.unresolved))

    if report.probable_duplicates:
        lines.append("")
        lines.append(
            f"Probabili doppioni ({len(report.probable_duplicates)}): stesso utente, film e giorno "
            "di una visione già registrata, quindi non inseriti:"
        )
        for entry in report.probable_duplicates:
            lines.append(
                f"  riga {entry.line_no} [{entry.author}] visto il {format_date(entry.watched_on)}: "
                f"{entry.title} ({entry.year})"
            )

    if report.suspicious_dates:
        lines.append("")
        lines.append(f"Date sospette ({len(report.suspicious_dates)}): visione molto prima dell'invio, o dopo:")
        for entry in report.suspicious_dates:
            lines.append(
                f"  riga {entry.line_no} [{entry.author}] visto il {format_date(entry.watched_on)}, "
                f"inviato il {format_date(entry.sent_at.date())}: {entry.title} ({entry.year})"
            )

    if report.anomalies:
        lines.append("")
        lines.append(f"Anomalie del parser ({len(report.anomalies)}):")
        for found in report.anomalies:
            lines.append(f"  riga {found.line_no} [{found.author}] {found.reason}: {found.raw}")

    return "\n".join(lines)


def corrections_template(unresolved: list[Resolution]) -> str:
    """Testo da copiare in corrections.yaml per i film non risolti.

    Un solo candidato: riga attiva con il suo id, da controllare. Più candidati o nessuno:
    riga commentata da attivare dopo aver scelto l'id.
    """
    if not unresolved:
        return ""
    lines = ["corrections:"]
    for resolution in unresolved:
        key = f"{{title: {json.dumps(resolution.title, ensure_ascii=False)}, year: {resolution.year}"
        if len(resolution.scored) == 1:
            best = resolution.best
            lines.append(f"  - {key}, tmdb_id: {best.candidate.tmdb_id}}}  # {_name(best.candidate)}, score {best.score:.2f}")
        elif resolution.scored:
            options = " | ".join(f"{s.candidate.tmdb_id} {_name(s.candidate)}" for s in resolution.scored[:5])
            lines.append(f"  # - {key}, tmdb_id: ???}}  # scegli: {options}")
        else:
            lines.append(f"  # - {key}, tmdb_id: ???}}  # non trovato su TMDB")
    return "\n".join(lines)


def _name(candidate: Candidate) -> str:
    return f"{candidate.display_title} ({candidate.year})"


def _resolve_film(entry: Entry, client, corrections: Corrections, report: ImportReport) -> int | None:
    corrected = corrections.get(entry.title, entry.year)
    if corrected is not None:
        return corrected
    resolution = resolve(entry.title, entry.year, client.search(entry.title))
    if resolution.status == "resolved":
        return resolution.best.candidate.tmdb_id
    report.unresolved.append(resolution)
    return None


def _is_suspicious_date(entry: Entry) -> bool:
    """Data scritta in chat molto prima dell'invio, o successiva ad esso. Il ripiego sulla data di invio non conta."""
    if entry.watched_on_source != "body":
        return False
    days_before_send = (entry.sent_at.date() - entry.watched_on).days
    return days_before_send > MAX_DAYS_BEFORE_SEND or days_before_send < 0


def _source_ref(entry: Entry, chat_name: str) -> str:
    """Identifica la riga d'origine (nell'export non c'è un id del messaggio): nome principale dell'utente, minuto
    d'invio e film. Né gli alias né i secondi entrano nella chiave, così lo stesso messaggio riesportato da un altro
    telefono, o in un altro formato, risulta già importato."""
    raw = f"{chat_name}|{entry.sent_at.replace(second=0, microsecond=0).isoformat()}|{entry.title}|{entry.year}"
    return "whatsapp:" + hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
