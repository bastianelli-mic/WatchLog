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
