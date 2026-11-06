"""Importa nel database le visualizzazioni di un export WhatsApp."""

import hashlib
import json
from dataclasses import dataclass, field

from watchlog.config import Corrections
from watchlog.db import Database
from watchlog.parser import Anomaly, Entry, parse_export
from watchlog.resolver import Resolution, resolve
from watchlog.tmdb import Candidate


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


def import_chat(text: str, db: Database, client, corrections: Corrections) -> ImportReport:
    """Importa l'export. Idempotente: una riga già importata non viene riletta né risolta di nuovo.

    L'import è atomico: se TMDB fallisce a metà, nulla viene salvato.
    """
    parsed = parse_export(text)
    report = ImportReport(entries=len(parsed.entries), anomalies=parsed.anomalies)
    film_ids: dict[tuple[str, int], int | None] = {}

    for entry in parsed.entries:
        user_id = db.user_id_by_whatsapp(entry.author)
        if user_id is None:
            report.unmapped_authors[entry.author] = report.unmapped_authors.get(entry.author, 0) + 1
            continue

        source_ref = _source_ref(entry)
        if db.has_viewing(source_ref):
            report.duplicates += 1
            continue

        key = (entry.title, entry.year)
        if key not in film_ids:
            film_ids[key] = _resolve_film(entry, client, corrections, report)
        tmdb_id = film_ids[key]
        if tmdb_id is None:
            report.unresolved_viewings += 1
            continue

        if not db.has_movie(tmdb_id):
            db.save_movie(client.details(tmdb_id))
            report.new_movies += 1
        db.add_viewing(
            user_id=user_id,
            tmdb_id=tmdb_id,
            watched_on=entry.watched_on,
            watched_on_source=entry.watched_on_source,
            rating=entry.rating,
            sent_at=entry.sent_at,
            source_ref=source_ref,
        )
        report.inserted += 1

    db.commit()
    return report


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


def _source_ref(entry: Entry) -> str:
    """Identifica la riga d'origine: autore, istante d'invio e film (nell'export non c'è un id del messaggio)."""
    raw = f"{entry.author}|{entry.sent_at.isoformat()}|{entry.title}|{entry.year}"
    return "whatsapp:" + hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
