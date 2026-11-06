import pytest

from watchlog.resolver import normalize, resolve
from watchlog.tmdb import Candidate


def film(tmdb_id, year, *, it=None, en=None, original=None, popularity=1.0):
    return Candidate(
        tmdb_id=tmdb_id,
        title_it=it,
        title_en=en,
        original_title=original,
        year=year,
        popularity=popularity,
    )


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Spider-Man: Brand New Day", "spider man brand new day"),
            ("Spider Man - Brand new day", "spider man brand new day"),
            ("The Menù", "the menu"),
            ("  Ocean's   Eleven  ", "ocean s eleven"),
            ("L'enigma del ciondolo", "l enigma del ciondolo"),
        ],
    )
    def test_case_accents_and_punctuation_are_flattened(self, raw, expected):
        assert normalize(raw) == expected


class TestResolved:
    def test_title_differing_only_by_punctuation_and_case(self):
        result = resolve(
            "Spider Man - Brand new day",
            2026,
            [film(1, 2026, en="Spider-Man: Brand New Day")],
        )

        assert result.status == "resolved"
        assert result.best.candidate.tmdb_id == 1

    def test_typo_in_title_still_resolves(self):
        result = resolve("In the Lost Landa", 2025, [film(1, 2025, en="In the Lost Lands")])

        assert result.status == "resolved"

    def test_accent_difference_resolves(self):
        result = resolve("The Menù", 2022, [film(1, 2022, en="The Menu")])

        assert result.status == "resolved"

    def test_year_off_by_one_resolves(self):
        result = resolve("Roofman", 2026, [film(1, 2025, en="Roofman")])

        assert result.status == "resolved"

    def test_italian_title_is_matched(self):
        result = resolve(
            "Avatar - Fuoco e cenere",
            2025,
            [film(1, 2025, it="Avatar - Fuoco e cenere", en="Avatar: Fire and Ash")],
        )

        assert result.status == "resolved"

    def test_original_title_is_matched(self):
        result = resolve("Il favoloso mondo", 2001, [film(1, 2001, it="Altro", original="Il favoloso mondo")])

        assert result.status == "resolved"

    def test_homonyms_far_in_time_are_discarded_by_year(self):
        result = resolve(
            "Anaconda",
            2026,
            [
                film(1, 2025, en="Anaconda"),
                film(2, 1997, en="Anaconda"),
                film(3, 2009, en="Anacondas: Trail of Blood"),
            ],
        )

        assert result.status == "resolved"
        assert result.best.candidate.tmdb_id == 1

    def test_exact_year_beats_adjacent_year_of_a_similar_title(self):
        result = resolve(
            "Heat",
            1995,
            [film(1, 1995, en="Heat"), film(2, 1996, en="Heats")],
        )

        assert result.status == "resolved"
        assert result.best.candidate.tmdb_id == 1


class TestHomonymsInAdjacentYears:
    def test_exact_year_wins_over_an_equally_titled_film_one_year_away(self):
        result = resolve(
            "Contagion",
            2011,
            [film(1, 2011, en="Contagion"), film(2, 2010, en="Contagion")],
        )

        assert result.status == "resolved"
        assert result.best.candidate.tmdb_id == 1

    def test_homonyms_equally_far_from_the_year_stay_ambiguous(self):
        result = resolve("Roofman", 2026, [film(1, 2025, en="Roofman"), film(2, 2027, en="Roofman")])

        assert result.status == "ambiguous"


class TestAmbiguous:
    def test_two_equally_good_candidates(self):
        result = resolve(
            "Roofman",
            2025,
            [film(1, 2025, en="Roofman"), film(2, 2025, en="Roofman")],
        )

        assert result.status == "ambiguous"
        assert {s.candidate.tmdb_id for s in result.scored} == {1, 2}

    def test_candidates_are_ordered_best_first(self):
        result = resolve(
            "Roofman",
            2025,
            [film(1, 2024, en="Roofman"), film(2, 2025, en="Roofman")],
        )

        assert result.scored[0].candidate.tmdb_id == 2


class TestNotFound:
    def test_no_candidates(self):
        assert resolve("Heat", 1995, []).status == "not_found"

    def test_year_more_than_one_apart(self):
        assert resolve("Heat", 1995, [film(1, 1997, en="Heat")]).status == "not_found"

    def test_title_too_different(self):
        assert resolve("Heat", 1995, [film(1, 1995, en="Completely Unrelated")]).status == "not_found"

    def test_candidate_without_release_year_is_ignored(self):
        assert resolve("Heat", 1995, [film(1, None, en="Heat")]).status == "not_found"
