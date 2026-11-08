from datetime import datetime

import pytest

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.live import Ask, Cancelled, LiveService, Recorded, Rejected, Unrecognized
from watchlog.tmdb import Candidate, MovieDetails, TmdbError

SENT = datetime(2026, 7, 6, 0, 45)
MARIO, FRANCO = "111", "222"


def candidate(tmdb_id, year, title):
    return Candidate(tmdb_id, None, title, title, year, 1.0)


def details(tmdb_id, title, year):
    return MovieDetails(tmdb_id, title, title, year, 120, ((18, "Drammatico"),), ((1, "Regista"),))


class FakeClient:
    def __init__(self, found, info, search_error=None, details_error=None):
        self.found, self.info = found, info
        self.search_error, self.details_error = search_error, details_error
        self.search_calls, self.details_calls = [], []

    def search(self, title):
        if self.search_error:
            raise self.search_error
        self.search_calls.append(title)
        return self.found.get(title, [])

    def details(self, tmdb_id):
        if self.details_error:
            raise self.details_error
        self.details_calls.append(tmdb_id)
        return self.info[tmdb_id]


HEAT = {"Heat": [candidate(949, 1995, "Heat")]}
INFO = {949: details(949, "Heat", 1995), 2: details(2, "Heat", 1995), 745: details(745, "Il sesto senso", 1999)}


def make(tmp_path, found=HEAT, **errors):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([UserConfig("mario", "Mario Rossi", MARIO), UserConfig("franco", "Franco Rossi", FRANCO)])
    db.commit()
    db.close()
    client = FakeClient(found, INFO, **errors)
    return LiveService(path, client), path, client


def viewings(path):
    db = Database.open(path)
    try:
        return db.list_viewings()
    finally:
        db.close()


def say(service, text="05/07/2026 - Heat (1995)", discord_id=MARIO, message_id="m1"):
    return service.handle(discord_id, text, SENT, message_id)


class TestRecording:
    def test_a_recognised_film_is_recorded_with_the_body_date(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service)

        assert isinstance(outcome, Recorded)
        assert "Heat (1995)" in outcome.text and "05/07/2026" in outcome.text
        assert [(v["user"], v["watched_on"], v["rating"]) for v in viewings(path)] == [("mario", "2026-07-05", None)]

    def test_rating_is_saved_and_shown(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service, "05/07/2026 - Heat (1995) [4.5]")

        assert "voto 4,5" in outcome.text
        assert viewings(path)[0]["rating"] == 4.5

    def test_missing_date_uses_the_sent_date_and_says_so(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service, "Heat (1995)")

        assert "06/07/2026" in outcome.text and "data di invio" in outcome.text
        assert viewings(path)[0]["watched_on"] == "2026-07-06"

    def test_wrong_date_uses_the_sent_date_and_says_it_was_not_valid(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service, "0000 - Heat (1995)")

        assert isinstance(outcome, Recorded)
        assert "non era valida" in outcome.text
        assert viewings(path)[0]["watched_on"] == "2026-07-06"

    def test_movie_details_are_fetched_once_and_stored(self, tmp_path):
        service, _, client = make(tmp_path)

        say(service, message_id="m1")
        say(service, "06/07/2026 - Heat (1995)", message_id="m2")

        assert client.details_calls == [949]

    def test_same_film_on_another_day_is_a_rewatch_without_questions(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")

        outcome = say(service, "06/07/2026 - Heat (1995)", message_id="m2")

        assert isinstance(outcome, Recorded)
        assert len(viewings(path)) == 2

    def test_same_film_same_day_by_another_user_is_not_a_duplicate(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")

        outcome = say(service, discord_id=FRANCO, message_id="m2")

        assert isinstance(outcome, Recorded)
        assert sorted(v["user"] for v in viewings(path)) == ["franco", "mario"]


class TestRejections:
    def test_unknown_discord_user_is_told_how_to_be_added(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service, discord_id="999")

        assert isinstance(outcome, Rejected)
        assert "users.yaml" in outcome.text
        assert viewings(path) == []

    def test_chatter_is_not_recognised_and_saves_nothing(self, tmp_path):
        service, path, _ = make(tmp_path)

        assert isinstance(say(service, "ciao a tutti"), Unrecognized)
        assert viewings(path) == []

    def test_invalid_rating_explains_the_valid_range(self, tmp_path):
        service, path, _ = make(tmp_path)

        outcome = say(service, "05/07/2026 - Heat (1995) [7]")

        assert isinstance(outcome, Rejected)
        assert "0,5" in outcome.text and "5" in outcome.text
        assert viewings(path) == []

    def test_film_not_found_asks_to_check_the_title(self, tmp_path):
        service, path, _ = make(tmp_path, found={})

        outcome = say(service)

        assert isinstance(outcome, Rejected)
        assert "Heat (1995)" in outcome.text
        assert viewings(path) == []

    def test_tmdb_down_during_search_is_a_friendly_rejection(self, tmp_path):
        service, path, _ = make(tmp_path, search_error=TmdbError("rete"))

        outcome = say(service)

        assert isinstance(outcome, Rejected)
        assert "TMDB" in outcome.text
        assert viewings(path) == []

    def test_tmdb_down_while_fetching_details_saves_nothing(self, tmp_path):
        service, path, _ = make(tmp_path, details_error=TmdbError("rete"))

        outcome = say(service)

        assert isinstance(outcome, Rejected)
        assert viewings(path) == []

    def test_the_same_message_is_not_recorded_twice(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")

        outcome = say(service, message_id="m1")

        assert isinstance(outcome, Rejected)
        assert "già" in outcome.text
        assert len(viewings(path)) == 1


class TestChoosingTheFilm:
    TWO = {"Heat": [candidate(949, 1995, "Heat"), candidate(2, 1995, "Heat")]}

    def test_ambiguous_film_offers_candidates_and_none_of_them(self, tmp_path):
        service, path, _ = make(tmp_path, found=self.TWO)

        outcome = say(service)

        assert isinstance(outcome, Ask) and outcome.kind == "film"
        assert [o.value for o in outcome.options] == ["949", "2", "none"]
        assert viewings(path) == []

    def test_choosing_a_candidate_records_that_film(self, tmp_path):
        service, path, _ = make(tmp_path, found=self.TWO)
        ask = say(service)

        outcome = service.answer(ask, "2")

        assert isinstance(outcome, Recorded)
        assert viewings(path)[0]["tmdb_id"] == 2

    def test_a_single_unsure_candidate_is_offered_for_confirmation(self, tmp_path):
        found = {"Il Sesto Senso": [candidate(745, 1999, "The Sixth Sense - Il sesto senso")]}
        service, path, _ = make(tmp_path, found=found)

        ask = say(service, "05/07/2026 - Il Sesto Senso (1999)")

        assert isinstance(ask, Ask)
        assert [o.value for o in ask.options] == ["745", "none"]
        assert "Intendevi" in ask.text
        assert isinstance(service.answer(ask, "745"), Recorded)
        assert len(viewings(path)) == 1

    def test_none_of_them_cancels_without_saving(self, tmp_path):
        service, path, _ = make(tmp_path, found=self.TWO)
        ask = say(service)

        assert isinstance(service.answer(ask, "none"), Cancelled)
        assert viewings(path) == []

    def test_a_value_that_was_not_offered_is_rejected(self, tmp_path):
        service, path, _ = make(tmp_path, found=self.TWO)
        ask = say(service)

        assert isinstance(service.answer(ask, "12345"), Rejected)
        assert viewings(path) == []

    def test_answering_twice_does_not_record_twice(self, tmp_path):
        service, path, _ = make(tmp_path, found=self.TWO)
        ask = say(service)
        service.answer(ask, "949")

        second = service.answer(ask, "949")

        assert isinstance(second, Rejected)
        assert len(viewings(path)) == 1


class TestDuplicates:
    def test_same_film_same_day_asks_for_confirmation(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")

        ask = say(service, message_id="m2")

        assert isinstance(ask, Ask) and ask.kind == "duplicate"
        assert [o.value for o in ask.options] == ["yes", "no"]
        assert "05/07/2026" in ask.text
        assert len(viewings(path)) == 1

    def test_confirming_records_it_again(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")
        ask = say(service, message_id="m2")

        outcome = service.answer(ask, "yes")

        assert isinstance(outcome, Recorded)
        assert len(viewings(path)) == 2

    def test_declining_cancels(self, tmp_path):
        service, path, _ = make(tmp_path)
        say(service, message_id="m1")
        ask = say(service, message_id="m2")

        assert isinstance(service.answer(ask, "no"), Cancelled)
        assert len(viewings(path)) == 1

    def test_choosing_a_candidate_that_is_a_duplicate_asks_again(self, tmp_path):
        found = {"Heat": [candidate(949, 1995, "Heat"), candidate(2, 1995, "Heat")]}
        service, path, _ = make(tmp_path, found=found)
        service.answer(say(service, message_id="m1"), "949")

        follow_up = service.answer(say(service, message_id="m2"), "949")

        assert isinstance(follow_up, Ask) and follow_up.kind == "duplicate"
        assert len(viewings(path)) == 1
