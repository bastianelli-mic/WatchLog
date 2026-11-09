"""Persistenza SQLite: utenti, film (con generi e registi) e visualizzazioni."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from watchlog.config import UserConfig
from watchlog.tmdb import MovieDetails

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    whatsapp_name TEXT NOT NULL UNIQUE,
    discord_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS user_alias (
    name TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS movie (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    runtime_minutes INTEGER
);
CREATE TABLE IF NOT EXISTS genre (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS movie_genre (
    movie_id INTEGER NOT NULL REFERENCES movie(tmdb_id),
    genre_id INTEGER NOT NULL REFERENCES genre(id),
    PRIMARY KEY (movie_id, genre_id)
);
CREATE TABLE IF NOT EXISTS person (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS movie_director (
    movie_id INTEGER NOT NULL REFERENCES movie(tmdb_id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    PRIMARY KEY (movie_id, person_id)
);
CREATE TABLE IF NOT EXISTS viewing (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    movie_id INTEGER NOT NULL REFERENCES movie(tmdb_id),
    watched_on TEXT NOT NULL,
    watched_on_source TEXT NOT NULL,
    rating REAL,
    sent_at TEXT NOT NULL,
    source_ref TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);
"""


class Database:
    def __init__(self, connection: sqlite3.Connection):
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @classmethod
    def open(cls, path: Path) -> "Database":
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(sqlite3.connect(path))

    @classmethod
    def in_memory(cls, copy_of: Path | None = None) -> "Database":
        """Database in memoria, eventualmente copia di un file: serve al dry-run, non scrive mai su disco."""
        connection = sqlite3.connect(":memory:")
        if copy_of is not None and copy_of.is_file():
            source = sqlite3.connect(copy_of)
            source.backup(connection)
            source.close()
        return cls(connection)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def sync_users(self, users: list[UserConfig]) -> None:
        """Allinea gli utenti al file di configurazione. Il nome WhatsApp è la chiave: nome interno e ID Discord si possono cambiare."""
        for user in users:
            self._conn.execute(
                "INSERT INTO users (name, whatsapp_name, discord_id) VALUES (?, ?, ?) "
                "ON CONFLICT(whatsapp_name) DO UPDATE SET name = excluded.name, discord_id = excluded.discord_id",
                (user.name, user.whatsapp, user.discord_id),
            )
            user_id = self.user_id_by_whatsapp(user.whatsapp)
            self._conn.execute("DELETE FROM user_alias WHERE user_id = ?", (user_id,))
            for alias in user.aliases:
                self._conn.execute("INSERT OR REPLACE INTO user_alias (name, user_id) VALUES (?, ?)", (alias, user_id))

    def user_id_by_whatsapp(self, whatsapp_name: str) -> int | None:
        return self._scalar("SELECT id FROM users WHERE whatsapp_name = ?", whatsapp_name)

    def find_user_by_chat_name(self, chat_name: str) -> tuple[int, str] | None:
        """L'utente e il suo nome principale nella chat, cercando per nome principale o per alias."""
        rows = self.query(
            "SELECT id, whatsapp_name FROM users WHERE whatsapp_name = ? "
            "UNION ALL SELECT u.id, u.whatsapp_name FROM user_alias a JOIN users u ON u.id = a.user_id WHERE a.name = ?",
            (chat_name, chat_name),
        )
        return (rows[0]["id"], rows[0]["whatsapp_name"]) if rows else None

    def user_id_by_discord(self, discord_id: str) -> int | None:
        return self._scalar("SELECT id FROM users WHERE discord_id = ?", discord_id)

    def has_movie(self, tmdb_id: int) -> bool:
        return self._scalar("SELECT 1 FROM movie WHERE tmdb_id = ?", tmdb_id) is not None

    def save_movie(self, movie: MovieDetails) -> None:
        self._conn.execute(
            "INSERT INTO movie (tmdb_id, title, original_title, year, runtime_minutes) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tmdb_id) DO UPDATE SET title = excluded.title, original_title = excluded.original_title, "
            "year = excluded.year, runtime_minutes = excluded.runtime_minutes",
            (movie.tmdb_id, movie.title, movie.original_title, movie.year, movie.runtime_minutes),
        )
        self._conn.execute("DELETE FROM movie_genre WHERE movie_id = ?", (movie.tmdb_id,))
        self._conn.execute("DELETE FROM movie_director WHERE movie_id = ?", (movie.tmdb_id,))
        for genre_id, name in movie.genres:
            self._conn.execute("INSERT OR REPLACE INTO genre (id, name) VALUES (?, ?)", (genre_id, name))
            self._conn.execute("INSERT INTO movie_genre (movie_id, genre_id) VALUES (?, ?)", (movie.tmdb_id, genre_id))
        for person_id, name in movie.directors:
            self._conn.execute("INSERT OR REPLACE INTO person (id, name) VALUES (?, ?)", (person_id, name))
            self._conn.execute(
                "INSERT INTO movie_director (movie_id, person_id) VALUES (?, ?)", (movie.tmdb_id, person_id)
            )

    def movie_genres(self, tmdb_id: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT g.name FROM genre g JOIN movie_genre mg ON mg.genre_id = g.id "
            "WHERE mg.movie_id = ? ORDER BY g.name",
            (tmdb_id,),
        )
        return [row["name"] for row in rows]

    def movie_directors(self, tmdb_id: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT p.name FROM person p JOIN movie_director md ON md.person_id = p.id "
            "WHERE md.movie_id = ? ORDER BY p.name",
            (tmdb_id,),
        )
        return [row["name"] for row in rows]

    def has_viewing(self, source_ref: str) -> bool:
        return self._scalar("SELECT 1 FROM viewing WHERE source_ref = ?", source_ref) is not None

    def get_viewing(self, viewing_id: int) -> dict | None:
        """La visione con utente e film, anche se annullata (`deleted_at` valorizzato); None se non esiste."""
        rows = self.query(
            "SELECT v.id AS id, v.user_id AS user_id, u.name AS user, v.watched_on AS watched_on, "
            "v.deleted_at AS deleted_at, m.title AS title, m.year AS year "
            "FROM viewing v JOIN users u ON u.id = v.user_id JOIN movie m ON m.tmdb_id = v.movie_id "
            "WHERE v.id = ?",
            (viewing_id,),
        )
        return rows[0] if rows else None

    def cancel_viewing(self, viewing_id: int) -> bool:
        """Annullamento logico: la riga resta nel database. False se non esiste o era già annullata."""
        cursor = self._conn.execute(
            "UPDATE viewing SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL", (viewing_id,)
        )
        return cursor.rowcount == 1

    def has_viewing_same_day(self, user_id: int, tmdb_id: int, watched_on: date) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM viewing WHERE user_id = ? AND movie_id = ? AND watched_on = ? AND deleted_at IS NULL",
            (user_id, tmdb_id, watched_on.isoformat()),
        ).fetchone()
        return row is not None

    def add_viewing(
        self,
        *,
        user_id: int,
        tmdb_id: int,
        watched_on: date,
        watched_on_source: str,
        rating: float | None,
        sent_at: datetime,
        source_ref: str,
    ) -> bool:
        """Registra una visualizzazione; restituisce False se `source_ref` era già presente."""
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO viewing "
            "(user_id, movie_id, watched_on, watched_on_source, rating, sent_at, source_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                tmdb_id,
                watched_on.isoformat(),
                watched_on_source,
                rating,
                sent_at.isoformat(timespec="seconds"),
                source_ref,
            ),
        )
        return cursor.rowcount == 1

    def list_viewings(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT u.name AS user, m.tmdb_id, m.title, v.watched_on, v.rating "
            "FROM viewing v JOIN users u ON u.id = v.user_id JOIN movie m ON m.tmdb_id = v.movie_id "
            "WHERE v.deleted_at IS NULL ORDER BY v.watched_on, v.id"
        )
        return [dict(row) for row in rows]

    def query(self, sql: str, parameters=()) -> list[dict]:
        """Esegue una SELECT e restituisce le righe come dizionari (usata dalle statistiche)."""
        return [dict(row) for row in self._conn.execute(sql, parameters)]

    def _scalar(self, sql: str, parameter):
        row = self._conn.execute(sql, (parameter,)).fetchone()
        return row[0] if row else None
