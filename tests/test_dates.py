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
