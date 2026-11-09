from datetime import date

import pytest

from watchlog.dates import format_date, format_iso, parse_date


def test_dates_are_shown_as_day_month_year():
    assert format_date(date(2026, 7, 5)) == "05/07/2026"
    assert format_iso("2026-07-05") == "05/07/2026"


@pytest.mark.parametrize("text", ["05/07/2026", " 5/7/2026 ", "05/07/2026\n"])
def test_a_day_month_year_date_is_read(text):
    assert parse_date(text) == date(2026, 7, 5)


@pytest.mark.parametrize("text", ["", "abc", "31/02/2026", "2026-07-05", "05/07/26", "05/13/2026"])
def test_anything_else_is_not_a_date(text):
    assert parse_date(text) is None


from watchlog.dates import parse_bound  # noqa: E402


class TestParseBound:
    @pytest.mark.parametrize(
        ("text", "start", "end"),
        [
            ("05/07/2026", date(2026, 7, 5), date(2026, 7, 5)),
            ("07/2026", date(2026, 7, 1), date(2026, 7, 31)),
            ("7/2026", date(2026, 7, 1), date(2026, 7, 31)),
            ("2026", date(2026, 1, 1), date(2026, 12, 31)),
            (" 2026 ", date(2026, 1, 1), date(2026, 12, 31)),
            ("02/2028", date(2028, 2, 1), date(2028, 2, 29)),
            ("02/2027", date(2027, 2, 1), date(2027, 2, 28)),
            ("12/2026", date(2026, 12, 1), date(2026, 12, 31)),
        ],
    )
    def test_a_partial_date_covers_its_whole_month_or_year(self, text, start, end):
        assert parse_bound(text, end=False) == start
        assert parse_bound(text, end=True) == end

    @pytest.mark.parametrize("text", ["", "abc", "13/2026", "00/2026", "31/02/2026", "2026-07", "26", "99999", "0000", "07/26"])
    def test_anything_else_is_not_a_bound(self, text):
        assert parse_bound(text, end=False) is None
        assert parse_bound(text, end=True) is None
