from datetime import date, datetime

from watchlog.config import UserConfig
from watchlog.db import Database
import pytest

from watchlog.report import DETAILS, period_text, render_stats
from watchlog.stats import compute_stats, group_extras
from watchlog.tmdb import MovieDetails


def seeded_db():
    db = Database.in_memory()
    db.sync_users([UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", None)])
    db.save_movie(MovieDetails(1, "Heat", "Heat", 1995, 120, ((28, "Azione"),), ((488, "Michael Mann"),)))
    for index, (user, day) in enumerate([("Mario Rossi", 5), ("Franco Rossi", 6)]):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=1,
            watched_on=date(2026, 7, day),
            watched_on_source="body",
            rating=None,
            sent_at=datetime(2026, 7, 20),
            source_ref=f"r{index}",
        )
    return db


class TestRenderStats:
    def test_first_block_has_title_and_summary_and_each_section_is_its_own_block(self):
        db = seeded_db()

        blocks = render_stats(compute_stats(db), None)

        assert blocks[0].splitlines()[0] == "Statistiche: gruppo"
        assert "visualizzazioni: 2" in blocks[0]
        assert blocks[1].startswith("Generi più visti:")
        assert all("\n\n" not in block for block in blocks)

    def test_group_extras_are_appended_as_blocks(self):
        db = seeded_db()

        blocks = render_stats(compute_stats(db), group_extras(db))

        assert any(block.startswith("Classifica utenti:") for block in blocks)

    def test_user_title_and_period(self):
        db = seeded_db()
        since, until = date(2026, 7, 1), date(2026, 7, 31)

        blocks = render_stats(compute_stats(db, user="mario", since=since, until=until), None, "mario", since, until)

        assert blocks[0].splitlines()[0] == "Statistiche: mario (dal 01/07/2026 al 31/07/2026)"


class TestDetails:
    def blocks(self, details, extras=False):
        db = seeded_db()
        return render_stats(compute_stats(db), group_extras(db) if extras else None, details=details)

    def test_base_is_a_short_summary_with_the_streak_and_nothing_else(self):
        blocks = self.blocks(("base",))

        assert len(blocks) == 1
        for expected in ("Statistiche: gruppo", "visualizzazioni: 2", "tempo totale:", "serie consecutiva più lunga:", "voto medio:"):
            assert expected in blocks[0]
        assert "durata media" not in blocks[0] and "film più lungo" not in blocks[0]

    def test_duration_has_its_own_block(self):
        blocks = self.blocks(("durata",))

        assert blocks[1].startswith("Durata:")
        for expected in ("durata media: 2 h 0 min", "film più lungo: Heat", "film più corto: Heat"):
            assert expected in blocks[1]
        assert "durata media" not in blocks[0]

    def test_tastes_time_and_rewatched_select_their_sections(self):
        titles = lambda details: [block.splitlines()[0] for block in self.blocks(details)[1:]]  # noqa: E731

        assert titles(("gusti",)) == ["Generi più visti:", "Registi più visti:", "Per decennio di uscita:"]
        assert titles(("tempo",)) == [
            "Visualizzazioni per mese:",
            "Giorni della settimana:",
            "Giorni con più film:",
            "Record di film visti:",
        ]
        assert titles(("rivisti",)) == []  # nessun film rivisto: la sezione vuota non compare
        assert titles(("gusti", "tempo"))[0] == "Generi più visti:" and "Giorni della settimana:" in titles(("gusti", "tempo"))

    def test_rankings_come_from_the_group_extras_only(self):
        with_extras = [b.splitlines()[0] for b in self.blocks(("classifiche",), extras=True)[1:]]

        assert with_extras[0] == "Classifica utenti:"
        assert len(self.blocks(("classifiche",), extras=False)) == 1

    def test_everything_is_the_complete_report_and_the_default(self):
        db = seeded_db()
        stats, extras = compute_stats(db), group_extras(db)

        complete = render_stats(stats, extras)

        assert render_stats(stats, extras, details=("tutto",)) == complete
        assert render_stats(stats, extras, details=None) == complete
        assert "durata media: 2 h 0 min" in complete[0]
        assert any(block.startswith("Classifica utenti:") for block in complete)

    def test_an_unknown_detail_is_rejected(self):
        with pytest.raises(ValueError, match="boh"):
            self.blocks(("boh",))

    def test_records_are_listed_with_their_period(self):
        block = next(b for b in self.blocks(("tempo",)) if b.startswith("Record di film visti:"))

        assert block.splitlines()[1:] == [
            "  in un giorno: 1 film (05/07/2026)",
            "  in una settimana: 1 film (dal 29/06/2026 al 05/07/2026)",
            "  in un mese: 2 film (07/2026)",
            "  in un anno: 2 film (2026)",
        ]

    def test_the_known_details(self):
        assert DETAILS == ("base", "durata", "gusti", "tempo", "rivisti", "classifiche", "tutto")


class TestPeriodText:
    def test_forms(self):
        assert period_text(None, None) == ""
        assert period_text(date(2026, 7, 1), None) == " (dal 01/07/2026)"
        assert period_text(None, date(2026, 7, 31)) == " (fino al 31/07/2026)"
        assert period_text(date(2026, 7, 1), date(2026, 7, 31)) == " (dal 01/07/2026 al 31/07/2026)"
