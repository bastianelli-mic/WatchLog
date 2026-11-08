from datetime import date, datetime

import pytest

from watchlog.bot import MESSAGE_LIMIT, chunk_blocks, stats_reply, sync_users, user_names
from watchlog.config import ConfigError, DiscordConfig, UserConfig
from watchlog.db import Database
from watchlog.tmdb import MovieDetails

CONFIG = DiscordConfig(guild_id=1, stats_channel_id=100)


def seeded_db_file(tmp_path):
    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", None)])
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
        reply = stats_reply(seeded_db_file(tmp_path), CONFIG, channel_id=100)

        assert reply.ephemeral is False
        assert all(m.startswith("```\n") and m.endswith("\n```") for m in reply.messages)
        assert all(len(m) <= 2000 for m in reply.messages)
        text = "\n".join(reply.messages)
        assert "Statistiche: gruppo" in text
        assert "visualizzazioni: 3" in text
        assert "Classifica utenti:" in text

    def test_user_and_period(self, tmp_path):
        reply = stats_reply(
            seeded_db_file(tmp_path), CONFIG, channel_id=100, user="mario", since_text="2026-07-01", until_text="2026-07-07"
        )

        text = "\n".join(reply.messages)
        assert "Statistiche: mario (dal 2026-07-01 al 2026-07-07)" in text
        assert "visualizzazioni: 1" in text
        assert "Classifica utenti:" not in text

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
        assert "AAAA-MM-GG" in reply.messages[0]

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

        reply = stats_reply(path, CONFIG, channel_id=100, top_n=60)

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
