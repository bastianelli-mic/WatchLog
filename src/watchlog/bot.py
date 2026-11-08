"""Logica del bot Discord, senza dipendere da discord.py: l'adattatore è in `discord_app`."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from watchlog.config import DiscordConfig, load_users
from watchlog.db import Database
from watchlog.report import render_stats
from watchlog.stats import TOP_N, UnknownUser, compute_stats, group_extras

MESSAGE_LIMIT = 1900  # un messaggio Discord arriva a 2000 caratteri: il resto serve al blocco di codice
_FENCE = "```"


@dataclass(frozen=True)
class Reply:
    messages: list[str]
    ephemeral: bool = False  # visibile solo a chi ha lanciato il comando


def chunk_blocks(blocks: list[str], limit: int = MESSAGE_LIMIT) -> list[str]:
    """Impacchetta i blocchi in messaggi, nell'ordine, senza superare `limit`; un blocco troppo lungo si spezza per righe."""
    chunks: list[str] = []
    current = ""
    for block in blocks:
        for piece in _split(block, limit):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _split(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    pieces: list[str] = []
    current = ""
    for line in block.splitlines():
        for part in (line[i : i + limit] for i in range(0, max(len(line), 1), limit)):
            candidate = f"{current}\n{part}" if current else part
            if len(candidate) <= limit:
                current = candidate
            else:
                pieces.append(current)
                current = part
    if current:
        pieces.append(current)
    return pieces


def stats_reply(
    db_path: Path,
    config: DiscordConfig,
    channel_id: int,
    user: str | None = None,
    since_text: str | None = None,
    until_text: str | None = None,
    top_n: int = TOP_N,
) -> Reply:
    if channel_id != config.stats_channel_id:
        return _private(f"Le statistiche si chiedono nel canale <#{config.stats_channel_id}>.")
    try:
        since, until = _parse_date(since_text), _parse_date(until_text)
    except ValueError as error:
        return _private(str(error))
    if not db_path.is_file():
        return _private("Database non trovato: il bot non ha ancora dati.")

    db = Database.open(db_path)
    try:
        stats = compute_stats(db, user=user, top_n=top_n, since=since, until=until)
        extras = group_extras(db, top_n=top_n, since=since, until=until) if user is None else None
    except UnknownUser as error:
        return _private(str(error))
    finally:
        db.close()

    blocks = render_stats(stats, extras, user, since, until)
    return Reply([f"{_FENCE}\n{chunk}\n{_FENCE}" for chunk in chunk_blocks(blocks)])


def sync_users(db_path: Path, users_path: Path) -> bool:
    """Applica users.yaml al database: nomi e ID Discord cambiati nel file diventano effettivi.

    Non crea il database né richiede il file: se uno dei due manca non fa nulla e restituisce False.
    """
    if not db_path.is_file() or not users_path.is_file():
        return False
    users = load_users(users_path)
    db = Database.open(db_path)
    try:
        db.sync_users(users)
        db.commit()
    finally:
        db.close()
    return True


def user_names(db_path: Path) -> list[str]:
    """Nomi interni degli utenti, per il completamento automatico del comando."""
    if not db_path.is_file():
        return []
    db = Database.open(db_path)
    try:
        return [row["name"] for row in db.query("SELECT name FROM users ORDER BY name")]
    finally:
        db.close()


def _private(message: str) -> Reply:
    return Reply([message], ephemeral=True)


def _parse_date(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"Data non valida: {text!r} (usa AAAA-MM-GG).") from None
