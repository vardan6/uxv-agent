"""RAG document-identity tests: chunking, collection naming, manifest staleness,
and stable point replacement (TA3). Uses fakes only; no live embedding or Qdrant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import rag_service.ingest as ingest
from rag_service.chunker import chunk_markdown_file
from rag_service.collection import collection_name_for
from rag_service.manifest import compute_staleness, manifest_point_id


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_chunk_markdown_file_returns_empty_list_for_empty_file(tmp_path: Path) -> None:
    doc = tmp_path / "empty.md"
    doc.write_text("")

    assert chunk_markdown_file(doc, "empty.md") == []


def test_chunk_heading_path_reflects_nested_structure(tmp_path: Path) -> None:
    doc = tmp_path / "nested.md"
    doc.write_text("# Top\n\nintro text\n\n## Sub\n\nsub text\n")

    chunks = chunk_markdown_file(doc, "nested.md")

    heading_paths = [c.heading_path for c in chunks]
    assert "Top" in heading_paths
    assert "Top > Sub" in heading_paths
    for chunk in chunks:
        assert chunk.text.startswith(f"[{chunk.heading_path}]")


def test_chunk_splits_oversized_sections_within_token_bound(tmp_path: Path) -> None:
    paragraphs = [f"PARA{i} " + ("word " * 30) for i in range(5)]
    doc = tmp_path / "long.md"
    doc.write_text("# Doc\n\n" + "\n\n".join(paragraphs) + "\n")

    chunks = chunk_markdown_file(doc, "long.md", max_tokens=40, target_tokens=35)

    assert len(chunks) > 1
    assert all(chunk.heading_path == "Doc" for chunk in chunks)


def test_chunk_split_overlaps_boundary_paragraphs(tmp_path: Path) -> None:
    paragraphs = [f"PARA{i} " + ("word " * 30) for i in range(5)]
    doc = tmp_path / "overlap.md"
    doc.write_text("# Doc\n\n" + "\n\n".join(paragraphs) + "\n")

    chunks = chunk_markdown_file(doc, "overlap.md", max_tokens=40, target_tokens=35)

    shared = 0
    for a, b in zip(chunks, chunks[1:]):
        a_paras = {p for p in a.text.split("\n\n") if p.startswith("PARA")}
        b_paras = {p for p in b.text.split("\n\n") if p.startswith("PARA")}
        if a_paras & b_paras:
            shared += 1
    assert shared > 0


def test_chunk_preserves_non_ascii_text_and_hashes_deterministically(tmp_path: Path) -> None:
    doc = tmp_path / "unicode.md"
    doc.write_text("# 标题\n\nContenu en français avec des accents: éèàç 日本語テスト\n")

    first = chunk_markdown_file(doc, "unicode.md")
    second = chunk_markdown_file(doc, "unicode.md")

    assert "éèàç" in first[0].text
    assert "日本語テスト" in first[0].text
    assert [c.content_hash for c in first] == [c.content_hash for c in second]


# ---------------------------------------------------------------------------
# Collection naming
# ---------------------------------------------------------------------------


def test_collection_name_is_deterministic_across_calls() -> None:
    first = collection_name_for("qwen3-embedding-4b", 2560)
    second = collection_name_for("qwen3-embedding-4b", 2560)

    assert first == second


@pytest.mark.parametrize(
    ("model_id", "dim", "expected"),
    [
        ("qwen3-embedding-4b", 2560, "project_docs_v1_qwen3e4b_2560"),
        ("text-embedding-3-small", 1536, "project_docs_v1_te3s_1536"),
    ],
)
def test_collection_name_normalizes_model_ids_to_documented_slugs(
    model_id: str, dim: int, expected: str
) -> None:
    assert collection_name_for(model_id, dim) == expected


def test_collection_name_reflects_version_and_source() -> None:
    assert collection_name_for("m", 8, version=2, source="other_docs") == "other_docs_v2_m_8"


# ---------------------------------------------------------------------------
# Manifest staleness
# ---------------------------------------------------------------------------


def test_compute_staleness_reports_missing_when_manifest_absent(tmp_path: Path) -> None:
    result = compute_staleness(None, expected_model_id="m", expected_dim=8, docs_dir=tmp_path)

    assert result == "missing"


def test_compute_staleness_reports_model_mismatch_on_model_or_dim_change(tmp_path: Path) -> None:
    manifest = {
        "model_id": "other-model",
        "dim": 8,
        "last_ingest_at": datetime.now(timezone.utc).isoformat(),
    }

    result = compute_staleness(manifest, expected_model_id="m", expected_dim=8, docs_dir=tmp_path)

    assert result == "model_mismatch"


def test_compute_staleness_reports_stale_when_a_doc_changes_after_ingest(tmp_path: Path) -> None:
    ingest_time = datetime.now(timezone.utc) - timedelta(hours=1)
    manifest = {"model_id": "m", "dim": 8, "last_ingest_at": ingest_time.isoformat()}
    (tmp_path / "a.md").write_text("changed after ingest")

    result = compute_staleness(manifest, expected_model_id="m", expected_dim=8, docs_dir=tmp_path)

    assert result == "stale"


def test_compute_staleness_reports_up_to_date_when_docs_are_unchanged(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("unchanged")
    ingest_time = datetime.now(timezone.utc) + timedelta(hours=1)
    manifest = {"model_id": "m", "dim": 8, "last_ingest_at": ingest_time.isoformat()}

    result = compute_staleness(manifest, expected_model_id="m", expected_dim=8, docs_dir=tmp_path)

    assert result == "up_to_date"


def test_manifest_point_id_is_stable_per_collection_and_unique_across_collections() -> None:
    assert manifest_point_id("collection-a") == manifest_point_id("collection-a")
    assert manifest_point_id("collection-a") != manifest_point_id("collection-b")


# ---------------------------------------------------------------------------
# Stable point replacement across reruns (fake Qdrant client)
# ---------------------------------------------------------------------------


class _FakePoint:
    def __init__(self, point_id: str, payload: dict) -> None:
        self.id = point_id
        self.payload = payload


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.points: dict[str, dict] = {}

    def scroll(self, collection_name, scroll_filter=None, with_payload=True, with_vectors=False, limit=256, offset=None):
        return [_FakePoint(pid, payload) for pid, payload in self.points.items()], None

    def delete(self, collection_name, points_selector) -> None:
        for point_id in points_selector.points:
            self.points.pop(point_id, None)

    def upsert(self, collection_name, points) -> None:
        for point in points:
            self.points[point.id] = point.payload


@pytest.fixture
def fake_ingest_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embed_all(texts: list[str], params: ingest.IngestParams):
        return [[0.0] * params.dim for _ in texts], 0

    monkeypatch.setattr(ingest, "_embed_all", fake_embed_all)
    monkeypatch.setattr(ingest, "_sparse_encode", lambda texts: None)


def _ingest(client: _FakeQdrantClient, params: ingest.IngestParams, file_path: Path, rel_path: str) -> dict:
    stats = {"upserted": 0, "skipped": 0, "deleted": 0, "tokens": 0}
    ingest._ingest_file(client, file_path, rel_path, params, dry_run=False, stats=stats)
    return stats


def test_point_ids_stay_stable_when_a_chunks_content_changes(
    fake_ingest_backends: None, tmp_path: Path
) -> None:
    params = ingest.IngestParams(base_url="x", model_id="m", api_key="k", dim=4, collection="c")
    client = _FakeQdrantClient()
    doc = tmp_path / "doc.md"
    doc.write_text("# A\n\ncontent one\n\n# B\n\ncontent two\n")

    _ingest(client, params, doc, "doc.md")
    ids_before = set(client.points.keys())
    assert len(ids_before) == 2

    doc.write_text("# A\n\ncontent one CHANGED\n\n# B\n\ncontent two\n")
    stats = _ingest(client, params, doc, "doc.md")

    assert set(client.points.keys()) == ids_before
    assert stats["upserted"] == 1
    assert stats["skipped"] == 1


def test_removed_chunks_delete_their_points_and_leave_the_rest(
    fake_ingest_backends: None, tmp_path: Path
) -> None:
    params = ingest.IngestParams(base_url="x", model_id="m", api_key="k", dim=4, collection="c")
    client = _FakeQdrantClient()
    doc = tmp_path / "doc.md"
    doc.write_text("# A\n\ncontent one\n\n# B\n\ncontent two\n")
    _ingest(client, params, doc, "doc.md")
    ids_before = set(client.points.keys())

    doc.write_text("# A\n\ncontent one\n")
    stats = _ingest(client, params, doc, "doc.md")

    assert len(client.points) == 1
    assert client.points.keys() < ids_before
    assert stats["deleted"] == 1
    assert stats["upserted"] == 0
