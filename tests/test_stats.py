from datetime import date, datetime

import pytest

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.stats import UnknownUser, compute_stats, group_extras
from watchlog.tmdb import MovieDetails

# Database di prova con numeri calcolati a mano.
#
#   mario:  Heat 05/07 (4.5), Heat 01/08 (5), Casino 10/07, Alien 15/08 (3)
#   franco: Heat 06/07 (4),   Alien 16/08,    Sconosciuto 20/08 (senza durata)


def movie(tmdb_id, title, year, runtime, genres=(), directors=()):
    return MovieDetails(tmdb_id, title, title, year, runtime, tuple(genres), tuple(directors))


@pytest.fixture
def db():
    db = Database.in_memory()
    db.sync_users([UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", None)])
    db.save_movie(movie(1, "Heat", 1995, 170, [(28, "Azione"), (80, "Crime")], [(488, "Michael Mann")]))
    db.save_movie(movie(2, "Casino", 1995, 178, [(80, "Crime"), (18, "Drammatico")], [(1032, "Martin Scorsese")]))
    db.save_movie(movie(3, "Alien", 1979, 117, [(878, "Fantascienza"), (27, "Horror")], [(578, "Ridley Scott")]))
    db.save_movie(movie(4, "Sconosciuto", 2020, None))
    views = [
        ("mario", 1, date(2026, 7, 5), 4.5),
        ("mario", 1, date(2026, 8, 1), 5.0),
        ("mario", 2, date(2026, 7, 10), None),
        ("mario", 3, date(2026, 8, 15), 3.0),
        ("franco", 1, date(2026, 7, 6), 4.0),
        ("franco", 3, date(2026, 8, 16), None),
        ("franco", 4, date(2026, 8, 20), None),
    ]
    for index, (user, tmdb_id, watched_on, rating) in enumerate(views):
        user_id = db.user_id_by_whatsapp(f"{user.capitalize()} Rossi")
        db.add_viewing(
            user_id=user_id,
            tmdb_id=tmdb_id,
            watched_on=watched_on,
            watched_on_source="body",
            rating=rating,
            sent_at=datetime(2026, 9, 1),
            source_ref=f"ref-{index}",
        )
    return db


class TestTotals:
    def test_group_totals(self, db):
        stats = compute_stats(db)

        assert stats.viewings == 7
        assert stats.distinct_films == 4
        assert stats.rewatches == 1  # Mario ha rivisto Heat; Franco che vede Heat non è una rivisione
        assert stats.runtime_minutes == 170 + 170 + 178 + 117 + 170 + 117
        assert stats.viewings_without_runtime == 1

    def test_user_totals(self, db):
        stats = compute_stats(db, user="mario")

        assert (stats.viewings, stats.distinct_films, stats.rewatches) == (4, 3, 1)
        assert stats.runtime_minutes == 635
        assert stats.viewings_without_runtime == 0

    def test_average_rating_counts_only_rated_viewings(self, db):
        group = compute_stats(db)
        mario = compute_stats(db, user="mario")
        franco = compute_stats(db, user="franco")

        assert (group.rated_viewings, group.average_rating) == (4, pytest.approx(4.125))
        assert (mario.rated_viewings, mario.average_rating) == (3, pytest.approx(12.5 / 3))
        assert (franco.rated_viewings, franco.average_rating) == (1, 4.0)

    def test_no_ratings_means_no_average(self):
        empty = Database.in_memory()

        stats = compute_stats(empty)

        assert (stats.viewings, stats.average_rating, stats.runtime_minutes) == (0, None, 0)

    def test_unknown_user_is_rejected(self, db):
        with pytest.raises(UnknownUser, match="nessuno"):
            compute_stats(db, user="nessuno")

    def test_deleted_viewings_are_not_counted(self, db):
        db._conn.execute("UPDATE viewing SET deleted_at = '2026-09-01' WHERE source_ref = 'ref-0'")

        assert compute_stats(db, user="mario").viewings == 3


class TestBreakdowns:
    def test_top_genres_by_viewings_ties_sorted_by_name(self, db):
        assert compute_stats(db).top_genres == [
            ("Crime", 4),
            ("Azione", 3),
            ("Fantascienza", 2),
            ("Horror", 2),
            ("Drammatico", 1),
        ]

    def test_user_top_genres(self, db):
        assert compute_stats(db, user="mario").top_genres[:2] == [("Crime", 3), ("Azione", 2)]

    def test_top_directors(self, db):
        assert compute_stats(db).top_directors == [("Michael Mann", 3), ("Ridley Scott", 2), ("Martin Scorsese", 1)]

    def test_top_n_limits_the_lists(self, db):
        stats = compute_stats(db, top_n=2)

        assert len(stats.top_genres) == 2
        assert len(stats.top_directors) == 2

    def test_decades_are_chronological_and_skip_unknown_years(self, db):
        assert compute_stats(db).decades == [(1970, 2), (1990, 4), (2020, 1)]

    def test_viewings_per_month_use_the_watched_date(self, db):
        assert compute_stats(db).per_month == [("2026-07", 3), ("2026-08", 4)]

    def test_most_rewatched_is_per_user(self, db):
        stats = compute_stats(db)

        assert [(r.user, r.title, r.times) for r in stats.most_rewatched] == [("mario", "Heat", 2)]
        assert compute_stats(db, user="franco").most_rewatched == []


class TestGroupExtras:
    def test_users_ranked_by_viewings(self, db):
        extras = group_extras(db)

        assert [(u.name, u.viewings, u.runtime_minutes) for u in extras.users] == [
            ("mario", 4, 635),
            ("franco", 3, 287),
        ]

    def test_most_watched_films_with_distinct_viewers(self, db):
        extras = group_extras(db)

        assert [(f.title, f.views, f.viewers) for f in extras.most_watched] == [
            ("Heat", 3, 2),
            ("Alien", 2, 2),
            ("Casino", 1, 1),
            ("Sconosciuto", 1, 1),
        ]

    def test_films_seen_by_every_user(self, db):
        assert group_extras(db).seen_by_all == ["Alien", "Heat"]

    def test_a_single_user_group_has_no_shared_films(self):
        db = Database.in_memory()
        db.sync_users([UserConfig("mario", "Mario Rossi", None)])
        db.save_movie(movie(1, "Heat", 1995, 170))
        db.add_viewing(
            user_id=db.user_id_by_whatsapp("Mario Rossi"),
            tmdb_id=1,
            watched_on=date(2026, 7, 5),
            watched_on_source="body",
            rating=None,
            sent_at=datetime(2026, 7, 6),
            source_ref="r",
        )

        assert group_extras(db).seen_by_all == []
