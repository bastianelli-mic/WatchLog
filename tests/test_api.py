from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from watchlog.api import create_app
from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.tmdb import MovieDetails


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
