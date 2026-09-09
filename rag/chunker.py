"""Header-aware markdown chunker for project_docs ingestion (ADR 0028 §6)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import tiktoken

_ENCODER: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def _tokens(text: str) -> int:
    return len(_encoder().encode(text))


def _heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


def _heading_text(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", line).strip()


@dataclass
class Chunk:
    text: str
    path: str
    heading_path: str
    chunk_index: int
    content_hash: str


def _make_chunk(text: str, path: str, heading_path: str, index: int) -> Chunk:
    stripped = text.strip()
    content_hash = hashlib.sha256(stripped.encode()).hexdigest()
    return Chunk(
        text=stripped,
        path=path,
        heading_path=heading_path,
        chunk_index=index,
        content_hash=content_hash,
    )


def _iter_sections(lines: list[str]) -> Iterator[tuple[list[str], list[str]]]:
    """Yield (heading_stack, body_lines) for each section delimited by headings."""
    heading_stack: list[str] = []
    body: list[str] = []

    for line in lines:
        level = _heading_level(line)
        if level:
            if body or not heading_stack:
                yield list(heading_stack), list(body)
                body = []
            text = _heading_text(line)
            # Trim stack to the parent level, then push this heading.
            heading_stack = heading_stack[: level - 1] + [text]
            body.append(line)
        else:
            body.append(line)

    if body:
        yield list(heading_stack), list(body)


def _split_paragraphs(body: str, max_tokens: int, overlap_lines: int = 2) -> list[str]:
    """Split oversized body text by double-newline paragraphs with minimal overlap."""
    paragraphs = re.split(r"\n{2,}", body)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        t = _tokens(para)
        if current and current_tokens + t > max_tokens:
            chunks.append("\n\n".join(current))
            # Carry last `overlap_lines` paragraphs into the next chunk.
            current = current[-overlap_lines:] if overlap_lines else []
            current_tokens = sum(_tokens(p) for p in current)
        current.append(para)
        current_tokens += t

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def chunk_markdown_file(
    file_path: Path,
    rel_path: str,
    *,
    max_tokens: int = 1500,
    target_tokens: int = 1000,
) -> list[Chunk]:
    """Chunk a markdown file into embedding-ready pieces.

    Each chunk's text is prefixed with its heading path so the embedding
    captures structural context even without surrounding sections.
    """
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    chunks: list[Chunk] = []
    index = 0

    for heading_stack, body_lines in _iter_sections(lines):
        body = "".join(body_lines).strip()
        if not body:
            continue

        heading_path = " > ".join(heading_stack) if heading_stack else rel_path
        prefix = f"[{heading_path}]\n\n"
        embedded_text = prefix + body

        if _tokens(embedded_text) <= max_tokens:
            chunks.append(_make_chunk(embedded_text, rel_path, heading_path, index))
            index += 1
        else:
            for sub in _split_paragraphs(body, max_tokens=target_tokens):
                if sub:
                    chunks.append(_make_chunk(prefix + sub, rel_path, heading_path, index))
                    index += 1

    return chunks
