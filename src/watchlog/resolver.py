"""Sceglie, tra i candidati TMDB, il film a cui si riferisce un titolo scritto in chat."""

import difflib
import re
import unicodedata
from dataclasses import dataclass

from watchlog.tmdb import Candidate

YEAR_TOLERANCE = 1  # l'anno di uscita italiano può differire da quello originale
YEAR_PENALTY = 0.1  # per ogni anno di scarto: a parità di titolo vince l'anno esatto
MIN_SIMILARITY = 0.6  # sotto questa soglia il candidato non è considerato
RESOLVE_SCORE = 0.85  # punteggio minimo per risolvere in automatico
RESOLVE_GAP = 0.1  # distacco minimo dal secondo candidato


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    similarity: float
    score: float


@dataclass(frozen=True)
class Resolution:
    status: str  # "resolved", "ambiguous" oppure "not_found"
    title: str
    year: int
    scored: list[Scored]  # candidati idonei, il migliore per primo

    @property
    def best(self) -> Scored | None:
        return self.scored[0] if self.scored else None


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[\W_]+", " ", without_accents.casefold()).strip()


def resolve(title: str, year: int, candidates: list[Candidate]) -> Resolution:
    wanted = normalize(title)
    scored = []
    for candidate in candidates:
        if candidate.year is None or abs(candidate.year - year) > YEAR_TOLERANCE:
            continue
        similarity = _similarity(wanted, candidate)
        if similarity < MIN_SIMILARITY:
            continue
        scored.append(Scored(candidate, similarity, similarity - YEAR_PENALTY * abs(candidate.year - year)))
    scored.sort(key=lambda s: (-s.score, -s.candidate.popularity))

    if not scored:
        status = "not_found"
    elif scored[0].score >= RESOLVE_SCORE and (
        len(scored) == 1 or round(scored[0].score - scored[1].score, 6) >= RESOLVE_GAP
    ):
        status = "resolved"
    else:
        status = "ambiguous"
    return Resolution(status, title, year, scored)


def _similarity(wanted: str, candidate: Candidate) -> float:
    names = (candidate.title_it, candidate.title_en, candidate.original_title)
    return max(
        (difflib.SequenceMatcher(None, wanted, normalize(name)).ratio() for name in names if name),
        default=0.0,
    )
