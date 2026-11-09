"""Logica del bot Discord, senza dipendere da discord.py: l'adattatore è in `discord_app`."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from watchlog.config import GROUP_NAME, DiscordConfig, load_users
from watchlog.dates import parse_bound
from watchlog.db import Database
from watchlog.listing import list_viewings, render_pages
from watchlog.periods import period_range
from watchlog.report import DETAILS, period_text, render_stats
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
    periodo: str | None = None,
    today: date | None = None,
    discord_id: str | None = None,
    dettaglio: str = "base",
) -> Reply:
    """Senza `user` valgono i dati di chi ha lanciato il comando; `gruppo` chiede quelli di tutti.

    `dettaglio` sceglie il gruppo di statistiche oltre al riepilogo: vedi `report.DETAILS`."""
    if dettaglio not in DETAILS:
        return _private(f"Dettaglio sconosciuto: {dettaglio}. Scegli tra {', '.join(DETAILS)}.")
    if channel_id != config.stats_channel_id:
        return _private(f"Le statistiche si chiedono nel canale <#{config.stats_channel_id}>.")
    try:
        since, until = _resolve_period(periodo, since_text, until_text, today or date.today())
    except ValueError as error:
        return _private(str(error))
    if not db_path.is_file():
        return _private("Database non trovato: il bot non ha ancora dati.")

    db = Database.open(db_path)
    try:
        user = _target_user(db, user, discord_id)
        stats = compute_stats(db, user=user, top_n=top_n, since=since, until=until)
        extras = group_extras(db, top_n=top_n, since=since, until=until) if user is None else None
    except UnknownUser as error:
        return _private(str(error))
    finally:
        db.close()

    if dettaglio == "classifiche" and user is not None:
        return _private(f"Le classifiche esistono solo per il gruppo: usa `utente:{GROUP_NAME}`.")
    blocks = render_stats(stats, extras, user, since, until, details=(dettaglio,))
    return Reply([f"{_FENCE}\n{chunk}\n{_FENCE}" for chunk in chunk_blocks(blocks)])


def viewings_reply(
    db_path: Path,
    config: DiscordConfig,
    channel_id: int,
    user: str | None,
    periodo: str | None,
    since_text: str | None,
    until_text: str | None,
    title: str | None,
    today: date,
    discord_id: str | None = None,
) -> Reply:
    """Elenco delle visioni in pagine. `periodo` (oggi, settimana, mese, anno) e `dal`/`al` non si combinano.

    Senza `user` valgono le visioni di chi ha lanciato il comando; `gruppo` chiede quelle di tutti.
    """
    if channel_id != config.stats_channel_id:
        return _private(f"Le statistiche si chiedono nel canale <#{config.stats_channel_id}>.")
    try:
        since, until = _resolve_period(periodo, since_text, until_text, today)
    except ValueError as error:
        return _private(str(error))
    if not db_path.is_file():
        return _private("Database non trovato: il bot non ha ancora dati.")

    title = (title or "").strip() or None
    db = Database.open(db_path)
    try:
        user = _target_user(db, user, discord_id)
        rows = list_viewings(db, user=user, since=since, until=until, title=title)
    except UnknownUser as error:
        return _private(str(error))
    finally:
        db.close()

    if not rows:
        return Reply(["Nessuna visione trovata con questi filtri."])
    header = f"Visioni: {user or 'gruppo'}{period_text(since, until)}" + (f" · titolo «{title}»" if title else "")
    return Reply(render_pages(rows, header, show_user=user is None))


def _target_user(db: Database, user: str | None, discord_id: str | None) -> str | None:
    """Il nome da filtrare, o None per il gruppo. Senza `user`, chi ha lanciato il comando: se non lo si riconosce
    UnknownUser porta il messaggio per lui."""
    if user is not None and user.strip().lower() == GROUP_NAME:
        return None
    if user is not None:
        return user
    rows = db.query("SELECT name FROM users WHERE discord_id = ?", (discord_id,)) if discord_id else []
    if not rows:
        raise UnknownUser(
            "Non ti riconosco: chiedi di aggiungere il tuo discord_id a users.yaml. "
            f"Intanto puoi scegliere un nome in `utente`, oppure `{GROUP_NAME}` per tutti."
        )
    return rows[0]["name"]


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


def cancel_channel_error(config: DiscordConfig, channel_id: int) -> str | None:
    """L'annullamento si chiede nel canale delle statistiche o in quello delle visioni; altrove, il messaggio per l'utente."""
    channels = [config.stats_channel_id]
    if config.input_channel_id is not None:
        channels.append(config.input_channel_id)
    if channel_id in channels:
        return None
    return "Questo comando si usa in " + " o ".join(f"<#{channel}>" for channel in channels) + "."


def _resolve_period(
    periodo: str | None, since_text: str | None, until_text: str | None, today: date
) -> tuple[date | None, date | None]:
    """Il periodo da `periodo` oppure da `dal`/`al`; i due modi non si combinano. ValueError ha il messaggio per l'utente."""
    if periodo and (since_text or until_text):
        raise ValueError("Usa `periodo` oppure `dal` e `al`, non entrambi.")
    if periodo:
        return period_range(periodo, today)
    return _parse_bound(since_text, end=False), _parse_bound(until_text, end=True)


def _private(message: str) -> Reply:
    return Reply([message], ephemeral=True)


def _parse_bound(text: str | None, end: bool) -> date | None:
    if text is None:
        return None
    parsed = parse_bound(text, end)
    if parsed is None:
        raise ValueError(f"Data non valida: {text!r} (usa gg/mm/aaaa, mm/aaaa o aaaa).")
    return parsed
