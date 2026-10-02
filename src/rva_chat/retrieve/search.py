"""Hybrid retrieval: BM25 keyword search, with an embedding scorer pluggable
in later without touching call sites (see docs/PLAN.md §3c on why there's no
vector database here — the corpus is small enough that exact in-memory search
costs a fraction of the query-embedding step that would feed it).

v0 ships BM25-only. It already does most of the work for this corpus: queries
are short, specific, and full of proper nouns ("pill bottles", "Northside",
"bike co-op") that keyword search is good at. Flip on embeddings once
sentence-transformers (or a static embedding model) is actually installed —
`search()` already fuses scorers via Reciprocal Rank Fusion, so adding one is
additive, not a rewrite.
"""

from __future__ import annotations

import dataclasses
import re

from rank_bm25 import BM25Okapi

from rva_chat.retrieve.corpus import Chunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# On a corpus this small, BM25's IDF weighting can backfire on common words: "the"
# appearing in only one entity's text makes BM25 treat it as *rare* (high IDF), so
# an off-topic query sharing only stopwords with the corpus can still score as a
# confident match. A short stopword list fixes this; it stops mattering once the
# corpus is large enough for IDF to behave as intended, but costs nothing to keep.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have if in into is it its of on or "
    "that the their this to was were will with you your what who how where when "
    "why do does did can could should would me my we us our "
    # Conversational filler that behaves like noise at this corpus's size, even
    # though it's not in a standard NLP stopword list (see the note in search()).
    "go get got old need needs want wants like looking find help "
    "please thanks hi hello there here some any".split()
)


def _tokenize(text: str) -> list[str]:
    # len > 1 drops single-char fragments from acronyms like "D.I.Y." (-> "d","i","y")
    # — those are noise, not terms, and the same small-corpus IDF quirk above makes
    # them look like confident matches for any query containing that stray letter.
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclasses.dataclass
class ScoredChunk:
    chunk: Chunk
    score: float  # fused rank score, not directly comparable across runs/corpora


class HybridSearcher:
    """BM25 now; `embedder` is an optional callable (text -> vector) that, when
    supplied, gets fused in via Reciprocal Rank Fusion. `None` (the default)
    runs BM25-only — correct, just not hybrid.
    """

    def __init__(self, chunks: list[Chunk], embedder=None):
        self.chunks = chunks
        self._doc_tokens = [_tokenize(c.text) for c in chunks]
        self._doc_token_sets = [set(t) for t in self._doc_tokens]
        self._bm25 = BM25Okapi(self._doc_tokens) if chunks else None
        self._embedder = embedder
        self._embeddings = None
        if embedder is not None and chunks:
            self._embeddings = [embedder(c.text) for c in chunks]

    def search(
        self,
        query: str,
        top_k: int = 5,
        jurisdiction: str | None = None,
        scope: str | None = None,
    ) -> list[ScoredChunk]:
        if not self.chunks or self._bm25 is None:
            return []

        candidate_idx = [
            i
            for i, c in enumerate(self.chunks)
            if (jurisdiction is None or not c.jurisdiction or jurisdiction in c.jurisdiction)
            and (scope is None or c.scope == scope)
        ]
        if not candidate_idx:
            return []

        query_tokens = set(_tokenize(query))
        bm25_scores = self._bm25.get_scores(list(query_tokens))
        # Drop zero-score candidates: BM25 gives 0 to a doc sharing no term with
        # the query, and ranking still happily orders those — without this, a
        # small corpus pads out to top_k with irrelevant cards just to fill the
        # quota, which is exactly what "grounded or silent" (§2) argues against.
        #
        # Known limitation, not fully fixed here: on a 15-document corpus, BM25's
        # IDF treats any word as "rare" (-> high weight) whenever few documents
        # happen to contain it — at this size that includes ordinary conversational
        # words, not just real domain terms (seen in testing: "go" in "Too Good to
        # Go" spuriously matched "...where can I go?"). An early attempt to fix
        # this by requiring 2+ shared tokens overcorrected and broke legitimate
        # single-term matches ("hosting" -> Acorn Host). The real fix is the
        # confidence gate in PLAN.md §2 step 4 — a score threshold tuned against
        # the §6 golden set, not hand-tuned against a handful of example queries —
        # and this stops being a significant issue once the corpus grows past a
        # few hundred chunks (§3d), since IDF then behaves as intended. For now,
        # a larger stopword list (below) catches the common cases cheaply.
        bm25_matched = [i for i in candidate_idx if bm25_scores[i] > 0]
        bm25_rank = sorted(bm25_matched, key=lambda i: -bm25_scores[i])

        if self._embedder is not None and self._embeddings is not None:
            q_vec = self._embedder(query)
            vec_scores = {i: _cosine(q_vec, self._embeddings[i]) for i in candidate_idx}
            vec_rank = sorted(candidate_idx, key=lambda i: -vec_scores[i])
            fused = _reciprocal_rank_fusion([bm25_rank, vec_rank])
            ranked = sorted(fused, key=lambda i: -fused[i])[:top_k]
        else:
            fused = {idx: 1.0 / (rank + 1) for rank, idx in enumerate(bm25_rank)}
            ranked = bm25_rank[:top_k]

        return [ScoredChunk(chunk=self.chunks[i], score=fused[i]) for i in ranked]


def _reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
