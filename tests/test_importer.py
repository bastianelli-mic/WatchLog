from watchlog.config import Corrections, UserConfig, load_corrections
from watchlog.db import Database
from watchlog.importer import corrections_template, import_chat
from watchlog.resolver import resolve
from watchlog.tmdb import Candidate, MovieDetails

USERS = [UserConfig("mario", "Mario Rossi", None), UserConfig("franco", "Franco Rossi", "111")]

CHAT = (
    "06/07/26, 00:45 - Mario Rossi: 05/07/2026 - Heat (1995)\n"
    "06/07/26, 00:46 - Franco Rossi: 04/07/2026 - Heat (1995) [4.5]\n"
    "06/07/26, 00:47 - Giuseppe Verdi: 05/07/2026 - Heat (1995)\n"
)


def candidate(tmdb_id, year, title):
    return Candidate(tmdb_id, None, title, title, year, 1.0)


def details(tmdb_id, title, year):
    return MovieDetails(tmdb_id, title, title, year, 120, ((18, "Drammatico"),), ((1, "Regista"),))


class FakeClient:
    def __init__(self, found, info):
        self.found = found  # titolo -> [Candidate]
        self.info = info  # tmdb_id -> MovieDetails
        self.search_calls = []
        self.details_calls = []

    def search(self, title):
        self.search_calls.append(title)
        return self.found.get(title, [])

    def details(self, tmdb_id):
        self.details_calls.append(tmdb_id)
        return self.info[tmdb_id]


def make(tmp_path):
    db = Database.open(tmp_path / "w.sqlite")
    db.sync_users(USERS)
    client = FakeClient({"Heat": [candidate(949, 1995, "Heat")]}, {949: details(949, "Heat", 1995)})
    return db, client


def test_mapped_users_get_their_viewings_with_the_body_date_and_rating(tmp_path):
    db, client = make(tmp_path)

    report = import_chat(CHAT, db, client, Corrections({}))

    rows = sorted((v["user"], str(v["watched_on"]), v["rating"]) for v in db.list_viewings())
    assert rows == [("franco", "2026-07-04", 4.5), ("mario", "2026-07-05", None)]
    assert report.entries == 3
    assert report.inserted == 2


def test_unmapped_author_is_skipped_and_counted(tmp_path):
    db, client = make(tmp_path)

    report = import_chat(CHAT, db, client, Corrections({}))

    assert report.unmapped_authors == {"Giuseppe Verdi": 1}


def test_importing_twice_adds_nothing_and_does_not_call_tmdb_again(tmp_path):
    db, client = make(tmp_path)
    import_chat(CHAT, db, client, Corrections({}))
    searches, fetched = len(client.search_calls), len(client.details_calls)

    report = import_chat(CHAT, db, client, Corrections({}))

    assert report.inserted == 0
    assert report.duplicates == 2
    assert len(db.list_viewings()) == 2
    assert (len(client.search_calls), len(client.details_calls)) == (searches, fetched)


def test_movie_details_are_fetched_once_per_film_not_per_viewing(tmp_path):
    db, client = make(tmp_path)

    report = import_chat(CHAT, db, client, Corrections({}))

    assert client.details_calls == [949]
    assert client.search_calls == ["Heat"]
    assert report.new_movies == 1


def test_movie_already_in_the_database_is_not_fetched_again(tmp_path):
    db, client = make(tmp_path)
    db.save_movie(details(949, "Heat", 1995))

    report = import_chat(CHAT, db, client, Corrections({}))

    assert client.details_calls == []
    assert report.new_movies == 0
    assert report.inserted == 2


def test_ambiguous_film_is_reported_and_not_imported(tmp_path):
    db, _ = make(tmp_path)
    client = FakeClient({"Heat": [candidate(1, 1995, "Heat"), candidate(2, 1995, "Heat")]}, {})

    report = import_chat(CHAT, db, client, Corrections({}))

    assert report.inserted == 0
    assert [(r.title, r.year, r.status) for r in report.unresolved] == [("Heat", 1995, "ambiguous")]
    assert report.unresolved_viewings == 2


def test_not_found_film_is_reported(tmp_path):
    db, _ = make(tmp_path)

    report = import_chat(CHAT, db, FakeClient({}, {}), Corrections({}))

    assert [r.status for r in report.unresolved] == ["not_found"]


def test_correction_resolves_an_otherwise_ambiguous_film(tmp_path):
    db, _ = make(tmp_path)
    client = FakeClient(
        {"Heat": [candidate(1, 1995, "Heat"), candidate(2, 1995, "Heat")]},
        {2: details(2, "Heat", 1995)},
    )

    report = import_chat(CHAT, db, client, Corrections({("heat", 1995): 2}))

    assert report.inserted == 2
    assert report.unresolved == []
    assert client.search_calls == []
    assert client.details_calls == [2]


def test_parser_anomalies_are_carried_into_the_report(tmp_path):
    db, client = make(tmp_path)
    chat = CHAT + "06/07/26, 00:48 - Mario Rossi: ciao a tutti\n"

    report = import_chat(chat, db, client, Corrections({}))

    assert [a.raw for a in report.anomalies] == ["ciao a tutti"]


class TestCorrectionsTemplate:
    def test_single_candidate_becomes_an_active_line_with_its_id(self):
        sesto = resolve("Il Sesto Senso", 1999, [Candidate(745, "The Sixth Sense - Il sesto senso", None, None, 1999, 1.0)])

        template = corrections_template([sesto])

        assert '  - {title: "Il Sesto Senso", year: 1999, tmdb_id: 745}' in template
        assert "The Sixth Sense - Il sesto senso (1999)" in template

    def test_several_candidates_are_listed_in_a_commented_line_to_choose_from(self):
        reunion = resolve("Reunion", 2024, [candidate(1, 2024, "Reunion"), candidate(2, 2024, "Reunion")])

        template = corrections_template([reunion])

        assert '  # - {title: "Reunion", year: 2024, tmdb_id: ???}' in template
        assert "1 Reunion (2024) | 2 Reunion (2024)" in template

    def test_not_found_is_a_commented_placeholder(self):
        lost = resolve("In the Lost Landa", 2025, [])

        template = corrections_template([lost])

        assert '  # - {title: "In the Lost Landa", year: 2025, tmdb_id: ???}' in template
        assert "non trovato" in template

    def test_nothing_unresolved_gives_an_empty_template(self):
        assert corrections_template([]) == ""

    def test_template_is_a_valid_corrections_file_with_only_the_active_lines(self, tmp_path):
        resolutions = [
            resolve("Il Sesto Senso", 1999, [Candidate(745, "The Sixth Sense - Il sesto senso", None, None, 1999, 1.0)]),
            resolve("Reunion", 2024, [candidate(1, 2024, "Reunion"), candidate(2, 2024, "Reunion")]),
            resolve('Dice "ciao"', 2020, []),
        ]
        path = tmp_path / "corrections.yaml"
        path.write_text(corrections_template(resolutions), encoding="utf-8")

        corrections = load_corrections(path)

        assert corrections.get("Il Sesto Senso", 1999) == 745
        assert corrections.get("Reunion", 2024) is None
        assert corrections.get('Dice "ciao"', 2020) is None

    def test_titles_with_quotes_survive_when_the_line_is_activated(self, tmp_path):
        template = corrections_template([resolve('Dice "ciao"', 2020, [])])
        path = tmp_path / "corrections.yaml"
        path.write_text(template.replace("# - ", "- ").replace("???", "99"), encoding="utf-8")

        assert load_corrections(path).get('Dice "ciao"', 2020) == 99
