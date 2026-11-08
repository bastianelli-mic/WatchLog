from datetime import date, datetime

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.tmdb import MovieDetails

MARIO = UserConfig("mario", "Mario Rossi", None)


def heat(**overrides):
    fields = dict(
        tmdb_id=949,
        title="Heat - La sfida",
        original_title="Heat",
        year=1995,
        runtime_minutes=170,
        genres=((28, "Azione"), (80, "Crime")),
        directors=((488, "Michael Mann"),),
    )
    return MovieDetails(**{**fields, **overrides})


def add(db, user_id, source_ref="ref-1", **overrides):
    fields = dict(
        user_id=user_id,
        tmdb_id=949,
        watched_on=date(2026, 7, 5),
        watched_on_source="body",
        rating=None,
        sent_at=datetime(2026, 7, 6, 0, 45),
        source_ref=source_ref,
    )
    return db.add_viewing(**{**fields, **overrides})


def test_open_creates_file_and_parent_directory(tmp_path):
    path = tmp_path / "data" / "watchlog.sqlite"

    Database.open(path).close()

    assert path.is_file()


def test_data_survives_reopening(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([MARIO])
    db.save_movie(heat())
    add(db, db.user_id_by_whatsapp("Mario Rossi"))
    db.commit()
    db.close()

    reopened = Database.open(path)

    assert [v["title"] for v in reopened.list_viewings()] == ["Heat - La sfida"]


def test_sync_users_updates_discord_id_without_duplicating(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    first_id = db.user_id_by_whatsapp("Mario Rossi")

    db.sync_users([UserConfig("mario", "Mario Rossi", "555")])

    assert db.user_id_by_whatsapp("Mario Rossi") == first_id
    assert db.user_id_by_discord("555") == first_id


def test_unknown_names_have_no_user(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")

    assert db.user_id_by_whatsapp("Nessuno") is None


def test_viewing_with_same_source_ref_is_not_added_twice(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    db.save_movie(heat())
    user_id = db.user_id_by_whatsapp("Mario Rossi")

    assert add(db, user_id) is True
    assert add(db, user_id) is False
    assert len(db.list_viewings()) == 1
    assert db.has_viewing("ref-1") is True


def test_same_film_with_different_source_ref_is_a_rewatch(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    db.save_movie(heat())
    user_id = db.user_id_by_whatsapp("Mario Rossi")

    add(db, user_id, "ref-1")
    add(db, user_id, "ref-2", watched_on=date(2026, 8, 1))

    assert len(db.list_viewings()) == 2


def test_saving_a_movie_again_replaces_genres_and_directors(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")

    db.save_movie(heat())
    db.save_movie(heat(genres=((80, "Crime"),), directors=((1, "Altro"),)))

    assert db.movie_genres(949) == ["Crime"]
    assert db.movie_directors(949) == ["Altro"]
    assert db.has_movie(949) is True
    assert db.has_movie(1) is False


def test_in_memory_copy_does_not_touch_the_file(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([MARIO])
    db.commit()
    db.close()

    copy = Database.in_memory(copy_of=path)
    copy.save_movie(heat())
    add(copy, copy.user_id_by_whatsapp("Mario Rossi"))
    copy.commit()

    assert len(copy.list_viewings()) == 1
    assert Database.open(path).list_viewings() == []


def test_in_memory_without_source_starts_empty():
    assert Database.in_memory().list_viewings() == []


def test_sync_users_renames_an_existing_user_keeping_id_and_viewings(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    db.save_movie(heat())
    user_id = db.user_id_by_whatsapp("Mario Rossi")
    add(db, user_id)

    db.sync_users([UserConfig("Bastio", "Mario Rossi", "555")])

    assert db.user_id_by_whatsapp("Mario Rossi") == user_id
    assert db.user_id_by_discord("555") == user_id
    assert [v["user"] for v in db.list_viewings()] == ["Bastio"]
    assert db.query("SELECT COUNT(*) AS n FROM users")[0]["n"] == 1


def test_same_day_check_matches_user_film_and_date_and_ignores_deleted(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO, UserConfig("franco", "Franco Rossi", None)])
    db.save_movie(heat())
    mario, franco = db.user_id_by_whatsapp("Mario Rossi"), db.user_id_by_whatsapp("Franco Rossi")
    add(db, mario)

    assert db.has_viewing_same_day(mario, 949, date(2026, 7, 5)) is True
    assert db.has_viewing_same_day(mario, 949, date(2026, 7, 6)) is False
    assert db.has_viewing_same_day(mario, 1, date(2026, 7, 5)) is False
    assert db.has_viewing_same_day(franco, 949, date(2026, 7, 5)) is False

    db.query("UPDATE viewing SET deleted_at = '2026-08-01'")
    assert db.has_viewing_same_day(mario, 949, date(2026, 7, 5)) is False


def test_get_viewing_returns_the_joined_row_or_none(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    db.save_movie(heat())
    add(db, db.user_id_by_whatsapp("Mario Rossi"))

    viewing = db.get_viewing(1)

    assert (viewing["user"], viewing["title"], viewing["year"], viewing["watched_on"]) == (
        "mario",
        "Heat - La sfida",
        1995,
        "2026-07-05",
    )
    assert viewing["deleted_at"] is None
    assert db.get_viewing(99) is None


def test_cancel_viewing_marks_it_deleted_once(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users([MARIO])
    db.save_movie(heat())
    add(db, db.user_id_by_whatsapp("Mario Rossi"))

    assert db.cancel_viewing(1) is True
    assert db.cancel_viewing(1) is False
    assert db.cancel_viewing(99) is False
    assert db.get_viewing(1)["deleted_at"] is not None
    assert db.list_viewings() == []
