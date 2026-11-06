import argparse
import sys
from pathlib import Path

from watchlog.parser import parse_export, parse_film_text
from watchlog.resolver import Resolution, resolve
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

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args.chat)
    try:
        if args.command == "resolve":
            return _resolve(args.film)
        return _resolve_chat(args.chat)
    except TmdbError as error:
        print(f"Errore TMDB: {error}", file=sys.stderr)
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
            f"{entry.watched_on} ({entry.watched_on_source:7}) "
            f"{entry.author}: {entry.title} ({entry.year}){rating}"
        )

    if result.anomalies:
        print("\nAnomalie:")
        for found in result.anomalies:
            print(f"  riga {found.line_no} [{found.author}] {found.reason}: {found.raw}")

    print(f"\n{len(result.entries)} visualizzazioni, {len(result.anomalies)} anomalie")
    return 0
