import pytest

from watchlog.config import (
    ConfigError,
    DiscordConfig,
    UserConfig,
    load_corrections,
    load_discord_config,
    load_discord_token,
    load_users,
)


def write(tmp_path, text, name="cfg.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestUsers:
    def test_users_with_and_without_discord_id(self, tmp_path):
        path = write(
            tmp_path,
            """
users:
  - name: mario
    whatsapp: "Mario Rossi"
    discord_id: 123456789012345678
  - name: giuseppe
    whatsapp: "Giuseppe Verdi"
""",
        )

        assert load_users(path) == [
            UserConfig("mario", "Mario Rossi", "123456789012345678"),
            UserConfig("giuseppe", "Giuseppe Verdi", None),
        ]

    def test_missing_file_is_a_config_error_naming_the_path(self, tmp_path):
        with pytest.raises(ConfigError, match="nope.yaml"):
            load_users(tmp_path / "nope.yaml")

    def test_missing_file_suggests_copying_the_example_when_it_exists(self, tmp_path):
        example = tmp_path / "users.example.yaml"
        example.write_text("users: []\n")
        target = tmp_path / "users.yaml"

        with pytest.raises(ConfigError) as error:
            load_users(target)

        assert f"cp {example} {target}" in str(error.value)

    def test_missing_file_without_an_example_gives_no_suggestion(self, tmp_path):
        with pytest.raises(ConfigError) as error:
            load_users(tmp_path / "users.yaml")

        assert "cp " not in str(error.value)

    def test_user_without_whatsapp_name_is_rejected(self, tmp_path):
        path = write(tmp_path, "users:\n  - name: mario\n")

        with pytest.raises(ConfigError, match="mario"):
            load_users(path)

    def test_duplicate_whatsapp_names_are_rejected(self, tmp_path):
        path = write(
            tmp_path,
            """
users:
  - {name: a, whatsapp: "Mario Rossi"}
  - {name: b, whatsapp: "Mario Rossi"}
""",
        )

        with pytest.raises(ConfigError, match="Mario Rossi"):
            load_users(path)

    def test_duplicate_internal_names_are_rejected(self, tmp_path):
        path = write(
            tmp_path,
            """
users:
  - {name: a, whatsapp: "Mario Rossi"}
  - {name: a, whatsapp: "Franco Rossi"}
""",
        )

        with pytest.raises(ConfigError, match="a"):
            load_users(path)


class TestCorrections:
    def test_lookup_ignores_case_and_punctuation_of_the_title(self, tmp_path):
        path = write(
            tmp_path,
            """
corrections:
  - {title: "Il Sesto Senso", year: 1999, tmdb_id: 745}
""",
        )

        corrections = load_corrections(path)

        assert corrections.get("il sesto  senso!", 1999) == 745
        assert corrections.get("Il Sesto Senso", 2000) is None

    def test_missing_file_means_no_corrections(self, tmp_path):
        assert load_corrections(tmp_path / "nope.yaml").get("Heat", 1995) is None

    def test_entry_without_tmdb_id_is_rejected(self, tmp_path):
        path = write(tmp_path, "corrections:\n  - {title: Heat, year: 1995}\n")

        with pytest.raises(ConfigError, match="Heat"):
            load_corrections(path)


class TestDiscordConfig:
    def test_guild_and_channels_are_read_and_unknown_keys_ignored(self, tmp_path):
        path = write(
            tmp_path,
            """
guild_id: 1557790947973140623
stats_channel_id: 1568998046593712178
input_channel_id: 1568997973017370816
colore_preferito: blu
""",
        )

        assert load_discord_config(path) == DiscordConfig(
            1557790947973140623, 1568998046593712178, 1568997973017370816
        )

    def test_input_channel_is_optional(self, tmp_path):
        path = write(tmp_path, "guild_id: 1\nstats_channel_id: 2\n")

        assert load_discord_config(path) == DiscordConfig(1, 2, None)

    def test_input_channel_must_be_an_integer_when_present(self, tmp_path):
        path = write(tmp_path, "guild_id: 1\nstats_channel_id: 2\ninput_channel_id: abc\n")

        with pytest.raises(ConfigError, match="input_channel_id"):
            load_discord_config(path)

    def test_missing_file_is_a_config_error_naming_the_path(self, tmp_path):
        with pytest.raises(ConfigError, match="discord.yaml"):
            load_discord_config(tmp_path / "discord.yaml")

    def test_missing_file_suggests_copying_the_example(self, tmp_path):
        (tmp_path / "discord.example.yaml").write_text("guild_id: 1\n")

        with pytest.raises(ConfigError, match="cp "):
            load_discord_config(tmp_path / "discord.yaml")

    @pytest.mark.parametrize("missing", ["guild_id", "stats_channel_id"])
    def test_required_keys_are_named_when_missing(self, tmp_path, missing):
        values = {"guild_id": 1, "stats_channel_id": 2}
        del values[missing]
        path = write(tmp_path, "".join(f"{key}: {value}\n" for key, value in values.items()))

        with pytest.raises(ConfigError, match=missing):
            load_discord_config(path)

    def test_ids_must_be_integers(self, tmp_path):
        path = write(tmp_path, "guild_id: abc\nstats_channel_id: 2\n")

        with pytest.raises(ConfigError, match="guild_id"):
            load_discord_config(path)

    def test_empty_file_names_the_first_missing_key(self, tmp_path):
        with pytest.raises(ConfigError, match="guild_id"):
            load_discord_config(write(tmp_path, ""))


class TestDiscordToken:
    def test_environment_variable_wins_over_file(self, tmp_path):
        key_file = tmp_path / "token"
        key_file.write_text("from-file\n")

        assert load_discord_token({"DISCORD_TOKEN": "from-env"}, key_file) == "from-env"

    def test_file_is_used_when_variable_is_missing(self, tmp_path):
        key_file = tmp_path / "token"
        key_file.write_text("  from-file \n")

        assert load_discord_token({}, key_file) == "from-file"

    def test_missing_token_is_an_error_naming_both_places(self, tmp_path):
        with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
            load_discord_token({}, tmp_path / "nope")
