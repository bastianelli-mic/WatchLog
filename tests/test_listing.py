from datetime import date, datetime

import pytest

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.listing import ViewingRow, list_viewings, render_pages
from watchlog.stats import UnknownUser
from watchlog.tmdb import MovieDetails


@pytest.fixture
def db():
    db = Database.in_memory()
    db.sync_users([UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", None)])
    db.save_movie(MovieDetails(1, "Heat - La sfida", "Heat", 1995, 170, (), ()))
    db.save_movie(MovieDetails(2, "Il sesto senso", "The Sixth Sense", 1999, 107, (), ()))
    db.save_movie(MovieDetails(3, "Città di Dio", "Cidade de Deus", 2002, 130, (), ()))
    views = [
        ("Mario Rossi", 1, date(2026, 7, 5), 4.5),
        ("Franco Rossi", 2, date(2026, 7, 6), None),
        ("Mario Rossi", 3, date(2026, 8, 1), None),
        ("Mario Rossi", 1, date(2026, 8, 1), 5.0),
    ]
    for index, (user, tmdb_id, day, rating) in enumerate(views):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=tmdb_id,
            watched_on=day,
            watched_on_source="body",
            rating=rating,
            sent_at=datetime(2026, 9, 1),
            source_ref=f"r{index}",
        )
    return db


class TestListViewings:
    def test_most_recent_first_and_same_day_by_latest_id(self, db):
        rows = list_viewings(db)

        assert [(r.id, r.watched_on, r.user, r.title) for r in rows] == [
            (4, "2026-08-01", "mario", "Heat - La sfida"),
            (3, "2026-08-01", "mario", "Città di Dio"),
            (2, "2026-07-06", "franco", "Il sesto senso"),
            (1, "2026-07-05", "mario", "Heat - La sfida"),
        ]

    def test_rows_carry_year_and_rating(self, db):
        row = list_viewings(db)[0]

        assert (row.year, row.rating) == (1995, 5.0)

    def test_user_filter(self, db):
        assert [r.id for r in list_viewings(db, user="franco")] == [2]

    def test_unknown_user_is_rejected(self, db):
        with pytest.raises(UnknownUser, match="nessuno"):
            list_viewings(db, user="nessuno")

    def test_period_is_inclusive(self, db):
        rows = list_viewings(db, since=date(2026, 7, 6), until=date(2026, 8, 1))

        assert [r.id for r in rows] == [4, 3, 2]

    def test_filters_combine(self, db):
        assert [r.id for r in list_viewings(db, user="mario", since=date(2026, 8, 1))] == [4, 3]

    @pytest.mark.parametrize(
        ("needle", "expected"),
        [
            ("heat", [4, 1]),  # senza badare alle maiuscole
            ("SESTO", [2]),
            ("citta", [3]),  # senza badare agli accenti
            ("sixth sense", [2]),  # anche sul titolo originale
            ("zzz", []),
        ],
    )
    def test_title_filter_is_a_partial_match_ignoring_case_and_accents(self, db, needle, expected):
        assert [r.id for r in list_viewings(db, title=needle)] == expected

    def test_deleted_viewings_do_not_appear(self, db):
        db.query("UPDATE viewing SET deleted_at = '2026-09-01' WHERE id = 4")

        assert [r.id for r in list_viewings(db)] == [3, 2, 1]


def row(index, user="mario", title="Heat", year=1995, rating=None):
    return ViewingRow(index, f"2026-08-{index % 28 + 1:02d}", user, title, year, rating)


class TestRenderPages:
    def test_a_row_shows_id_date_user_title_year_and_rating(self):
        pages = render_pages([row(7, rating=4.5)], "Visioni: gruppo", show_user=True)

        assert len(pages) == 1
        assert pages[0].startswith("```\nVisioni: gruppo")
        assert "#7" in pages[0] and "08/08/2026" in pages[0] and "mario" in pages[0]
        assert "Heat (1995)" in pages[0] and "★4,5" in pages[0]

    def test_integer_rating_has_no_decimals(self):
        assert "★5" in render_pages([row(1, rating=5.0)], "Visioni", show_user=True)[0]

    def test_user_column_is_hidden_for_a_single_user_list(self):
        page = render_pages([row(1, user="mario")], "Visioni: mario", show_user=False)[0]

        assert "mario" not in page.split("\n", 2)[2]

    def test_row_without_a_year_has_no_empty_parentheses(self):
        assert "()" not in render_pages([row(1, year=None)], "Visioni", show_user=True)[0]

    def test_very_long_titles_are_truncated(self):
        page = render_pages([row(1, title="T" * 200)], "Visioni", show_user=True)[0]

        assert "T" * 200 not in page and "…" in page

    def test_pages_respect_the_row_limit_and_keep_order(self):
        rows = [row(i) for i in range(45, 0, -1)]

        pages = render_pages(rows, "Visioni", show_user=True, max_rows=20)

        assert len(pages) == 3
        body = [line for page in pages for line in page.splitlines()[2:-1]]
        assert [int(line.split()[0][1:]) for line in body] == list(range(45, 0, -1))
        assert "pagina 1/3" in pages[0] and "pagina 3/3" in pages[2]
        assert "45 visioni" in pages[0]

    def test_pages_never_exceed_the_message_size_even_with_long_titles(self):
        rows = [row(i, title="Titolo molto lungo " * 4) for i in range(1, 80)]

        pages = render_pages(rows, "Visioni: gruppo (dal 01/01/2026 al 31/12/2026)", show_user=True)

        assert len(pages) > 1
        assert all(len(page) <= 2000 for page in pages)

    def test_no_rows_no_pages(self):
        assert render_pages([], "Visioni", show_user=True) == []
