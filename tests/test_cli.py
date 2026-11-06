from pathlib import Path

import pytest

from watchlog.cli import main

SAMPLE = Path(__file__).parent / "fixtures" / "sample_chat.txt"


def test_parse_prints_entries_and_summary(capsys):
    exit_code = main(["parse", str(SAMPLE)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Mario Rossi" in out
    assert "Good Fortune (2025)" in out
    assert "62 visualizzazioni, 0 anomalie" in out


def test_parse_lists_anomalies(tmp_path, capsys):
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "06/07/26, 00:45 - Mario Rossi: ciao a tutti\n"
        "06/07/26, 00:46 - Mario Rossi: 05/07/2026 - Heat (1995)\n",
        encoding="utf-8",
    )

    exit_code = main(["parse", str(chat)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "riga 1" in out
    assert "ciao a tutti" in out
    assert "1 visualizzazioni, 1 anomalie" in out


def test_parse_missing_file_fails(capsys):
    exit_code = main(["parse", "/non/esiste.txt"])

    assert exit_code == 2
    assert "/non/esiste.txt" in capsys.readouterr().err


class FakeClient:
    """Sostituisce TmdbClient: restituisce candidati preconfezionati per titolo."""

    def __init__(self, by_title):
        self.by_title = by_title
        self.searched = []

    def search(self, title):
        self.searched.append(title)
        return self.by_title.get(title, [])


def _film(tmdb_id, year, en, popularity=1.0):
    from watchlog.tmdb import Candidate

    return Candidate(tmdb_id, None, en, en, year, popularity)


def test_resolve_prints_the_chosen_film(monkeypatch, capsys):
    client = FakeClient({"Roofman": [_film(11, 2025, "Roofman")]})
    monkeypatch.setattr("watchlog.cli._make_client", lambda: client)

    exit_code = main(["resolve", "Roofman (2026)"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "resolved" in out
    assert "Roofman (2025)" in out
    assert "11" in out


def test_resolve_lists_candidates_when_ambiguous(monkeypatch, capsys):
    client = FakeClient({"Roofman": [_film(11, 2025, "Roofman"), _film(12, 2025, "Roofman")]})
    monkeypatch.setattr("watchlog.cli._make_client", lambda: client)

    main(["resolve", "Roofman (2025)"])

    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "11" in out and "12" in out


def test_resolve_rejects_text_without_year(monkeypatch, capsys):
    monkeypatch.setattr("watchlog.cli._make_client", lambda: FakeClient({}))

    exit_code = main(["resolve", "Roofman"])

    assert exit_code == 2
    assert "titolo (anno)" in capsys.readouterr().err


def test_resolve_chat_reports_each_distinct_film_once(tmp_path, monkeypatch, capsys):
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "06/07/26, 00:45 - Mario Rossi: 05/07/2026 - Roofman (2025)\n"
        "06/07/26, 00:46 - Franco Rossi: 05/07/2026 - Roofman (2025)\n"
        "06/07/26, 00:47 - Franco Rossi: 05/07/2026 - Sconosciuto (2020)\n",
        encoding="utf-8",
    )
    client = FakeClient({"Roofman": [_film(11, 2025, "Roofman")]})
    monkeypatch.setattr("watchlog.cli._make_client", lambda: client)

    exit_code = main(["resolve-chat", str(chat)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert client.searched == ["Roofman", "Sconosciuto"]
    assert "1 risolti, 0 ambigui, 1 non trovati su 2 film distinti" in out


def _details(tmdb_id, title, year):
    from watchlog.tmdb import MovieDetails

    return MovieDetails(tmdb_id, title, title, year, 120, ((18, "Drammatico"),), ((1, "Regista"),))


class ImportClient(FakeClient):
    def details(self, tmdb_id):
        return _details(tmdb_id, "Roofman", 2025)


def _import_setup(tmp_path, monkeypatch):
    from watchlog.db import Database

    chat = tmp_path / "chat.txt"
    chat.write_text(
        "06/07/26, 00:45 - Mario Rossi: 05/07/2026 - Roofman (2025)\n"
        "06/07/26, 00:46 - Sconosciuto: 05/07/2026 - Roofman (2025)\n"
        "06/07/26, 00:47 - Mario Rossi: 05/07/2026 - Introvabile (2020)\n",
        encoding="utf-8",
    )
    users = tmp_path / "users.yaml"
    users.write_text('users:\n  - {name: mario, whatsapp: "Mario Rossi"}\n', encoding="utf-8")
    monkeypatch.setattr("watchlog.cli._make_client", lambda: ImportClient({"Roofman": [_film(11, 2025, "Roofman")]}))
    db_path = tmp_path / "data" / "w.sqlite"
    args = ["import", str(chat), "--db", str(db_path), "--users", str(users)]
    return args, db_path, Database


def test_import_writes_the_database_and_prints_the_report(tmp_path, monkeypatch, capsys):
    args, db_path, Database = _import_setup(tmp_path, monkeypatch)

    exit_code = main(args)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "inseriti: 1" in out
    assert "Sconosciuto" in out
    assert 'title: "Introvabile", year: 2020' in out
    assert "corrections:" in out
    assert [v["user"] for v in Database.open(db_path).list_viewings()] == ["mario"]


def test_import_dry_run_reports_the_same_but_writes_nothing(tmp_path, monkeypatch, capsys):
    args, db_path, _ = _import_setup(tmp_path, monkeypatch)

    exit_code = main(args + ["--dry-run"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "dry-run" in out
    assert "inseriti: 1" in out
    assert not db_path.exists()


def test_import_without_users_file_fails_clearly(tmp_path, monkeypatch, capsys):
    args, _, _ = _import_setup(tmp_path, monkeypatch)
    args[args.index("--users") + 1] = str(tmp_path / "manca.yaml")

    exit_code = main(args)

    assert exit_code == 2
    assert "manca.yaml" in capsys.readouterr().err


def _seeded_stats_db(tmp_path):
    from datetime import date, datetime

    from watchlog.config import UserConfig
    from watchlog.db import Database

    path = tmp_path / "w.sqlite"
    db = Database.open(path)
    db.sync_users([UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", None)])
    db.save_movie(_details(1, "Heat", 1995))
    for index, (user, day) in enumerate([("Mario Rossi", 5), ("Mario Rossi", 9), ("Franco Rossi", 6)]):
        db.add_viewing(
            user_id=db.user_id_by_whatsapp(user),
            tmdb_id=1,
            watched_on=date(2026, 7, day),
            watched_on_source="body",
            rating=4.5 if index == 0 else None,
            sent_at=datetime(2026, 7, 20),
            source_ref=f"r{index}",
        )
    db.commit()
    db.close()
    return path


def test_stats_prints_group_numbers_and_extras(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    exit_code = main(["stats", "--db", str(path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Statistiche: gruppo" in out
    assert "visualizzazioni: 3" in out
    assert "film distinti: 1" in out
    assert "rivisioni: 1" in out
    assert "6 h 0 min" in out
    assert "voto medio: 4,5" in out
    assert "Generi più visti" in out
    assert "Classifica utenti" in out
    assert "mario" in out


def test_stats_for_a_single_user_has_no_group_sections(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    exit_code = main(["stats", "--db", str(path), "--user", "franco"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Statistiche: franco" in out
    assert "visualizzazioni: 1" in out
    assert "Classifica utenti" not in out


def test_stats_unknown_user_fails_clearly(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    exit_code = main(["stats", "--db", str(path), "--user", "nessuno"])

    assert exit_code == 2
    assert "nessuno" in capsys.readouterr().err


def test_stats_without_a_database_fails_clearly(tmp_path, capsys):
    exit_code = main(["stats", "--db", str(tmp_path / "manca.sqlite")])

    assert exit_code == 2
    assert "manca.sqlite" in capsys.readouterr().err


def test_import_report_lists_suspicious_dates(tmp_path, monkeypatch, capsys):
    args, _, _ = _import_setup(tmp_path, monkeypatch)
    chat = tmp_path / "chat.txt"
    chat.write_text(chat.read_text(encoding="utf-8") + "06/07/26, 00:50 - Mario Rossi: 05/01/2025 - Roofman (2025)\n", encoding="utf-8")

    main(args + ["--dry-run"])

    out = capsys.readouterr().out
    assert "Date sospette (1)" in out
    assert "riga 4" in out
    assert "visto il 2025-01-05, inviato il 2026-07-06" in out


def test_import_report_without_suspicious_dates_has_no_section(tmp_path, monkeypatch, capsys):
    args, _, _ = _import_setup(tmp_path, monkeypatch)

    main(args + ["--dry-run"])

    assert "Date sospette" not in capsys.readouterr().out


def test_stats_prints_runtime_streak_weekday_and_busiest_day_sections(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    main(["stats", "--db", str(path)])

    out = capsys.readouterr().out
    assert "durata media: 2 h 0 min" in out
    assert "film più lungo: Heat (2 h 0 min)" in out
    assert "film più corto: Heat (2 h 0 min)" in out
    assert "serie consecutiva più lunga: 2 giorni (dal 2026-07-05 al 2026-07-06)" in out
    assert "Giorni della settimana:" in out
    assert "Domenica: 1" in out
    assert "Lunedì: 1" in out
    assert "Giorni con più film:" in out
    assert "2026-07-05: 1" in out
    assert "2026-07: 3 visualizzazioni, 6 h 0 min" in out


def test_stats_period_filters_and_is_shown_in_the_title(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    exit_code = main(["stats", "--db", str(path), "--dal", "2026-07-06", "--al", "2026-07-31"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Statistiche: gruppo (dal 2026-07-06 al 2026-07-31)" in out
    assert "visualizzazioni: 2" in out


def test_stats_invalid_period_date_is_rejected(tmp_path, capsys):
    path = _seeded_stats_db(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        main(["stats", "--db", str(path), "--dal", "boh"])

    assert exit_info.value.code == 2
    assert "boh" in capsys.readouterr().err
