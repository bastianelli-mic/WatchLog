from datetime import date, datetime

import pytest

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.edits import Done, ViewingEditor
from watchlog.live import Ask, Cancelled, Rejected
from watchlog.tmdb import Candidate, MovieDetails, TmdbError

MARIO, FRANCO, SUPER, STRANGER = "111", "222", "333", "999"


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users(
        [
            UserConfig("mario", "Mario Rossi", MARIO),
            UserConfig("franco", "Franco Rossi", FRANCO),
            UserConfig("capo", "Capo Rossi", SUPER),
        ]
    )
    db.save_movie(MovieDetails(1, "Heat - La sfida", "Heat", 1995, 170, (), ()))
    for index, user in enumerate(["Mario Rossi", "Franco Rossi"], start=1):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=1,
            watched_on=date(2026, 7, 5),
            watched_on_source="body",
            rating=None,
            sent_at=datetime(2026, 7, 6),
            source_ref=f"r{index}",
        )
    db.commit()
    db.close()
    return ViewingEditor(path, frozenset({SUPER})), path  # visione 1 = mario, 2 = franco


def viewings(path):
    db = Database.open(path)
    try:
        return [(v["user"], v["title"]) for v in db.list_viewings()]
    finally:
        db.close()


class TestRequestCancel:
    def test_the_author_is_asked_for_confirmation_with_the_details(self, setup):
        editor, path = setup

        ask = editor.request_cancel(MARIO, 1)

        assert isinstance(ask, Ask) and ask.kind == "cancel"
        assert "#1" in ask.text and "Heat - La sfida (1995)" in ask.text and "05/07/2026" in ask.text
        assert "di franco" not in ask.text
        assert [o.value for o in ask.options] == ["yes", "no"]
        assert len(viewings(path)) == 2  # niente è ancora cambiato

    def test_other_peoples_viewings_cannot_be_cancelled(self, setup):
        editor, path = setup

        outcome = editor.request_cancel(MARIO, 2)

        assert isinstance(outcome, Rejected)
        assert "tue" in outcome.text
        assert len(viewings(path)) == 2

    def test_a_superuser_can_cancel_anyones_viewing_and_the_text_names_the_owner(self, setup):
        editor, _ = setup

        ask = editor.request_cancel(SUPER, 2)

        assert isinstance(ask, Ask)
        assert "di franco" in ask.text

    def test_unknown_discord_user_is_told_how_to_be_added(self, setup):
        editor, _ = setup

        outcome = editor.request_cancel(STRANGER, 1)

        assert isinstance(outcome, Rejected) and "users.yaml" in outcome.text

    def test_a_viewing_that_does_not_exist_is_reported(self, setup):
        editor, _ = setup

        outcome = editor.request_cancel(MARIO, 99)

        assert isinstance(outcome, Rejected) and "99" in outcome.text

    def test_an_already_cancelled_viewing_is_reported(self, setup):
        editor, _ = setup
        editor.answer(editor.request_cancel(MARIO, 1), "yes")

        outcome = editor.request_cancel(MARIO, 1)

        assert isinstance(outcome, Rejected) and "già" in outcome.text


class TestAnswer:
    def test_confirming_cancels_the_viewing_and_prepares_a_public_note(self, setup):
        editor, path = setup

        outcome = editor.answer(editor.request_cancel(MARIO, 1), "yes")

        assert isinstance(outcome, Done)
        assert "#1" in outcome.text
        assert "mario ha annullato la visione #1" in outcome.announcement
        assert "Heat - La sfida (1995)" in outcome.announcement
        assert viewings(path) == [("franco", "Heat - La sfida")]

    def test_the_note_names_the_owner_when_a_superuser_cancels(self, setup):
        editor, path = setup

        outcome = editor.answer(editor.request_cancel(SUPER, 2), "yes")

        assert "capo ha annullato la visione #2" in outcome.announcement
        assert "di franco" in outcome.announcement
        assert viewings(path) == [("mario", "Heat - La sfida")]

    def test_declining_changes_nothing(self, setup):
        editor, path = setup

        outcome = editor.answer(editor.request_cancel(MARIO, 1), "no")

        assert isinstance(outcome, Cancelled)
        assert len(viewings(path)) == 2

    def test_a_value_that_was_not_offered_is_rejected(self, setup):
        editor, path = setup

        outcome = editor.answer(editor.request_cancel(MARIO, 1), "forse")

        assert isinstance(outcome, Rejected)
        assert len(viewings(path)) == 2

    def test_confirming_twice_cancels_once(self, setup):
        editor, _ = setup
        ask = editor.request_cancel(MARIO, 1)
        editor.answer(ask, "yes")

        second = editor.answer(ask, "yes")

        assert isinstance(second, Rejected) and "già" in second.text


def rating_of(path, viewing_id):
    db = Database.open(path)
    try:
        return db.get_viewing(viewing_id)["rating"]
    finally:
        db.close()


class TestSetRating:
    def test_the_author_rates_a_given_viewing_and_the_note_is_public(self, setup):
        editor, path = setup

        outcome = editor.set_rating(MARIO, 4.5, 1)

        assert isinstance(outcome, Done)
        assert "#1" in outcome.text and "4,5" in outcome.text
        assert "mario ha dato 4,5 a Heat - La sfida (1995)" in outcome.announcement
        assert "#1" in outcome.announcement
        assert rating_of(path, 1) == 4.5

    def test_without_a_number_the_last_viewing_of_the_author_is_rated(self, setup):
        editor, path = setup

        outcome = editor.set_rating(FRANCO, 3)

        assert isinstance(outcome, Done) and "#2" in outcome.text
        assert rating_of(path, 2) == 3
        assert rating_of(path, 1) is None

    def test_the_last_viewing_ignores_cancelled_ones(self, setup):
        editor, path = setup
        editor.answer(editor.request_cancel(FRANCO, 2), "yes")

        outcome = editor.set_rating(FRANCO, 3)

        assert isinstance(outcome, Rejected) and "nessuna visione" in outcome.text.lower()

    def test_a_previous_rating_is_shown_in_the_note(self, setup):
        editor, _ = setup
        editor.set_rating(MARIO, 2, 1)

        outcome = editor.set_rating(MARIO, 4, 1)

        assert "da 2 a 4" in outcome.announcement

    @pytest.mark.parametrize("rating", [0, 0.3, 5.5, 4.25, -1])
    def test_a_rating_outside_half_points_from_half_to_five_is_rejected(self, setup, rating):
        editor, path = setup

        outcome = editor.set_rating(MARIO, rating, 1)

        assert isinstance(outcome, Rejected)
        assert rating_of(path, 1) is None

    def test_other_peoples_viewings_cannot_be_rated(self, setup):
        editor, path = setup

        outcome = editor.set_rating(MARIO, 4, 2)

        assert isinstance(outcome, Rejected) and "tue" in outcome.text
        assert rating_of(path, 2) is None

    def test_a_superuser_can_rate_anyones_viewing_and_the_note_names_the_owner(self, setup):
        editor, path = setup

        outcome = editor.set_rating(SUPER, 5, 2)

        assert isinstance(outcome, Done)
        assert "capo ha dato 5 a Heat - La sfida (1995)" in outcome.announcement and "di franco" in outcome.announcement
        assert rating_of(path, 2) == 5

    def test_unknown_user_missing_and_cancelled_viewings_are_reported(self, setup):
        editor, _ = setup
        editor.answer(editor.request_cancel(MARIO, 1), "yes")

        assert "users.yaml" in editor.set_rating(STRANGER, 4, 1).text
        assert "99" in editor.set_rating(MARIO, 4, 99).text
        assert "già" in editor.set_rating(MARIO, 4, 1).text


TODAY = date(2026, 7, 10)


def candidate(tmdb_id, year, title):
    return Candidate(tmdb_id, None, title, title, year, 1.0)


class FakeClient:
    def __init__(self, found, search_error=None):
        self.found, self.search_error = found, search_error
        self.details_calls = []

    def search(self, title):
        if self.search_error:
            raise self.search_error
        return self.found.get(title, [])

    def details(self, tmdb_id):
        self.details_calls.append(tmdb_id)
        return MovieDetails(tmdb_id, f"Film {tmdb_id}", f"Film {tmdb_id}", 1999, 100, (), ())


FOUND = {
    "Il sesto senso": [candidate(745, 1999, "Il sesto senso")],
    "Reunion": [candidate(10, 2024, "Reunion"), candidate(11, 2024, "Reunion")],
}


@pytest.fixture
def edit_setup(setup):
    _, path = setup
    client = FakeClient(FOUND)
    return ViewingEditor(path, frozenset({SUPER}), client, today=lambda: TODAY), path, client


def stored(path, viewing_id):
    db = Database.open(path)
    try:
        return db.get_viewing(viewing_id)
    finally:
        db.close()


class TestRequestEdit:
    def test_something_to_change_is_required(self, edit_setup):
        editor, _, _ = edit_setup

        outcome = editor.request_edit(MARIO, 1)

        assert isinstance(outcome, Rejected) and "data" in outcome.text and "film" in outcome.text

    def test_a_new_date_is_confirmed_showing_before_and_after(self, edit_setup):
        editor, path, _ = edit_setup

        ask = editor.request_edit(MARIO, 1, date_text="06/07/2026")

        assert isinstance(ask, Ask) and ask.kind == "edit"
        assert "#1" in ask.text and "05/07/2026" in ask.text and "06/07/2026" in ask.text
        assert [o.value for o in ask.options] == ["yes", "no"]
        assert stored(path, 1)["watched_on"] == "2026-07-05"

    @pytest.mark.parametrize("text", ["abc", "31/02/2026", "2026-07-06", "06/07/26"])
    def test_a_malformed_date_is_rejected(self, edit_setup, text):
        editor, _, _ = edit_setup

        outcome = editor.request_edit(MARIO, 1, date_text=text)

        assert isinstance(outcome, Rejected) and "gg/mm/aaaa" in outcome.text

    def test_a_future_date_is_rejected(self, edit_setup):
        editor, _, _ = edit_setup

        assert isinstance(editor.request_edit(MARIO, 1, date_text="11/07/2026"), Rejected)
        assert isinstance(editor.request_edit(MARIO, 1, date_text="10/07/2026"), Ask)

    def test_a_recognised_film_is_confirmed_showing_before_and_after(self, edit_setup):
        editor, _, _ = edit_setup

        ask = editor.request_edit(MARIO, 1, film_text="Il sesto senso (1999)")

        assert isinstance(ask, Ask) and ask.kind == "edit"
        assert "Heat - La sfida (1995)" in ask.text and "Il sesto senso (1999)" in ask.text

    def test_a_film_without_year_is_rejected(self, edit_setup):
        editor, _, _ = edit_setup

        outcome = editor.request_edit(MARIO, 1, film_text="Il sesto senso")

        assert isinstance(outcome, Rejected) and "Titolo (anno)" in outcome.text

    def test_an_unknown_film_is_rejected(self, edit_setup):
        editor, _, _ = edit_setup

        outcome = editor.request_edit(MARIO, 1, film_text="Nulla (2001)")

        assert isinstance(outcome, Rejected) and "Nulla (2001)" in outcome.text

    def test_an_ambiguous_film_offers_a_choice_then_the_confirmation(self, edit_setup):
        editor, path, _ = edit_setup

        ask = editor.request_edit(MARIO, 1, film_text="Reunion (2024)", date_text="06/07/2026")
        assert isinstance(ask, Ask) and ask.kind == "edit_film"
        assert [o.value for o in ask.options] == ["10", "11", "none"]

        confirm = editor.answer(ask, "11")

        assert isinstance(confirm, Ask) and confirm.kind == "edit"
        assert "Reunion (2024)" in confirm.text and "06/07/2026" in confirm.text
        assert stored(path, 1)["title"] == "Heat - La sfida"

    def test_declining_every_candidate_changes_nothing(self, edit_setup):
        editor, path, _ = edit_setup
        ask = editor.request_edit(MARIO, 1, film_text="Reunion (2024)")

        outcome = editor.answer(ask, "none")

        assert isinstance(outcome, Cancelled)
        assert stored(path, 1)["title"] == "Heat - La sfida"

    def test_the_same_date_is_not_a_change(self, edit_setup):
        editor, _, _ = edit_setup

        outcome = editor.request_edit(MARIO, 1, date_text="05/07/2026")

        assert isinstance(outcome, Rejected) and "non cambia" in outcome.text

    def test_a_result_equal_to_another_viewing_of_the_same_user_is_rejected(self, edit_setup):
        editor, path, _ = edit_setup
        db = Database.open(path)
        db.add_viewing(
            user_id=db.user_id_by_whatsapp("Mario Rossi"), tmdb_id=1, watched_on=date(2026, 7, 6),
            watched_on_source="body", rating=None, sent_at=datetime(2026, 7, 7), source_ref="r9",
        )
        db.commit()
        db.close()

        outcome = editor.request_edit(MARIO, 1, date_text="06/07/2026")

        assert isinstance(outcome, Rejected) and "già" in outcome.text

    def test_other_peoples_viewings_cannot_be_edited_but_a_superuser_can(self, edit_setup):
        editor, _, _ = edit_setup

        denied = editor.request_edit(MARIO, 2, date_text="06/07/2026")
        allowed = editor.request_edit(SUPER, 2, date_text="06/07/2026")

        assert isinstance(denied, Rejected) and "tue" in denied.text
        assert isinstance(allowed, Ask) and "di franco" in allowed.text

    def test_unknown_user_missing_and_cancelled_viewings_are_reported(self, edit_setup):
        editor, _, _ = edit_setup
        editor.answer(editor.request_cancel(MARIO, 1), "yes")

        assert "users.yaml" in editor.request_edit(STRANGER, 1, date_text="06/07/2026").text
        assert "99" in editor.request_edit(MARIO, 99, date_text="06/07/2026").text
        assert "già" in editor.request_edit(MARIO, 1, date_text="06/07/2026").text

    def test_changing_the_film_needs_tmdb(self, setup):
        _, path = setup
        editor = ViewingEditor(path, frozenset({SUPER}), None, today=lambda: TODAY)

        outcome = editor.request_edit(MARIO, 1, film_text="Il sesto senso (1999)")

        assert isinstance(outcome, Rejected) and "TMDB" in outcome.text
        assert isinstance(editor.request_edit(MARIO, 1, date_text="06/07/2026"), Ask)

    def test_a_tmdb_failure_is_reported(self, setup):
        _, path = setup
        editor = ViewingEditor(path, frozenset(), FakeClient({}, TmdbError("giù")), today=lambda: TODAY)

        outcome = editor.request_edit(MARIO, 1, film_text="Il sesto senso (1999)")

        assert isinstance(outcome, Rejected) and "TMDB" in outcome.text


class TestAnswerEdit:
    def test_confirming_changes_date_and_film_keeping_the_rating(self, edit_setup):
        editor, path, client = edit_setup
        editor.set_rating(MARIO, 4, 1)
        ask = editor.request_edit(MARIO, 1, film_text="Il sesto senso (1999)", date_text="06/07/2026")

        outcome = editor.answer(ask, "yes")

        assert isinstance(outcome, Done) and "#1" in outcome.text
        assert "mario ha modificato la visione #1" in outcome.announcement
        assert "Heat - La sfida (1995)" in outcome.announcement and "Film 745 (1999)" in outcome.announcement
        assert "05/07/2026" in outcome.announcement and "06/07/2026" in outcome.announcement
        viewing = stored(path, 1)
        assert (viewing["tmdb_id"], viewing["watched_on"], viewing["rating"]) == (745, "2026-07-06", 4)
        assert client.details_calls == [745]

    def test_an_edited_date_counts_as_written_by_hand(self, edit_setup):
        editor, path, _ = edit_setup

        editor.answer(editor.request_edit(MARIO, 1, date_text="06/07/2026"), "yes")

        db = Database.open(path)
        try:
            row = db.query("SELECT watched_on_source FROM viewing WHERE id = 1")[0]
        finally:
            db.close()
        assert row["watched_on_source"] == "body"

    def test_the_note_names_the_owner_when_a_superuser_edits(self, edit_setup):
        editor, _, _ = edit_setup

        outcome = editor.answer(editor.request_edit(SUPER, 2, date_text="06/07/2026"), "yes")

        assert "capo ha modificato la visione #2" in outcome.announcement and "di franco" in outcome.announcement

    def test_declining_changes_nothing(self, edit_setup):
        editor, path, _ = edit_setup

        outcome = editor.answer(editor.request_edit(MARIO, 1, date_text="06/07/2026"), "no")

        assert isinstance(outcome, Cancelled)
        assert stored(path, 1)["watched_on"] == "2026-07-05"

    def test_confirming_twice_changes_once(self, edit_setup):
        editor, _, _ = edit_setup
        ask = editor.request_edit(MARIO, 1, date_text="06/07/2026")
        editor.answer(ask, "yes")

        second = editor.answer(ask, "yes")

        assert isinstance(second, Rejected) and "non cambia" in second.text

    def test_a_viewing_cancelled_after_the_question_is_not_edited(self, edit_setup):
        editor, path, _ = edit_setup
        ask = editor.request_edit(MARIO, 1, date_text="06/07/2026")
        editor.answer(editor.request_cancel(MARIO, 1), "yes")

        outcome = editor.answer(ask, "yes")

        assert isinstance(outcome, Rejected) and "già" in outcome.text

    def test_a_duplicate_created_after_the_question_is_rejected(self, edit_setup):
        editor, path, _ = edit_setup
        ask = editor.request_edit(MARIO, 1, date_text="06/07/2026")
        db = Database.open(path)
        db.add_viewing(
            user_id=db.user_id_by_whatsapp("Mario Rossi"), tmdb_id=1, watched_on=date(2026, 7, 6),
            watched_on_source="body", rating=None, sent_at=datetime(2026, 7, 7), source_ref="r9",
        )
        db.commit()
        db.close()

        outcome = editor.answer(ask, "yes")

        assert isinstance(outcome, Rejected) and "già" in outcome.text
        assert stored(path, 1)["watched_on"] == "2026-07-05"
