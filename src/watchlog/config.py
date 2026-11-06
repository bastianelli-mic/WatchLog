"""Lettura dei file di configurazione: mappatura utenti e correzioni dei film."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from watchlog.resolver import normalize


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class UserConfig:
    name: str
    whatsapp: str
    discord_id: str | None


class Corrections:
    """Associazioni manuali `titolo (anno)` -> id TMDB, per i film che il resolver non risolve da solo."""

    def __init__(self, by_key: dict[tuple[str, int], int]):
        self._by_key = by_key

    def get(self, title: str, year: int) -> int | None:
        return self._by_key.get((normalize(title), year))


def load_users(path: Path) -> list[UserConfig]:
    users: list[UserConfig] = []
    for index, item in enumerate(_load_list(path, "users"), start=1):
        if not item.get("name"):
            raise ConfigError(f"{path}: utente #{index} senza 'name'")
        if not item.get("whatsapp"):
            raise ConfigError(f"{path}: utente {item['name']!r} senza 'whatsapp'")
        discord_id = item.get("discord_id")
        users.append(
            UserConfig(str(item["name"]), str(item["whatsapp"]), None if discord_id is None else str(discord_id))
        )
    _reject_duplicates(path, "name", [u.name for u in users])
    _reject_duplicates(path, "whatsapp", [u.whatsapp for u in users])
    return users


def load_corrections(path: Path) -> Corrections:
    if not path.is_file():
        return Corrections({})
    by_key: dict[tuple[str, int], int] = {}
    for item in _load_list(path, "corrections"):
        if not all(item.get(field) for field in ("title", "year", "tmdb_id")):
            raise ConfigError(f"{path}: correzione {item.get('title')!r} senza title, year o tmdb_id")
        by_key[(normalize(str(item["title"])), int(item["year"]))] = int(item["tmdb_id"])
    return Corrections(by_key)


def _load_list(path: Path, key: str) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        example = path.with_name(f"{path.stem}.example{path.suffix}")
        hint = f". Crealo dall'esempio: cp {example} {path}" if example.is_file() else ""
        raise ConfigError(f"File non trovato: {path}{hint}") from error
    except OSError as error:
        raise ConfigError(f"File non leggibile: {path} ({error.strerror})") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"{path}: YAML non valido: {error}") from error
    items = (data or {}).get(key) or []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ConfigError(f"{path}: '{key}' deve essere una lista di voci")
    return items


def _reject_duplicates(path: Path, field: str, values: list[str]) -> None:
    for value in values:
        if values.count(value) > 1:
            raise ConfigError(f"{path}: {field} duplicato: {value!r}")
