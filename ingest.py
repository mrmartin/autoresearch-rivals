"""
ingest.py — Corpus ingestion pipeline for autoresearch-rivals.

Designed for dense mathematical textbooks:
- Section-aware chunking: Theorem/Definition/Proof blocks are kept intact
- Section breadcrumbs prepended to each chunk so agents know location
- Larger chunks (800 tokens) to avoid splitting mid-proof
- Overlap at paragraph boundaries, not arbitrary character positions

Usage:
    python ingest.py corpus/raw/ --output corpus/index/
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

# Math texts need bigger chunks — proofs and theorem statements can be long.
# 800 tokens ≈ 3200 chars. Overlap at 100 tokens ≈ 400 chars.
CHUNK_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
CHARS_PER_TOKEN = 4  # rough approximation

# Regex patterns for mathematical structure detection
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
MATH_BLOCK_START_RE = re.compile(
    r"^\s*\*\*(Theorem|Lemma|Corollary|Proposition|Definition|Proof|Remark|"
    r"Example|Axiom|Claim|Conjecture|Observation|Notation)\b[^*]*\*\*",
    re.IGNORECASE | re.MULTILINE,
)
# Also detect plain-text math block starters (common in converted PDFs)
PLAIN_BLOCK_START_RE = re.compile(
    r"^(Theorem|Lemma|Corollary|Proposition|Definition|Proof|Remark|"
    r"Example|Axiom|Claim|Conjecture)\s+[\d.]+",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class Chunk:
    chunk_id: str
    source: str           # short display name
    source_file: str      # original filename
    section: str          # section breadcrumb (e.g. "Ch.3 > §3.2 > Theorem 3.4")
    position: int         # chunk index within document
    text: str             # full text including prepended breadcrumb

    def to_dict(self) -> dict:
        return asdict(self)

    def format_for_prompt(self) -> str:
        return (
            f"[source:{self.chunk_id}] ({self.source}, {self.section})\n"
            f"{self.text}"
        )


# ---------------------------------------------------------------------------
# Short display names for known textbooks
# ---------------------------------------------------------------------------

SOURCE_NAMES = {
    "from-frege-to-goedel": "Frege-to-Gödel",
    "modern-mathematical-logic": "ModernMathLogic",
    "proof-complexity": "ProofComplexity",
}


def _short_name(stem: str) -> str:
    for key, name in SOURCE_NAMES.items():
        if key in stem:
            return name
    return stem[:30]


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(path: Path) -> str:
    try:
        import fitz
        doc = fitz.open(str(path))
        parts = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                parts.append(text)
        doc.close()
        return "\n\n".join(parts)
    except Exception as e:
        print(f"[ingest] Warning: PDF extraction failed for {path}: {e}")
        return ""


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    elif suffix in (".txt", ".md"):
        return path.read_text(errors="replace")
    else:
        print(f"[ingest] Skipping unsupported type: {path}")
        return ""


# ---------------------------------------------------------------------------
# Section-aware chunking for mathematical texts
# ---------------------------------------------------------------------------

def _extract_headings(text: str) -> list[tuple[int, int, str]]:
    """Return list of (char_pos, level, heading_text) for all headings."""
    headings = []
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        headings.append((m.start(), level, m.group(2).strip()))
    return headings


def _current_breadcrumb(pos: int, headings: list[tuple[int, int, str]]) -> str:
    """Build a section breadcrumb for a chunk at char position pos."""
    active: dict[int, str] = {}
    for h_pos, h_level, h_text in headings:
        if h_pos > pos:
            break
        # Clear deeper levels when a new heading at this level appears
        for deeper in list(active.keys()):
            if deeper >= h_level:
                del active[deeper]
        active[h_level] = h_text

    if not active:
        return "§ (preamble)"
    parts = [active[lvl] for lvl in sorted(active.keys())]
    return " > ".join(parts)


def _find_math_block_boundaries(text: str) -> list[tuple[int, int]]:
    """
    Find start/end positions of named math blocks (Theorem X.Y ... end of proof).
    Returns list of (start, end) char positions.
    """
    boundaries = []
    patterns = [MATH_BLOCK_START_RE, PLAIN_BLOCK_START_RE]
    starts = []
    for pat in patterns:
        for m in pat.finditer(text):
            starts.append(m.start())
    starts = sorted(set(starts))

    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        boundaries.append((start, end))
    return boundaries


def chunk_math_text(
    text: str,
    source_file: str,
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[tuple[str, str]]:
    """
    Chunk a math textbook intelligently.

    Returns list of (breadcrumb, chunk_text) tuples.
    Strategy:
    1. Try to keep named math blocks (Theorem, Proof, etc.) intact.
    2. If a block exceeds chunk_tokens, split at paragraph boundaries.
    3. For prose sections, slide a window at paragraph boundaries.
    4. Prepend the section breadcrumb to each chunk.
    """
    char_limit = chunk_tokens * CHARS_PER_TOKEN
    char_overlap = overlap_tokens * CHARS_PER_TOKEN

    headings = _extract_headings(text)
    block_boundaries = _find_math_block_boundaries(text)

    chunks: list[tuple[str, str]] = []

    if block_boundaries:
        # Process text as alternating prose and named-block segments
        prev_end = 0
        for block_start, block_end in block_boundaries:
            # Prose before this block
            prose = text[prev_end:block_start]
            if prose.strip():
                for c in _slide_paragraphs(prose, char_limit, char_overlap):
                    pos = prev_end + text[prev_end:block_start].find(c[:50] or c)
                    crumb = _current_breadcrumb(prev_end, headings)
                    chunks.append((crumb, c))

            # The named block itself
            block_text = text[block_start:block_end].strip()
            crumb = _current_breadcrumb(block_start, headings)
            if len(block_text) <= char_limit * 1.5:
                chunks.append((crumb, block_text))
            else:
                # Split large blocks at paragraph boundaries
                for c in _slide_paragraphs(block_text, char_limit, char_overlap):
                    chunks.append((crumb, c))

            prev_end = block_end

        # Trailing prose
        tail = text[prev_end:].strip()
        if tail:
            for c in _slide_paragraphs(tail, char_limit, char_overlap):
                crumb = _current_breadcrumb(prev_end, headings)
                chunks.append((crumb, c))
    else:
        # No detected named blocks — slide over paragraphs
        for c in _slide_paragraphs(text, char_limit, char_overlap):
            # Approximate position by searching for the start of this chunk
            pos = text.find(c[:80]) if c else 0
            crumb = _current_breadcrumb(max(0, pos), headings)
            chunks.append((crumb, c))

    return [(crumb, c) for crumb, c in chunks if c.strip()]


def _slide_paragraphs(text: str, char_limit: int, char_overlap: int) -> list[str]:
    """
    Slide a window over text, breaking at paragraph boundaries.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > char_limit and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Keep overlap: drop paragraphs from the front until we're under overlap size
            while current_parts and current_len > char_overlap:
                removed = current_parts.pop(0)
                current_len -= len(removed)
        current_parts.append(para)
        current_len += para_len

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    # Handle single paragraphs that exceed char_limit
    final = []
    for chunk in chunks:
        if len(chunk) <= char_limit * 1.5:
            final.append(chunk)
        else:
            # Hard split at sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", chunk)
            buf = []
            buf_len = 0
            for sent in sentences:
                if buf_len + len(sent) > char_limit and buf:
                    final.append(" ".join(buf))
                    buf = []
                    buf_len = 0
                buf.append(sent)
                buf_len += len(sent)
            if buf:
                final.append(" ".join(buf))

    return final


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        # all-mpnet-base-v2 handles technical text better than MiniLM
        model_name = os.environ.get("EMBED_MODEL", "all-mpnet-base-v2")
        print(f"[ingest] Loading embedding model: {model_name}")
        _model = SentenceTransformer(model_name)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_embedding_model()
    embeddings = model.encode(
        texts, batch_size=32, show_progress_bar=True,
        normalize_embeddings=True,  # use cosine similarity
    )
    return np.array(embeddings, dtype=np.float32)


# ---------------------------------------------------------------------------
# FAISS index — Inner Product on normalized vectors = cosine similarity
# ---------------------------------------------------------------------------

def build_index(embeddings: np.ndarray):
    import faiss
    dim = embeddings.shape[1]
    # IndexFlatIP + normalized vectors = cosine similarity search
    index = faiss.IndexFlatIP(dim)
    index_with_ids = faiss.IndexIDMap(index)
    ids = np.arange(len(embeddings), dtype=np.int64)
    index_with_ids.add_with_ids(embeddings, ids)
    return index_with_ids


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def ingest(input_dir: str, output_dir: str):
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    processed_path = input_path.parent / "processed"
    processed_path.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in (".pdf", ".txt", ".md")
    )

    if not files:
        print(f"[ingest] No supported files found in {input_dir}")
        return

    print(f"[ingest] Processing {len(files)} file(s)...")

    all_chunks: list[Chunk] = []

    for file_path in files:
        short = _short_name(file_path.stem)
        print(f"[ingest]   {file_path.name} → [{short}]")

        text = extract_text(file_path)
        if not text.strip():
            print(f"[ingest]   WARNING: no text extracted from {file_path.name}")
            continue

        # Save processed text
        (processed_path / (file_path.stem + ".txt")).write_text(text)

        raw_chunks = chunk_math_text(text, file_path.name)
        print(f"[ingest]     {len(raw_chunks)} chunks from {len(text):,} chars")

        for idx, (breadcrumb, chunk_text) in enumerate(raw_chunks):
            # Prepend breadcrumb so the embedding captures section context
            full_text = f"[{short} | {breadcrumb}]\n\n{chunk_text}"
            chunk = Chunk(
                chunk_id=f"{short}_c{idx:05d}",
                source=short,
                source_file=file_path.name,
                section=breadcrumb,
                position=idx,
                text=full_text,
            )
            all_chunks.append(chunk)

    if not all_chunks:
        print("[ingest] No chunks produced.")
        return

    total = len(all_chunks)
    print(f"\n[ingest] Total: {total} chunks across {len(files)} file(s). Embedding...")
    print(f"         (this may take a while for large corpora)")

    texts = [c.text for c in all_chunks]
    embeddings = embed_texts(texts)

    print(f"[ingest] Building FAISS index (dim={embeddings.shape[1]}, n={total})...")
    index = build_index(embeddings)

    import faiss
    faiss.write_index(index, str(output_path / "index.faiss"))

    metadata = [c.to_dict() for c in all_chunks]
    with open(output_path / "chunks.json", "w") as f:
        json.dump(metadata, f, indent=2)

    np.save(str(output_path / "embeddings.npy"), embeddings)

    # Write a manifest so agents know what's in the corpus
    manifest = {
        "sources": {},
        "total_chunks": total,
        "embedding_model": os.environ.get("EMBED_MODEL", "all-mpnet-base-v2"),
        "chunk_tokens": CHUNK_TOKENS,
    }
    for c in all_chunks:
        if c.source not in manifest["sources"]:
            manifest["sources"][c.source] = {
                "file": c.source_file,
                "chunks": 0,
            }
        manifest["sources"][c.source]["chunks"] += 1

    with open(output_path / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n[ingest] Done.")
    print(f"         {total} chunks, dim={embeddings.shape[1]}")
    print(f"         Sources:")
    for src, info in manifest["sources"].items():
        print(f"           {src}: {info['chunks']} chunks")
    print(f"         Index: {output_path}/index.faiss")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest corpus into FAISS index (math-aware chunking)"
    )
    parser.add_argument("input_dir", help="Directory containing PDFs/text files")
    parser.add_argument("--output", default="corpus/index", help="Output directory for index")
    args = parser.parse_args()
    ingest(args.input_dir, args.output)


if __name__ == "__main__":
    main()
