"""curate US-002 episode 기록 계약 테스트.

WHY: curate 실행(audit/distill/lifecycle)이 끝나면 운영 이력을 episode 로 남겨야
한다(PRD US-002 — 4 배선점 중 curate; ingest·express·wiki_app 는 이미 done).
기록은 **fail-soft** — episode 실패가 curate 메인 경로를 못 깨뜨린다.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402
import episode  # noqa: E402


def _results():
    audit = {"orphans": [{"path": "wiki/a.md"}], "stale_links": [], "contradictions": []}
    distilled = ["wiki/b.md", "wiki/c.md"]
    lifecycle = {"archive": [{"path": "wiki/d.md"}], "delete": [], "rescued": [{"path": "wiki/e.md"}]}
    return audit, distilled, lifecycle


def test_curate_episode_record_is_valid_with_counts():
    audit, distilled, lifecycle = _results()
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    rec = curate._curate_episode_record("all", audit, distilled, lifecycle, now=now)
    assert rec["task_type"] == "curate"
    assert rec["outputs"]["orphans"] == 1
    assert rec["outputs"]["distill_queued"] == 2
    assert rec["outputs"]["archive_candidates"] == 1
    assert rec["outputs"]["rescued"] == 1


def test_curate_episode_record_passes_episode_schema(tmp_path):
    audit, distilled, lifecycle = _results()
    rec = curate._curate_episode_record("audit", audit, distilled, lifecycle)
    episode.append(rec, episodes_dir=tmp_path)  # 스키마 위반 시 raise
    got = episode.read_recent(task_type="curate", episodes_dir=tmp_path)
    assert len(got) == 1 and got[0]["task_type"] == "curate"


def test_record_curate_episode_is_fail_soft(monkeypatch):
    # episode.append 가 터져도 curate 흐름은 예외 전파 안 함(메인 경로 보호).
    def boom(*a, **k):
        raise RuntimeError("episode down")
    monkeypatch.setattr(curate.episode, "append", boom)
    audit, distilled, lifecycle = _results()
    curate._record_curate_episode("all", audit, distilled, lifecycle)  # must NOT raise
