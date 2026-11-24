from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from watchlog.api import create_app
from watchlog.config import UserConfig
from watchlog.dates import local_today
from watchlog.db import Database
from watchlog.tmdb import Candidate, MovieDetails, TmdbError


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([UserConfig("mario", "Mario Rossi", "111"), UserConfig("franco", "Franco Rossi", "222")])
    db.save_movie(MovieDetails(1, "Heat", "Heat", 1995, 170, ((28, "Azione"),), ((488, "Michael Mann"),)))
    db.save_movie(MovieDetails(2, "Il sorpasso", "Il sorpasso", 1962, 105, ((35, "Commedia"),), ((1, "Dino Risi"),)))
    viewings = [
        ("Mario Rossi", 1, date(2026, 7, 5), 4.0),
        ("Mario Rossi", 2, date(2026, 7, 6), None),
        ("Franco Rossi", 1, date(2026, 8, 1), 3.5),
    ]
    for index, (user, tmdb_id, day, rating) in enumerate(viewings):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=tmdb_id,
            watched_on=day,
            watched_on_source="body",
            rating=rating,
            sent_at=datetime(2026, 8, 2),
            source_ref=f"r{index}",
        )
    db.commit()
    db.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))


class TestUsers:
    def test_lists_the_names_in_alphabetical_order(self, client):
        response = client.get("/api/users")

        assert response.status_code == 200
        assert response.json() == ["franco", "mario"]


class TestStats:
    def test_without_user_gives_the_group_numbers_and_rankings(self, client):
        body = client.get("/api/stats").json()

        assert body["stats"]["viewings"] == 3
        assert body["stats"]["distinct_films"] == 2
        assert body["stats"]["runtime_minutes"] == 170 + 105 + 170
        assert body["group"]["users"] == [
            {"name": "mario", "viewings": 2, "runtime_minutes": 275},
            {"name": "franco", "viewings": 1, "runtime_minutes": 170},
        ]
        assert body["group"]["seen_by_all"] == ["Heat"]

    def test_with_user_gives_only_their_numbers_and_no_rankings(self, client):
        body = client.get("/api/stats", params={"user": "franco"}).json()

        assert body["stats"]["viewings"] == 1
        assert body["stats"]["average_rating"] == 3.5
        assert body["group"] is None

    def test_period_limits_by_watched_date_inclusive(self, client):
        body = client.get("/api/stats", params={"since": "2026-07-06", "until": "2026-08-01"}).json()

        assert body["stats"]["viewings"] == 2

    def test_lists_are_named_objects(self, client):
        stats = client.get("/api/stats", params={"user": "mario"}).json()["stats"]

        assert stats["top_genres"] == [{"name": "Azione", "count": 1}, {"name": "Commedia", "count": 1}]
        assert stats["top_directors"][0] == {"name": "Dino Risi", "count": 1}
        assert stats["decades"] == [{"decade": 1960, "count": 1}, {"decade": 1990, "count": 1}]
        assert stats["per_month"] == [{"month": "2026-07", "viewings": 2, "minutes": 275}]
        assert stats["busiest_days"][0] == {"day": "2026-07-05", "count": 1}
        assert stats["longest_streak"] == {"days": 2, "start": "2026-07-05", "end": "2026-07-06"}
        assert stats["longest_film"] == {"title": "Heat", "minutes": 170}
        assert stats["weekdays"] == [1, 0, 0, 0, 0, 0, 1]  # lunedì 6/7 in testa, domenica 5/7 in coda
        assert {"period": "giorno", "count": 1, "start": "2026-07-05", "end": "2026-07-05"} in stats["records"]

    def test_unknown_user_is_not_found(self, client):
        response = client.get("/api/stats", params={"user": "nessuno"})

        assert response.status_code == 404
        assert "nessuno" in response.json()["detail"]

    def test_invalid_date_is_rejected(self, client):
        assert client.get("/api/stats", params={"since": "05/07/2026"}).status_code == 422


class TestViewings:
    def test_newest_first_with_every_field(self, client):
        body = client.get("/api/viewings").json()

        assert [row["watched_on"] for row in body] == ["2026-08-01", "2026-07-06", "2026-07-05"]
        assert body[0] == {
            "id": 3,
            "watched_on": "2026-08-01",
            "user": "franco",
            "title": "Heat",
            "year": 1995,
            "rating": 3.5,
        }

    def test_filters_by_user_period_and_title(self, client):
        assert len(client.get("/api/viewings", params={"user": "mario"}).json()) == 2
        assert len(client.get("/api/viewings", params={"until": "2026-07-05"}).json()) == 1
        assert [row["title"] for row in client.get("/api/viewings", params={"title": "sorpas"}).json()] == ["Il sorpasso"]

    def test_unknown_user_is_not_found(self, client):
        assert client.get("/api/viewings", params={"user": "nessuno"}).status_code == 404


class FakeClient:
    def __init__(self):
        self.search_calls = []
        self.details_calls = []

    def search(self, title):
        self.search_calls.append(title)
        if title == "Heat":
            return [Candidate(1, "Heat", None, "Heat", 1995, 1.0)]
        if title == "Roofman":
            return [Candidate(3, "Roofman", None, "Roofman", 2025, 1.0)]
        if title == "Ambigua":
            return [
                Candidate(4, "Ambigua", None, "Ambigua", 2025, 1.0),
                Candidate(5, "Ambigua", None, "Ambigua", 2025, 0.9),
            ]
        if title == "Guasto":
            raise TmdbError("TMDB non raggiungibile")
        return []

    def details(self, tmdb_id):
        self.details_calls.append(tmdb_id)
        title = "Roofman" if tmdb_id == 3 else f"Film {tmdb_id}"
        return MovieDetails(tmdb_id, title, title, 2025, 120, ((18, "Drammatico"),), ((1, "Regista"),))


@pytest.fixture
def write_api(db_path):
    fake = FakeClient()
    return TestClient(create_app(db_path, client_factory=lambda: fake)), fake


def post_viewing(client, **overrides):
    body = {"user": "mario", "film": "Roofman (2025)", "watched_on": "2026-08-02"}
    body.update(overrides)
    return client.post("/api/viewings", json=body)


class TestAddViewing:
    def test_a_resolved_film_is_recorded_and_appears_in_the_list(self, write_api):
        client, fake = write_api

        response = post_viewing(client, rating=4.5)

        assert response.status_code == 201
        assert "Roofman (2025)" in response.json()["message"]
        row = next(v for v in client.get("/api/viewings").json() if v["title"] == "Roofman")
        assert (row["user"], row["watched_on"], row["rating"]) == ("mario", "2026-08-02", 4.5)
        assert fake.details_calls == [3]

    def test_missing_date_uses_today(self, write_api):
        client, _ = write_api

        response = post_viewing(client, watched_on=None)

        assert response.status_code == 201
        row = next(v for v in client.get("/api/viewings").json() if v["title"] == "Roofman")
        assert row["watched_on"] == local_today().isoformat()

    def test_an_ambiguous_film_returns_the_candidates_and_the_chosen_id_is_recorded(self, write_api):
        client, fake = write_api

        first = post_viewing(client, film="Ambigua (2025)")

        assert first.status_code == 409
        detail = first.json()["detail"]
        assert detail["status"] == "ambiguous"
        assert [c["tmdb_id"] for c in detail["candidates"]] == [4, 5]

        chosen = post_viewing(client, film="Ambigua (2025)", tmdb_id=4)

        assert chosen.status_code == 201
        assert fake.details_calls == [4]
        assert any(v["title"] == "Film 4" for v in client.get("/api/viewings").json())

    def test_a_same_day_viewing_asks_before_recording_it_again(self, write_api):
        client, _ = write_api

        first = client.post(
            "/api/viewings",
            json={"user": "franco", "film": "Heat (1995)", "watched_on": "2026-08-01"},
        )
        assert first.status_code == 409
        assert first.json()["detail"]["status"] == "duplicate"

        confirmed = client.post(
            "/api/viewings",
            json={"user": "franco", "film": "Heat (1995)", "watched_on": "2026-08-01", "confirm_duplicate": True},
        )
        assert confirmed.status_code == 201
        rows = [v for v in client.get("/api/viewings").json() if v["user"] == "franco" and v["title"] == "Heat"]
        assert len(rows) == 2

    def test_a_film_not_found_on_tmdb_is_rejected(self, write_api):
        client, _ = write_api

        response = post_viewing(client, film="Sconosciuto (2020)")

        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "rejected"
        assert "TMDB" in response.json()["detail"]["message"]

    def test_an_unknown_user_is_not_found(self, write_api):
        client, _ = write_api

        assert post_viewing(client, user="nessuno").status_code == 404

    @pytest.mark.parametrize("film", ["Roofman", "Roofman 2025", "(2025)"])
    def test_the_film_must_be_written_as_title_and_year(self, write_api, film):
        client, _ = write_api

        assert post_viewing(client, film=film).status_code == 422

    @pytest.mark.parametrize("rating", [0, 0.3, 5.5, 6])
    def test_the_rating_must_be_a_half_step_between_half_and_five(self, write_api, rating):
        client, _ = write_api

        assert post_viewing(client, rating=rating).status_code == 422

    def test_a_tmdb_failure_is_reported_without_recording(self, write_api):
        client, _ = write_api

        response = post_viewing(client, film="Guasto (2025)")

        assert response.status_code == 502
        assert "TMDB" in response.json()["detail"]
        assert not any(v["title"] == "Guasto" for v in client.get("/api/viewings").json())


def test_missing_database_is_reported_as_unavailable(tmp_path):
    client = TestClient(create_app(tmp_path / "manca.sqlite"))

    response = client.get("/api/stats")

    assert response.status_code == 503
    assert not (tmp_path / "manca.sqlite").exists()  # l'API non crea il database


def test_serves_the_web_page_next_to_the_api(db_path, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>WatchLog</h1>", encoding="utf-8")
    client = TestClient(create_app(db_path, web_dir=web))

    assert "WatchLog" in client.get("/").text
    assert client.get("/api/users").json() == ["franco", "mario"]
