from datetime import date, datetime

from watchlog.config import UserConfig
from watchlog.db import Database
from watchlog.report import period_text, render_stats
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

        assert blocks[0].splitlines()[0] == "Statistiche: mario (dal 2026-07-01 al 2026-07-31)"


class TestPeriodText:
    def test_forms(self):
        assert period_text(None, None) == ""
        assert period_text(date(2026, 7, 1), None) == " (dal 2026-07-01)"
        assert period_text(None, date(2026, 7, 31)) == " (fino al 2026-07-31)"
        assert period_text(date(2026, 7, 1), date(2026, 7, 31)) == " (dal 2026-07-01 al 2026-07-31)"
