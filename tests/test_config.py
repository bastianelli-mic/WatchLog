import pytest

from watchlog.config import ConfigError, UserConfig, load_corrections, load_users


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
