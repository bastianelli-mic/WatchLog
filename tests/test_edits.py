from datetime import date, datetime

import pytest

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.edits import Done, ViewingEditor
from watchlog.live import Ask, Cancelled, Rejected
from watchlog.tmdb import MovieDetails

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
