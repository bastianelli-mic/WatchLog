from datetime import date, datetime
from pathlib import Path

import pytest

from watchlog.parser import parse_export

SAMPLE = Path(__file__).parent / "fixtures" / "sample_chat.txt"
FALLBACK_REASON = "data non valida, usata la data di invio"


def one(line: str):
    """Parsa una sola riga d'export e restituisce il risultato."""
    return parse_export(line)


def header(payload: str, sent: str = "06/07/26, 00:45", author: str = "Mario Rossi") -> str:
    return f"{sent} - {author}: {payload}"


class TestSampleExport:
    def test_every_message_in_the_sample_becomes_an_entry(self):
        result = parse_export(SAMPLE.read_text(encoding="utf-8"))

        assert len(result.entries) == 62
        assert result.anomalies == []

    def test_first_entry_carries_author_both_dates_and_title(self):
        first = parse_export(SAMPLE.read_text(encoding="utf-8")).entries[0]

        assert first.author == "Mario Rossi"
        assert first.sent_at == datetime(2026, 7, 6, 0, 45)
        assert first.watched_on == date(2026, 7, 5)
        assert first.watched_on_source == "body"
        assert first.title == "Maledetto il giorno che t'ho incontrato"
        assert first.year == 1992
        assert first.rating is None
        assert first.edited is False


class TestWatchedOn:
    def test_body_date_wins_over_sent_date(self):
        entry = one(header("05/07/2026 - Heat (1995)", sent="06/07/26, 00:45")).entries[0]

        assert entry.watched_on == date(2026, 7, 5)
        assert entry.watched_on_source == "body"

    def test_single_digit_day_and_month_are_accepted(self):
        entry = one(header("16/8/2026 - Heat (1995)")).entries[0]

        assert entry.watched_on == date(2026, 8, 16)

    def test_missing_body_date_falls_back_to_sent_date(self):
        entry = one(header("Heat (1995)", sent="12/08/26, 14:00")).entries[0]

        assert entry.watched_on == date(2026, 8, 12)
        assert entry.watched_on_source == "sent_at"
        assert entry.title == "Heat"

    def test_impossible_body_date_falls_back_to_sent_date_and_is_reported(self):
        result = one(header("31/02/2026 - Heat (1995)", sent="12/08/26, 14:00"))

        entry = result.entries[0]
        assert (entry.title, entry.watched_on, entry.watched_on_source) == ("Heat", date(2026, 8, 12), "sent_at")
        assert [a.reason for a in result.anomalies] == [FALLBACK_REASON]


class TestTitle:
    def test_dash_inside_the_title_is_kept(self):
        entry = one(header("02/08/2026 - Fast & Furious 9 - The Fast Saga (2021)")).entries[0]

        assert entry.title == "Fast & Furious 9 - The Fast Saga"
        assert entry.year == 2021

    def test_parentheses_inside_the_title_are_kept(self):
        entry = one(header("02/08/2026 - Mission: Impossible (Dead Reckoning) (2023)")).entries[0]

        assert entry.title == "Mission: Impossible (Dead Reckoning)"
        assert entry.year == 2023

    def test_title_split_over_two_lines_is_rejoined(self):
        text = header("20/08/2026 - Good Fortune") + "\n(2025)\n"

        entry = parse_export(text).entries[0]

        assert entry.title == "Good Fortune"
        assert entry.year == 2025

    def test_edited_marker_is_removed_and_flagged(self):
        entry = one(
            header("28/08/2026 - Spider Man - Brand new day (2026) <Questo messaggio è stato modificato>")
        ).entries[0]

        assert entry.title == "Spider Man - Brand new day"
        assert entry.edited is True


class TestRating:
    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [("[3.5]", 3.5), ("[4,5]", 4.5), ("[5]", 5.0), ("[0.5]", 0.5)],
    )
    def test_valid_rating_suffix(self, suffix, expected):
        entry = one(header(f"05/07/2026 - Heat (1995) {suffix}")).entries[0]

        assert entry.rating == expected

    @pytest.mark.parametrize("suffix", ["[6]", "[0]", "[3.3]", "[abc]", "[]"])
    def test_invalid_rating_is_an_anomaly(self, suffix):
        result = one(header(f"05/07/2026 - Heat (1995) {suffix}"))

        assert result.entries == []
        assert [a.reason for a in result.anomalies] == ["voto non valido"]


class TestNonFilmLines:
    def test_chat_chatter_is_an_anomaly(self):
        result = one(header("ciao a tutti"))

        assert result.entries == []
        assert len(result.anomalies) == 1
        assert result.anomalies[0].author == "Mario Rossi"
        assert result.anomalies[0].raw == "ciao a tutti"

    def test_system_lines_without_author_are_ignored(self):
        text = (
            "05/07/26, 10:00 - I messaggi e le chiamate sono crittografati end-to-end.\n"
            "05/07/26, 10:01 - Mario Rossi ha aggiunto Franco Rossi\n"
            + header("05/07/2026 - Heat (1995)", sent="05/07/26, 10:02")
        )

        result = parse_export(text)

        assert len(result.entries) == 1
        assert result.anomalies == []

    def test_anomaly_reports_the_line_number_of_the_message(self):
        text = header("05/07/2026 - Heat (1995)") + "\n" + header("boh", sent="06/07/26, 01:00")

        assert parse_export(text).anomalies[0].line_no == 2


class TestEncoding:
    def test_bom_and_left_to_right_marks_are_ignored(self):
        text = "﻿" + header("‎05/07/2026 - Heat (1995)")

        entry = parse_export(text).entries[0]

        assert entry.title == "Heat"
        assert entry.watched_on == date(2026, 7, 5)

    def test_four_digit_sent_year_is_accepted(self):
        entry = one(header("Heat (1995)", sent="12/08/2026, 14:00")).entries[0]

        assert entry.sent_at == datetime(2026, 8, 12, 14, 0)


def ios_header(payload: str, sent: str = "06/07/26, 00:45:12", author: str = "Mario Rossi") -> str:
    return f"[{sent}] {author}: {payload}"


class TestIosFormat:
    def test_ios_line_is_parsed_like_android_and_keeps_seconds(self):
        entry = one(ios_header("05/07/2026 - Heat (1995)")).entries[0]

        assert entry.author == "Mario Rossi"
        assert entry.sent_at == datetime(2026, 7, 6, 0, 45, 12)
        assert entry.watched_on == date(2026, 7, 5)
        assert entry.title == "Heat"

    def test_ios_lines_start_with_an_invisible_mark(self):
        entry = one("‎" + ios_header("05/07/2026 - Heat (1995)")).entries[0]

        assert entry.title == "Heat"

    def test_ios_four_digit_year_and_date_fallback(self):
        entry = one(ios_header("Heat (1995)", sent="12/08/2026, 14:00:30")).entries[0]

        assert entry.watched_on == date(2026, 8, 12)
        assert entry.watched_on_source == "sent_at"

    def test_ios_title_split_over_two_lines_is_rejoined(self):
        text = ios_header("20/08/2026 - Good Fortune") + "\n(2025)\n"

        entry = parse_export(text).entries[0]

        assert (entry.title, entry.year) == ("Good Fortune", 2025)

    def test_ios_system_line_without_author_is_ignored(self):
        text = (
            "[05/07/26, 10:01:00] Mario Rossi ha aggiunto Franco Rossi\n"
            + ios_header("05/07/2026 - Heat (1995)", sent="05/07/26, 10:02:00")
        )

        result = parse_export(text)

        assert len(result.entries) == 1
        assert result.anomalies == []

    def test_android_and_ios_lines_can_be_mixed(self):
        text = header("05/07/2026 - Heat (1995)") + "\n" + ios_header("06/07/2026 - Ronin (1998)")

        assert [e.title for e in parse_export(text).entries] == ["Heat", "Ronin"]


class TestParseFilmText:
    def test_title_and_year_from_free_text(self):
        from watchlog.parser import parse_film_text

        assert parse_film_text("Roofman (2025)") == ("Roofman", 2025)
        assert parse_film_text("Mission: Impossible (Dead Reckoning) (2023)") == (
            "Mission: Impossible (Dead Reckoning)",
            2023,
        )

    def test_text_without_year_is_rejected(self):
        from watchlog.parser import parse_film_text

        assert parse_film_text("Roofman") is None


class TestDeletedMessages:
    @pytest.mark.parametrize(
        "text",
        [
            "Hai eliminato questo messaggio.",
            "Questo messaggio è stato eliminato.",
            "You deleted this message",
            "This message was deleted",
        ],
    )
    def test_deleted_message_placeholders_are_ignored_not_anomalies(self, text):
        result = one(header(text))

        assert result.entries == []
        assert result.anomalies == []


class TestMalformedBodyDate:
    @pytest.mark.parametrize(
        ("payload", "title", "year"),
        [
            ("0000 - Dune parte 1 (2021)", "Dune parte 1", 2021),
            ("2203/2026 - Il nome della rosa (1986)", "Il nome della rosa", 1986),
            ("05/07/26 - Heat (1995)", "Heat", 1995),
            ("05/07 - Heat (1995)", "Heat", 1995),
        ],
    )
    def test_date_like_prefix_that_is_not_a_date_falls_back_to_sent_date_and_is_reported(self, payload, title, year):
        result = one(header(payload, sent="12/08/26, 14:00"))

        entry = result.entries[0]
        assert (entry.title, entry.year) == (title, year)
        assert (entry.watched_on, entry.watched_on_source) == (date(2026, 8, 12), "sent_at")
        assert [a.reason for a in result.anomalies] == [FALLBACK_REASON]

    def test_malformed_date_on_a_line_that_is_not_a_film_is_only_a_film_anomaly(self):
        result = one(header("0000 - boh"))

        assert result.entries == []
        assert [a.reason for a in result.anomalies] == ["non è una visualizzazione"]

    @pytest.mark.parametrize(
        ("payload", "title"),
        [
            ("2001 - Odissea nello spazio (1968)", "2001 - Odissea nello spazio"),
            ("1917 (2019)", "1917"),
        ],
    )
    def test_titles_that_start_with_a_number_are_still_films(self, payload, title):
        entry = one(header(payload)).entries[0]

        assert entry.title == title


class TestLineNumber:
    def test_entry_remembers_the_line_of_its_message(self):
        text = (
            header("05/07/2026 - Heat (1995)")
            + "\n"
            + header("06/07/2026 - Good Fortune", sent="07/07/26, 10:00")
            + "\n(2025)\n"
            + header("08/07/2026 - Ronin (1998)", sent="09/07/26, 10:00")
        )

        assert [e.line_no for e in parse_export(text).entries] == [1, 2, 4]
