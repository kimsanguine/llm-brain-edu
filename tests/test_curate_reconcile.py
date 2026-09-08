"""test_curate_reconcile.py — v0.3.1 Wave 6: curate 가 reconcile 순수 코어를 배선한다.

WHY (이 테스트가 인코딩하는 의도):
  1. run_audit 은 가장 최근 raw 근거 × 기존 페이지를 reconcile.detect_contradiction_
     candidates 로 대조해 모순 *후보* 를 표면화한다(결정적·보수적). 화해 서술은 아님.
  2. 후보가 있으면 wiki/contradiction_queue.md 에 distill_queue 동일 체크박스 패턴으로
     직렬화한다 (LLM Step 이 소비).
  3. **후보 0이면 큐 미생성** — 오탐 시 반론 남발 방지(정밀도 우선).
  4. contradiction_queue.md 는 find_all_wiki_pages 정규 스캔에서 격리된다.
  5. write_report 에 모순 후보 카운트 섹션이 들어간다.

tmp_path self-contained (claude CLI 불요).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402


def _fm_block(**fields) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"{k}: [" + ", ".join(str(x) for x in v) + "]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")
    return wiki


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# 같은 주제(GPU 학습)에 상반 극("가능"↔"불가능")을 담은 페이지·raw 쌍.
_PAGE_CLAIM = _fm_block(title="GPU 학습 최적화", type="concept",
                        tags=["gpu", "training"], created="2026-06-01") \
    + "\n\n# GPU 학습\n\n분산 학습은 가능하다.\n"
_RAW_CONTRA = _fm_block(title="GPU 학습 최적화", tags=["gpu", "training"]) \
    + "\n\n분산 학습은 불가능하다.\n"
_RAW_AGREE = _fm_block(title="GPU 학습 최적화", tags=["gpu", "training"]) \
    + "\n\n분산 학습은 가능하다.\n"


def test_audit_surfaces_contradiction_and_writes_queue(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/gpu-training.md", _PAGE_CLAIM)
    _write(tmp_path, "raw/clippings/2026-07-04-gpu.md", _RAW_CONTRA)

    audit = curate.run_audit(curate.find_all_wiki_pages())

    assert len(audit["contradictions"]) == 1
    cand = audit["contradictions"][0]
    assert cand.existing_slug == "gpu-training"
    assert cand.signal == "가능↔불가능"

    queue = (wiki / "contradiction_queue.md").read_text(encoding="utf-8")
    assert "- [ ] [[gpu-training]] ↔ raw/clippings/2026-07-04-gpu.md" in queue
    assert "기존 주장:" in queue and "신규 근거:" in queue


def test_no_candidates_no_queue_file(monkeypatch, tmp_path):
    """단순 보강(상반 신호 없음)이면 큐를 만들지 않는다 — 보수적."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/gpu-training.md", _PAGE_CLAIM)
    _write(tmp_path, "raw/clippings/2026-07-04-gpu.md", _RAW_AGREE)

    audit = curate.run_audit(curate.find_all_wiki_pages())

    assert audit["contradictions"] == []
    assert not (wiki / "contradiction_queue.md").exists()


def test_no_raw_no_queue(monkeypatch, tmp_path):
    """raw/ 부재 시 크래시 없이 후보 0 + 큐 미생성."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/gpu-training.md", _PAGE_CLAIM)

    audit = curate.run_audit(curate.find_all_wiki_pages())

    assert audit["contradictions"] == []
    assert not (wiki / "contradiction_queue.md").exists()


def test_contradiction_queue_excluded_from_scan(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/normal.md", _PAGE_CLAIM)
    _write(wiki, "contradiction_queue.md", "# Contradiction Queue\n- [ ] [[normal]]\n")

    rels = {p.relative_to(wiki).as_posix() for p in curate.find_all_wiki_pages()}
    assert rels == {"concepts/normal.md"}


def test_report_contains_contradiction_section(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/gpu-training.md", _PAGE_CLAIM)
    _write(tmp_path, "raw/clippings/2026-07-04-gpu.md", _RAW_CONTRA)

    audit = curate.run_audit(curate.find_all_wiki_pages())
    curate.write_report(audit, [], {})

    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "### 모순 후보 (1개)" in report
    assert "[[gpu-training]] ↔ raw/clippings/2026-07-04-gpu.md" in report
    assert "wiki/contradiction_queue.md" in report


def test_curate_episode_counts_contradictions():
    audit = {"orphans": [], "stale_links": [],
             "contradictions": [object(), object()]}
    rec = curate._curate_episode_record("audit", audit, [], {},
                                        now=datetime(2026, 7, 4))
    assert rec["outputs"]["contradictions"] == 2
