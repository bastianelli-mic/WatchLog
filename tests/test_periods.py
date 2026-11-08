from datetime import date

import pytest

from watchlog.periods import period_range


class TestPeriodRange:
    def test_today_is_a_single_day(self):
        assert period_range("oggi", date(2026, 11, 4)) == (date(2026, 11, 4), date(2026, 11, 4))

    @pytest.mark.parametrize("day", [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 8)])
    def test_week_runs_from_monday_to_sunday_whatever_the_day(self, day):
        assert period_range("settimana", day) == (date(2026, 11, 2), date(2026, 11, 8))

    def test_week_can_cross_a_month_boundary(self):
        assert period_range("settimana", date(2026, 7, 30)) == (date(2026, 7, 27), date(2026, 8, 2))

    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            (date(2026, 11, 15), (date(2026, 11, 1), date(2026, 11, 30))),
            (date(2026, 2, 10), (date(2026, 2, 1), date(2026, 2, 28))),
            (date(2028, 2, 10), (date(2028, 2, 1), date(2028, 2, 29))),
            (date(2026, 12, 31), (date(2026, 12, 1), date(2026, 12, 31))),
        ],
    )
    def test_month_is_the_calendar_month(self, today, expected):
        assert period_range("mese", today) == expected

    def test_year_is_the_calendar_year(self):
        assert period_range("anno", date(2026, 6, 15)) == (date(2026, 1, 1), date(2026, 12, 31))

    def test_unknown_period_is_rejected(self):
        with pytest.raises(ValueError, match="ieri"):
            period_range("ieri", date(2026, 11, 4))
