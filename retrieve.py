"""
retrieve.py — RAG retrieval module shared by both agents.

Tuned for large mathematical textbook corpora:
- Higher default k (15 per query)
- Cosine similarity (normalized IP) instead of L2
- Source-aware routing: agents can target specific books
- Manifest-driven: agents know what sources are available
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Chunk:
    chunk_id: str
    source: str
    source_file: str
    section: str
    position: int
    text: str
    score: float = 0.0

    def format_for_prompt(self) -> str:
        return (
            f"[source:{self.chunk_id}] ({self.source} | {self.section})\n"
            f"{self.text}"
        )


class Retriever:
    def __init__(self, index_dir: str):
        self.index_dir = Path(index_dir)
        self._index = None
        self._chunks: list[dict] = []
        self._embed_model = None
        self._manifest: dict = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        index_path = self.index_dir / "index.faiss"
        chunks_path = self.index_dir / "chunks.json"
        manifest_path = self.index_dir / "manifest.json"

        if not index_path.exists():
            raise FileNotFoundError(
                f"No FAISS index at {index_path}. "
                "Run: python ingest.py corpus/raw/ --output corpus/index/"
            )

        import faiss
        self._index = faiss.read_index(str(index_path))

        with open(chunks_path) as f:
            self._chunks = json.load(f)

        if manifest_path.exists():
            with open(manifest_path) as f:
                self._manifest = json.load(f)

        self._loaded = True

    def _get_embed_model(self):
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get(
                "EMBED_MODEL",
                self._manifest.get("embedding_model", "all-mpnet-base-v2"),
            )
            self._embed_model = SentenceTransformer(model_name)
        return self._embed_model

    def _embed(self, text: str) -> np.ndarray:
        model = self._get_embed_model()
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return np.array(vec, dtype=np.float32)

    def sources(self) -> dict:
        """Return manifest of available sources (book name → chunk count)."""
        self._load()
        return self._manifest.get("sources", {})

    def retrieve(
        self,
        query: str,
        k: int = 15,
        source_filter: str | None = None,
    ) -> list[Chunk]:
        """Return k most relevant chunks by cosine similarity."""
        self._load()
        if not self._chunks:
            return []

        query_vec = self._embed(query)
        fetch_k = k * 4 if source_filter else k
        fetch_k = min(fetch_k, len(self._chunks))

        scores, indices = self._index.search(query_vec, fetch_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            meta = self._chunks[idx]
            if source_filter and source_filter.lower() not in meta.get("source", "").lower():
                continue
            results.append(Chunk(
                chunk_id=meta["chunk_id"],
                source=meta["source"],
                source_file=meta.get("source_file", ""),
                section=meta.get("section", ""),
                position=meta["position"],
                text=meta["text"],
                score=float(score),
            ))
            if len(results) >= k:
                break

        return results

    def retrieve_multi(
        self,
        queries: list[str],
        k: int = 15,
        source_filter: str | None = None,
    ) -> list[Chunk]:
        """Multi-query retrieval with deduplication, ranked by best score."""
        self._load()
        best: dict[str, Chunk] = {}

        for query in queries:
            for chunk in self.retrieve(query, k=k, source_filter=source_filter):
                existing = best.get(chunk.chunk_id)
                # Higher cosine score = more relevant
                if existing is None or chunk.score > existing.score:
                    best[chunk.chunk_id] = chunk

        # Sort descending by score (cosine similarity: higher = better)
        ranked = sorted(best.values(), key=lambda c: -c.score)
        return ranked[:k]

    def format_context(self, chunks: list[Chunk], max_chars: int = 24_000) -> str:
        """
        Format retrieved chunks as a prompt context block.
        Caps total size at max_chars to protect context windows.
        """
        if not chunks:
            return "[No corpus context retrieved]"

        parts = ["## Retrieved Corpus Context\n"]
        total = 0
        included = 0
        for i, chunk in enumerate(chunks, 1):
            entry = f"### Chunk {i} (score={chunk.score:.3f})\n{chunk.format_for_prompt()}\n"
            if total + len(entry) > max_chars:
                parts.append(
                    f"\n*[{len(chunks) - included} additional chunks truncated to fit context]*"
                )
                break
            parts.append(entry)
            total += len(entry)
            included += 1

        return "\n".join(parts)

    def sources_summary(self) -> str:
        """One-line summary of available books for agent prompts."""
        src = self.sources()
        if not src:
            return "No corpus loaded."
        lines = [f"  - {name}: {info['chunks']} chunks ({info['file']})"
                 for name, info in src.items()]
        return "Available sources:\n" + "\n".join(lines)


class NullRetriever:
    """Used when no corpus has been ingested."""

    def retrieve(self, query: str, k: int = 15, source_filter: str | None = None) -> list[Chunk]:
        return []

    def retrieve_multi(self, queries: list[str], k: int = 15, source_filter: str | None = None) -> list[Chunk]:
        return []

    def format_context(self, chunks: list[Chunk], max_chars: int = 24_000) -> str:
        return "[No corpus available — run ingest.py first to add documents]"

    def sources(self) -> dict:
        return {}

    def sources_summary(self) -> str:
        return "No corpus loaded."


def load_retriever(index_dir: str) -> Retriever | NullRetriever:
    index_path = Path(index_dir) / "index.faiss"
    if not index_path.exists():
        return NullRetriever()
    return Retriever(index_dir)
