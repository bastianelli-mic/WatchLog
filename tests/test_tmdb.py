import io
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from watchlog import tmdb
from watchlog.tmdb import Candidate, TmdbClient, TmdbError, load_api_key

# Risposte scritte a mano nella forma dell'API TMDB (non sono registrazioni reali).
IT_RESPONSE = {
    "results": [
        {"id": 7, "title": "Il Menù", "original_title": "The Menu", "release_date": "2022-11-17", "popularity": 50.5},
        {"id": 8, "title": "Senza data", "original_title": "No Date", "release_date": "", "popularity": 0.1},
    ]
}
EN_RESPONSE = {
    "results": [
        {"id": 7, "title": "The Menu", "original_title": "The Menu", "release_date": "2022-11-17", "popularity": 50.5},
        {"id": 9, "title": "The Menu 2", "original_title": "The Menu 2", "release_date": "2024-01-01", "popularity": 3.0},
    ]
}


class FakeFetch:
    def __init__(self):
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, params))
        return IT_RESPONSE if params["language"] == "it-IT" else EN_RESPONSE


class TestSearch:
    def test_searches_both_languages_without_year_filter(self):
        fetch = FakeFetch()

        TmdbClient(fetch).search("The Menù")

        assert [(path, p["language"]) for path, p in fetch.calls] == [
            ("/search/movie", "it-IT"),
            ("/search/movie", "en-US"),
        ]
        assert all(p["query"] == "The Menù" and "year" not in p for _, p in fetch.calls)
        assert all(p["include_adult"] == "false" for _, p in fetch.calls)

    def test_same_film_in_both_languages_is_merged_keeping_both_titles(self):
        candidates = {c.tmdb_id: c for c in TmdbClient(FakeFetch()).search("The Menù")}

        assert candidates[7] == Candidate(
            tmdb_id=7,
            title_it="Il Menù",
            title_en="The Menu",
            original_title="The Menu",
            year=2022,
            popularity=50.5,
        )
        assert set(candidates) == {7, 8, 9}

    def test_missing_release_date_gives_no_year(self):
        candidates = {c.tmdb_id: c for c in TmdbClient(FakeFetch()).search("The Menù")}

        assert candidates[8].year is None


class TestApiKey:
    def test_environment_variable_wins_over_file(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text("from-file\n")

        assert load_api_key({"TMDB_API_KEY": "from-env"}, key_file) == "from-env"

    def test_file_is_used_when_variable_is_missing(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text("  from-file \n")

        assert load_api_key({}, key_file) == "from-file"

    def test_missing_key_is_an_error_naming_both_places(self, tmp_path):
        with pytest.raises(TmdbError, match="TMDB_API_KEY"):
            load_api_key({}, tmp_path / "nope")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestHttpFetch:
    def test_v3_key_goes_in_the_query_string(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            return FakeResponse(b'{"results": []}')

        monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_urlopen)

        tmdb.http_fetch("abc123")("/search/movie", {"query": "Heat"})

        query = parse_qs(urlparse(seen["url"]).query)
        assert urlparse(seen["url"]).path == "/3/search/movie"
        assert query == {"query": ["Heat"], "api_key": ["abc123"]}
        assert seen["auth"] is None

    def test_read_access_token_goes_in_the_bearer_header(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            return FakeResponse(b'{"results": []}')

        monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_urlopen)

        tmdb.http_fetch("eyJhbGciOi.token")("/search/movie", {"query": "Heat"})

        assert "api_key" not in seen["url"]
        assert seen["auth"] == "Bearer eyJhbGciOi.token"

    def test_unauthorized_is_reported_as_invalid_key(self, monkeypatch):
        def fake_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(TmdbError, match="chiave TMDB non valida"):
            tmdb.http_fetch("bad")("/search/movie", {"query": "Heat"})

    def test_network_failure_is_a_tmdb_error(self, monkeypatch):
        def fake_urlopen(request, timeout):
            raise urllib.error.URLError("nessuna rete")

        monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(TmdbError, match="nessuna rete"):
            tmdb.http_fetch("k")("/search/movie", {"query": "Heat"})
