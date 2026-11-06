from pathlib import Path

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
