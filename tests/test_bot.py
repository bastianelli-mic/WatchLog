from datetime import date, datetime

import pytest

from watchlog.bot import (
    MESSAGE_LIMIT,
    cancel_channel_error,
    chunk_blocks,
    stats_reply,
    sync_users,
    user_names,
    viewings_reply,
)
from watchlog.config import ConfigError, DiscordConfig, UserConfig
from watchlog.db import Database
from watchlog.tmdb import MovieDetails

CONFIG = DiscordConfig(guild_id=1, stats_channel_id=100)
MARIO, FRANCO, STRANGER = "111", "222", "999"


def seeded_db_file(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([UserConfig("mario", "Mario Rossi", MARIO), UserConfig("franco", "Franco Rossi", FRANCO)])
    db.save_movie(MovieDetails(1, "Heat", "Heat", 1995, 120, ((28, "Azione"),), ((488, "Michael Mann"),)))
    for index, (user, day) in enumerate([("Mario Rossi", 5), ("Mario Rossi", 9), ("Franco Rossi", 6)]):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=1,
            watched_on=date(2026, 7, day),
            watched_on_source="body",
            rating=None,
            sent_at=datetime(2026, 7, 20),
            source_ref=f"r{index}",
        )
    db.commit()
    db.close()
    return path


class TestChunkBlocks:
    def test_blocks_are_packed_in_order_without_exceeding_the_limit(self):
        blocks = ["a" * 40, "b" * 40, "c" * 40]

        chunks = chunk_blocks(blocks, limit=100)

        assert chunks == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]

    def test_everything_fits_in_one_chunk_when_small(self):
        assert chunk_blocks(["uno", "due"], limit=100) == ["uno\n\ndue"]

    def test_oversized_block_is_split_by_lines(self):
        block = "\n".join(f"riga {i:02d}" for i in range(10))  # 10 righe da 7 caratteri

        chunks = chunk_blocks([block], limit=30)

        assert all(len(chunk) <= 30 for chunk in chunks)
        assert "\n".join(chunks) == block

    def test_no_blocks_no_chunks(self):
        assert chunk_blocks([], limit=100) == []


class TestStatsReply:
    def test_group_stats_in_the_stats_channel_are_public_and_in_code_blocks(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, user="gruppo", dettaglio="tutto")

        assert reply.ephemeral is False
        assert all(m.startswith("```\n") and m.endswith("\n```") for m in reply.messages)
        assert all(len(m) <= 2000 for m in reply.messages)
        text = "\n".join(reply.messages)
        assert "Statistiche: gruppo" in text
        assert "visualizzazioni: 3" in text
        assert "Classifica utenti:" in text

    def test_user_and_period(self, tmp_path):
        reply = stats_reply(
            seeded_db_file(tmp_path), CONFIG, channel_id=100, user="mario", since_text="01/07/2026", until_text="07/07/2026"
        )

        text = "\n".join(reply.messages)
        assert "Statistiche: mario (dal 01/07/2026 al 07/07/2026)" in text
        assert "visualizzazioni: 1" in text
        assert "Classifica utenti:" not in text

    def test_month_and_year_bounds_cover_the_whole_period(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, user="gruppo", since_text="07/2026", until_text="2026")

        assert "Statistiche: gruppo (dal 01/07/2026 al 31/12/2026)" in "\n".join(reply.messages)

    def test_other_channels_get_a_private_pointer_to_the_stats_channel(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=999)

        assert reply.ephemeral is True
        assert reply.messages == ["Le statistiche si chiedono nel canale <#100>."]

    def test_unknown_user_is_a_private_error(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, user="nessuno")

        assert reply.ephemeral is True
        assert "nessuno" in reply.messages[0]

    def test_invalid_date_is_a_private_error_quoting_the_input(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, since_text="ieri")

        assert reply.ephemeral is True
        assert "ieri" in reply.messages[0]
        assert "gg/mm/aaaa" in reply.messages[0]

    def test_missing_database_is_a_private_error(self, tmp_path):
        reply = stats_reply(tmp_path / "manca.sqlite", CONFIG, channel_id=100)

        assert reply.ephemeral is True
        assert "Database non trovato" in reply.messages[0]

    def test_long_reports_are_split_into_several_messages(self, tmp_path):
        path = seeded_db_file(tmp_path)
        db = Database.open(path)
        for index in range(60):  # molti film: il report supera il limite di un messaggio
            db.save_movie(MovieDetails(1000 + index, f"Film {index}", None, 2000 + index % 20, 100, ((index, f"Genere {index}"),), ()))
            db.add_viewing(
                user_id=db.user_id_by_whatsapp("Mario Rossi"),
                tmdb_id=1000 + index,
                watched_on=date(2026, 8, 1 + index % 28),
                watched_on_source="body",
                rating=None,
                sent_at=datetime(2026, 9, 1),
                source_ref=f"extra{index}",
            )
        db.commit()
        db.close()

        reply = stats_reply(path, CONFIG, channel_id=100, user="gruppo", top_n=60, dettaglio="tutto")

        assert len(reply.messages) > 1
        assert all(len(m) <= 2000 for m in reply.messages)


class TestUserNames:
    def test_internal_names_sorted(self, tmp_path):
        assert user_names(seeded_db_file(tmp_path)) == ["franco", "mario"]

    def test_missing_database_has_no_names(self, tmp_path):
        assert user_names(tmp_path / "manca.sqlite") == []


def test_message_limit_leaves_room_for_the_code_fence():
    assert MESSAGE_LIMIT + len("```\n") + len("\n```") <= 2000


class TestSyncUsers:
    def write_users(self, tmp_path, text):
        path = tmp_path / "users.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_renames_and_discord_ids_in_the_file_reach_the_database(self, tmp_path):
        db_path = seeded_db_file(tmp_path)
        users = self.write_users(
            tmp_path,
            'users:\n  - {name: Bastio, whatsapp: "Mario Rossi", discord_id: 555}\n  - {name: franco, whatsapp: "Franco Rossi"}\n',
        )

        assert sync_users(db_path, users) is True

        assert user_names(db_path) == ["Bastio", "franco"]
        reply = stats_reply(db_path, CONFIG, channel_id=100, user="Bastio")
        assert "visualizzazioni: 2" in "\n".join(reply.messages)

    def test_without_a_database_nothing_is_created(self, tmp_path):
        users = self.write_users(tmp_path, 'users:\n  - {name: a, whatsapp: "A"}\n')

        assert sync_users(tmp_path / "manca.sqlite", users) is False
        assert not (tmp_path / "manca.sqlite").exists()

    def test_without_a_users_file_nothing_changes(self, tmp_path):
        db_path = seeded_db_file(tmp_path)

        assert sync_users(db_path, tmp_path / "manca.yaml") is False
        assert user_names(db_path) == ["franco", "mario"]

    def test_invalid_users_file_is_a_config_error(self, tmp_path):
        db_path = seeded_db_file(tmp_path)
        users = self.write_users(tmp_path, "users:\n  - {name: a}\n")

        with pytest.raises(ConfigError):
            sync_users(db_path, users)


class TestViewingsReply:
    TODAY = date(2026, 7, 8)

    def reply(self, tmp_path, **kwargs):
        defaults = dict(channel_id=100, user="gruppo", periodo=None, since_text=None, until_text=None, title=None)
        return viewings_reply(seeded_db_file(tmp_path), CONFIG, today=self.TODAY, **{**defaults, **kwargs})

    def test_group_list_is_public_and_in_code_blocks(self, tmp_path):
        reply = self.reply(tmp_path)

        assert reply.ephemeral is False
        assert reply.messages[0].startswith("```\nVisioni: gruppo")
        assert "3 visioni" in reply.messages[0]

    def test_other_channels_get_a_private_pointer(self, tmp_path):
        reply = self.reply(tmp_path, channel_id=999)

        assert reply.ephemeral is True
        assert reply.messages == ["Le statistiche si chiedono nel canale <#100>."]

    def test_user_title_and_dates_filter(self, tmp_path):
        reply = self.reply(tmp_path, user="mario", since_text="06/07/2026", title="heat")

        text = reply.messages[0]
        assert "Visioni: mario (dal 06/07/2026)" in text
        assert "titolo «heat»" in text
        assert "1 visioni" in text or "1 visione" in text

    def test_period_shortcut_uses_today(self, tmp_path):
        reply = self.reply(tmp_path, periodo="settimana")  # 08/07/2026 è un mercoledì: 06–12 luglio

        text = reply.messages[0]
        assert "dal 06/07/2026 al 12/07/2026" in text
        assert "2 visioni" in text  # le visioni del 6 e del 9 luglio

    def test_period_and_dates_together_are_rejected_privately(self, tmp_path):
        reply = self.reply(tmp_path, periodo="mese", since_text="01/07/2026")

        assert reply.ephemeral is True
        assert "periodo" in reply.messages[0] and "dal" in reply.messages[0]

    def test_unknown_period_unknown_user_and_bad_date_are_private_errors(self, tmp_path):
        for kwargs, needle in [
            ({"periodo": "ieri"}, "ieri"),
            ({"user": "nessuno"}, "nessuno"),
            ({"since_text": "boh"}, "boh"),
        ]:
            reply = self.reply(tmp_path, **kwargs)
            assert reply.ephemeral is True and needle in reply.messages[0]

    def test_no_match_says_so_in_plain_text(self, tmp_path):
        reply = self.reply(tmp_path, title="zzz")

        assert reply.messages == ["Nessuna visione trovata con questi filtri."]
        assert reply.ephemeral is False

    def test_missing_database_is_a_private_error(self, tmp_path):
        reply = viewings_reply(
            tmp_path / "manca.sqlite", CONFIG, 100, None, None, None, None, None, today=self.TODAY
        )

        assert reply.ephemeral is True and "Database non trovato" in reply.messages[0]

    def test_many_viewings_become_several_pages(self, tmp_path):
        path = seeded_db_file(tmp_path)
        db = Database.open(path)
        for index in range(50):
            db.save_movie(MovieDetails(2000 + index, f"Film {index}", None, 2000, 100, (), ()))
            db.add_viewing(
                user_id=db.user_id_by_whatsapp("Mario Rossi"),
                tmdb_id=2000 + index,
                watched_on=date(2026, 6, 1 + index % 28),
                watched_on_source="body",
                rating=None,
                sent_at=datetime(2026, 9, 1),
                source_ref=f"extra{index}",
            )
        db.commit()
        db.close()

        reply = viewings_reply(path, CONFIG, 100, "gruppo", None, None, None, None, today=self.TODAY)

        assert len(reply.messages) == 3  # 53 visioni, 20 per pagina
        assert all(len(m) <= 2000 for m in reply.messages)


class TestStatsPeriodShortcut:
    TODAY = date(2026, 7, 8)  # mercoledì

    def test_period_shortcut_on_stats_uses_today(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, 100, user="gruppo", periodo="settimana", today=self.TODAY)

        text = "\n".join(reply.messages)
        assert "Statistiche: gruppo (dal 06/07/2026 al 12/07/2026)" in text
        assert "visualizzazioni: 2" in text  # le visioni del 6 e del 9 luglio

    def test_period_shortcut_combines_with_a_user(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, 100, user="mario", periodo="mese", today=self.TODAY)

        assert "visualizzazioni: 2" in "\n".join(reply.messages)

    def test_period_and_dates_together_are_rejected_privately(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, 100, user="gruppo", periodo="mese", since_text="01/07/2026", today=self.TODAY)

        assert reply.ephemeral is True
        assert "periodo" in reply.messages[0]

    def test_unknown_period_is_a_private_error(self, tmp_path):
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, 100, periodo="ieri", today=self.TODAY)

        assert reply.ephemeral is True and "ieri" in reply.messages[0]


class TestCancelChannels:
    def test_allowed_in_the_stats_and_the_viewings_channels(self):
        config = DiscordConfig(guild_id=1, stats_channel_id=100, input_channel_id=200)

        assert cancel_channel_error(config, 100) is None
        assert cancel_channel_error(config, 200) is None

    def test_elsewhere_the_message_names_the_right_channels(self):
        config = DiscordConfig(guild_id=1, stats_channel_id=100, input_channel_id=200)

        message = cancel_channel_error(config, 999)

        assert "<#100>" in message and "<#200>" in message

    def test_without_a_viewings_channel_only_the_stats_one_counts(self):
        config = DiscordConfig(guild_id=1, stats_channel_id=100)

        assert cancel_channel_error(config, 100) is None
        assert "<#100>" in cancel_channel_error(config, 200)


class TestDefaultUser:
    """Senza `utente` si vedono i propri dati; il gruppo va chiesto con `gruppo`."""

    TODAY = date(2026, 7, 8)

    def stats(self, tmp_path, **kwargs):
        return stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, today=self.TODAY, **kwargs)

    def viewings(self, tmp_path, **kwargs):
        defaults = dict(channel_id=100, user=None, periodo=None, since_text=None, until_text=None, title=None)
        return viewings_reply(seeded_db_file(tmp_path), CONFIG, today=self.TODAY, **{**defaults, **kwargs})

    def test_stats_default_to_the_callers_own(self, tmp_path):
        text = "\n".join(self.stats(tmp_path, discord_id=MARIO).messages)

        assert "Statistiche: mario" in text and "visualizzazioni: 2" in text
        assert "Classifica utenti:" not in text

    def test_stats_for_the_group_are_asked_explicitly(self, tmp_path):
        for word in ("gruppo", "Gruppo"):
            text = "\n".join(self.stats(tmp_path, user=word, discord_id=MARIO, dettaglio="tutto").messages)

            assert "Statistiche: gruppo" in text and "visualizzazioni: 3" in text
            assert "Classifica utenti:" in text

    def test_an_explicit_user_wins_over_the_caller(self, tmp_path):
        text = "\n".join(self.stats(tmp_path, user="franco", discord_id=MARIO).messages)

        assert "Statistiche: franco" in text and "visualizzazioni: 1" in text

    @pytest.mark.parametrize("discord_id", [STRANGER, None])
    def test_an_unknown_caller_is_told_how_to_be_added_and_how_to_see_the_group(self, tmp_path, discord_id):
        reply = self.stats(tmp_path, discord_id=discord_id)

        assert reply.ephemeral is True
        assert "users.yaml" in reply.messages[0] and "gruppo" in reply.messages[0]

    def test_an_unknown_caller_can_still_ask_for_the_group(self, tmp_path):
        reply = self.stats(tmp_path, user="gruppo", discord_id=STRANGER)

        assert reply.ephemeral is False and "Statistiche: gruppo" in reply.messages[0]

    def test_viewings_default_to_the_callers_own_without_the_user_column(self, tmp_path):
        reply = self.viewings(tmp_path, discord_id=MARIO)

        assert reply.messages[0].startswith("```\nVisioni: mario") and "2 visioni" in reply.messages[0]
        assert "franco" not in reply.messages[0]

    def test_viewings_for_the_group_are_asked_explicitly(self, tmp_path):
        reply = self.viewings(tmp_path, user="gruppo", discord_id=MARIO)

        assert reply.messages[0].startswith("```\nVisioni: gruppo") and "3 visioni" in reply.messages[0]

    def test_viewings_of_an_unknown_caller_are_refused_privately(self, tmp_path):
        reply = self.viewings(tmp_path, discord_id=STRANGER)

        assert reply.ephemeral is True and "users.yaml" in reply.messages[0]


class TestDetail:
    def stats(self, tmp_path, **kwargs):
        return stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, user="gruppo", **kwargs)

    def test_by_default_only_the_base_is_shown_in_one_message(self, tmp_path):
        reply = self.stats(tmp_path)

        assert len(reply.messages) == 1
        text = reply.messages[0]
        assert "visualizzazioni: 3" in text and "serie consecutiva" in text
        assert "Generi più visti:" not in text and "Classifica utenti:" not in text

    def test_a_detail_adds_its_group_of_statistics(self, tmp_path):
        assert "Generi più visti:" in self.stats(tmp_path, dettaglio="gusti").messages[0]
        assert "Giorni della settimana:" in "\n".join(self.stats(tmp_path, dettaglio="tempo").messages)
        assert "Durata:" in self.stats(tmp_path, dettaglio="durata").messages[0]

    def test_everything_is_the_complete_report(self, tmp_path):
        text = "\n".join(self.stats(tmp_path, dettaglio="tutto").messages)

        assert "Classifica utenti:" in text and "Generi più visti:" in text and "durata media" in text

    def test_rankings_are_for_the_group_only(self, tmp_path):
        assert "Classifica utenti:" in "\n".join(self.stats(tmp_path, dettaglio="classifiche").messages)

        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100, user="mario", dettaglio="classifiche")

        assert reply.ephemeral is True and "gruppo" in reply.messages[0]

    def test_an_unknown_detail_is_a_private_error(self, tmp_path):
        reply = self.stats(tmp_path, dettaglio="boh")

        assert reply.ephemeral is True and "boh" in reply.messages[0]
