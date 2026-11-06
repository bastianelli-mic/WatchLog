"""Client minimale per la ricerca di film su TMDB (solo libreria standard)."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

API_BASE = "https://api.themoviedb.org/3"
DEFAULT_KEY_FILE = Path("local/tmdb_api_key")
LANGUAGES = ("it-IT", "en-US")
TIMEOUT_SECONDS = 10

Fetch = Callable[[str, Mapping[str, str]], dict]


class TmdbError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    tmdb_id: int
    title_it: str | None
    title_en: str | None
    original_title: str | None
    year: int | None
    popularity: float

    @property
    def display_title(self) -> str:
        return self.title_it or self.title_en or self.original_title or "?"


class TmdbClient:
    def __init__(self, fetch: Fetch):
        self._fetch = fetch

    def search(self, title: str) -> list[Candidate]:
        """Cerca il titolo in italiano e in inglese, unendo i risultati per id.

        Non si filtra per anno lato TMDB: l'anno di uscita italiano può differire
        da quello originale, la tolleranza la applica il resolver.
        """
        merged: dict[int, dict] = {}
        for language in LANGUAGES:
            params = {"query": title, "language": language, "include_adult": "false"}
            for result in self._fetch("/search/movie", params).get("results", []):
                found = merged.setdefault(result["id"], {"id": result["id"]})
                found["title_it" if language == "it-IT" else "title_en"] = result.get("title")
                found["original_title"] = result.get("original_title")
                found["year"] = _year(result.get("release_date"))
                found["popularity"] = result.get("popularity", 0.0)
        return [
            Candidate(
                tmdb_id=found["id"],
                title_it=found.get("title_it"),
                title_en=found.get("title_en"),
                original_title=found.get("original_title"),
                year=found["year"],
                popularity=found["popularity"],
            )
            for found in merged.values()
        ]


def _year(release_date: str | None) -> int | None:
    return int(release_date[:4]) if release_date else None


def load_api_key(env: Mapping[str, str] = os.environ, key_file: Path = DEFAULT_KEY_FILE) -> str:
    key = env.get("TMDB_API_KEY", "").strip()
    if not key and key_file.is_file():
        key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise TmdbError(f"Chiave TMDB mancante: imposta TMDB_API_KEY oppure scrivila in {key_file}")
    return key


def http_fetch(api_key: str) -> Fetch:
    """Fetch reale. Il token di lettura (JWT, inizia con `eyJ`) va nell'header, la chiave v3 nell'URL."""
    is_token = api_key.startswith("eyJ")

    def fetch(path: str, params: Mapping[str, str]) -> dict:
        query = dict(params) if is_token else {**params, "api_key": api_key}
        headers = {"Accept": "application/json"}
        if is_token:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(f"{API_BASE}{path}?{urllib.parse.urlencode(query)}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise TmdbError("chiave TMDB non valida") from error
            raise TmdbError(f"TMDB ha risposto {error.code}") from error
        except urllib.error.URLError as error:
            raise TmdbError(f"TMDB non raggiungibile: {error.reason}") from error

    return fetch
