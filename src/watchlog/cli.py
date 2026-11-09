import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from watchlog.bot import sync_users
from watchlog.config import ConfigError, load_corrections, load_discord_config, load_discord_token, load_users
from watchlog.dates import format_date, parse_date
from watchlog.db import Database
from watchlog.edits import ViewingEditor
from watchlog.importer import ImportReport, corrections_template, import_chat
from watchlog.live import LiveService
from watchlog.parser import parse_export, parse_film_text
from watchlog.resolver import Resolution, resolve
from watchlog.report import render_stats
from watchlog.stats import UnknownUser, compute_stats, group_extras
from watchlog.tmdb import TmdbClient, TmdbError, http_fetch, load_api_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watchlog")
    commands = parser.add_subparsers(dest="command", required=True)

    parse_cmd = commands.add_parser("parse", help="legge un export WhatsApp e stampa le visualizzazioni")
    parse_cmd.add_argument("chat", type=Path, help="file di export della chat")

    resolve_cmd = commands.add_parser("resolve", help="cerca su TMDB un film scritto come 'titolo (anno)'")
    resolve_cmd.add_argument("film", help="per esempio 'Roofman (2025)'")

    chat_cmd = commands.add_parser("resolve-chat", help="risolve su TMDB tutti i film distinti di un export")
    chat_cmd.add_argument("chat", type=Path, help="file di export della chat")

    import_cmd = commands.add_parser("import", help="importa nel database le visualizzazioni di un export")
    import_cmd.add_argument("chat", type=Path, help="file di export della chat")
    import_cmd.add_argument("--db", type=Path, default=Path("data/watchlog.sqlite"))
    import_cmd.add_argument("--users", type=Path, default=Path("config/users.yaml"))
    import_cmd.add_argument("--corrections", type=Path, default=Path("config/corrections.yaml"))
    import_cmd.add_argument("--dry-run", action="store_true", help="simula l'import senza scrivere il database")

    stats_cmd = commands.add_parser("stats", help="statistiche del gruppo, o di un utente con --user")
    stats_cmd.add_argument("--db", type=Path, default=Path("data/watchlog.sqlite"))
    stats_cmd.add_argument("--user", help="nome interno dell'utente (come in users.yaml)")
    stats_cmd.add_argument("--dal", type=_date_argument, help="solo visioni da questa data (gg/mm/aaaa), inclusa")
    stats_cmd.add_argument("--al", type=_date_argument, help="solo visioni fino a questa data (gg/mm/aaaa), inclusa")

    bot_cmd = commands.add_parser("bot", help="avvia il bot Discord (comando /stats)")
    bot_cmd.add_argument("--db", type=Path, default=Path("data/watchlog.sqlite"))
    bot_cmd.add_argument("--discord-config", type=Path, default=Path("config/discord.yaml"))
    bot_cmd.add_argument("--users", type=Path, default=Path("config/users.yaml"))

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args.chat)
    if args.command == "stats":
        return _stats(args.db, args.user, args.dal, args.al)
    try:
        if args.command == "resolve":
            return _resolve(args.film)
        if args.command == "import":
            return _import(args)
        if args.command == "bot":
            return _bot(args)
        return _resolve_chat(args.chat)
    except TmdbError as error:
        print(f"Errore TMDB: {error}", file=sys.stderr)
        return 2
    except ConfigError as error:
        print(f"Errore di configurazione: {error}", file=sys.stderr)
        return 2


def _make_client() -> TmdbClient:
    return TmdbClient(http_fetch(load_api_key()))


def _resolve(film: str) -> int:
    parsed = parse_film_text(film)
    if parsed is None:
        print(f"Formato non valido: {film!r}, atteso 'titolo (anno)'", file=sys.stderr)
        return 2
    title, year = parsed
    _print_resolution(resolve(title, year, _make_client().search(title)))
    return 0


def _resolve_chat(chat: Path) -> int:
    try:
        text = chat.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Impossibile leggere {chat}: {error.strerror}", file=sys.stderr)
        return 2

    films = dict.fromkeys((entry.title, entry.year) for entry in parse_export(text).entries)
    client = _make_client()
    counts = {"resolved": 0, "ambiguous": 0, "not_found": 0}
    for title, year in films:
        resolution = resolve(title, year, client.search(title))
        counts[resolution.status] += 1
        _print_resolution(resolution)

    print(
        f"\n{counts['resolved']} risolti, {counts['ambiguous']} ambigui, "
        f"{counts['not_found']} non trovati su {len(films)} film distinti"
    )
    return 0


def _import(args: argparse.Namespace) -> int:
    try:
        text = args.chat.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Impossibile leggere {args.chat}: {error.strerror}", file=sys.stderr)
        return 2

    users = load_users(args.users)
    corrections = load_corrections(args.corrections)
    db = Database.in_memory(copy_of=args.db) if args.dry_run else Database.open(args.db)
    try:
        db.sync_users(users)
        report = import_chat(text, db, _make_client(), corrections)
    finally:
        db.close()

    _print_import_report(report, args.dry_run)
    return 0


def _bot(args: argparse.Namespace) -> int:
    from watchlog import discord_app  # import tardivo: gli altri comandi non ne hanno bisogno

    config = load_discord_config(args.discord_config)
    token = load_discord_token()
    sync_users(args.db, args.users)  # i nomi in users.yaml diventano quelli dell'autocompletamento
    client = None
    try:
        client = _make_client()
    except TmdbError as error:
        print(f"Senza TMDB: inserimento delle visioni disattivato e film di /modifica non cambiabili ({error})", file=sys.stderr)
    live = LiveService(args.db, client) if client is not None and config.input_channel_id is not None else None
    superusers = frozenset(str(discord_id) for discord_id in config.superusers)
    editor = ViewingEditor(args.db, superusers, client, today=lambda: datetime.now(discord_app.LOCAL_TZ).date())
    discord_app.run(token, config, args.db, live, editor)
    return 0


def _stats(db_path: Path, user: str | None, since: date | None, until: date | None) -> int:
    if not db_path.is_file():
        print(f"Database non trovato: {db_path}", file=sys.stderr)
        return 2
    db = Database.open(db_path)
    try:
        stats = compute_stats(db, user=user, since=since, until=until)
        extras = group_extras(db, since=since, until=until) if user is None else None
    except UnknownUser as error:
        print(error, file=sys.stderr)
        return 2
    finally:
        db.close()

    print("\n\n".join(render_stats(stats, extras, user, since, until)))
    return 0


def _date_argument(text: str) -> date:
    parsed = parse_date(text)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"data non valida: {text!r} (usa gg/mm/aaaa)")
    return parsed


def _print_import_report(report: ImportReport, dry_run: bool) -> None:
    print("Import (dry-run: nessuna scrittura)" if dry_run else "Import")
    print(f"visualizzazioni nel file: {report.entries}")
    print(f"inseriti: {report.inserted}")
    print(f"già presenti: {report.duplicates}")
    print(f"nuovi film: {report.new_movies}")

    if report.unmapped_authors:
        print("\nUtenti non mappati (aggiungili a users.yaml):")
        for author, count in report.unmapped_authors.items():
            print(f"  {author}: {count} visualizzazioni escluse")

    if report.unresolved:
        print(
            f"\nFilm da risolvere ({len(report.unresolved)} distinti, "
            f"{report.unresolved_viewings} visualizzazioni escluse).\n"
            "Controlla ogni riga e copiala in corrections.yaml; le righe commentate vanno prima completate:\n"
        )
        print(corrections_template(report.unresolved))

    if report.probable_duplicates:
        print(
            f"\nProbabili doppioni ({len(report.probable_duplicates)}): stesso utente, film e giorno "
            "di una visione già registrata, quindi non inseriti:"
        )
        for entry in report.probable_duplicates:
            print(f"  riga {entry.line_no} [{entry.author}] visto il {format_date(entry.watched_on)}: {entry.title} ({entry.year})")

    if report.suspicious_dates:
        print(f"\nDate sospette ({len(report.suspicious_dates)}): visione molto prima dell'invio, o dopo:")
        for entry in report.suspicious_dates:
            print(
                f"  riga {entry.line_no} [{entry.author}] visto il {format_date(entry.watched_on)}, "
                f"inviato il {format_date(entry.sent_at.date())}: {entry.title} ({entry.year})"
            )

    if report.anomalies:
        print(f"\nAnomalie del parser ({len(report.anomalies)}):")
        for found in report.anomalies:
            print(f"  riga {found.line_no} [{found.author}] {found.reason}: {found.raw}")


def _print_resolution(resolution: Resolution) -> None:
    query = f"{resolution.title} ({resolution.year})"
    if resolution.status == "resolved":
        print(f"resolved   {query} -> {_describe(resolution.best)}")
        return
    print(f"{resolution.status:10} {query}")
    for scored in resolution.scored[:5]:
        print(f"             - {_describe(scored)}")


def _describe(scored) -> str:
    candidate = scored.candidate
    return f"{candidate.display_title} ({candidate.year}) [id {candidate.tmdb_id}] score {scored.score:.2f}"


def _parse(chat: Path) -> int:
    try:
        text = chat.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Impossibile leggere {chat}: {error.strerror}", file=sys.stderr)
        return 2

    result = parse_export(text)

    for entry in result.entries:
        rating = f" [{entry.rating:g}]" if entry.rating is not None else ""
        print(
            f"{format_date(entry.watched_on)} ({entry.watched_on_source:7}) "
            f"{entry.author}: {entry.title} ({entry.year}){rating}"
        )

    if result.anomalies:
        print("\nAnomalie:")
        for found in result.anomalies:
            print(f"  riga {found.line_no} [{found.author}] {found.reason}: {found.raw}")

    print(f"\n{len(result.entries)} visualizzazioni, {len(result.anomalies)} anomalie")
    return 0
