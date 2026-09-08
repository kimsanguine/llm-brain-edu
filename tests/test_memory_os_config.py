"""Phase 0 구성 단언 — OKF 누출 방어 + episode 스키마 예시 무결성.

WHY (이 테스트가 인코딩하는 의도):
  1. episodes/·procedures/ 의 OKF 누출 방어는 "okf 가 wiki/ 만 스캔"이라는 구조적
     격리 + exclude_paths 명시의 2중망이다. export *결과*뿐 아니라 *설정 값 자체*를
     단언해야 한다(Codex C8) — 누가 exclude_paths 를 건드리거나 폴더를 옮겨도 회귀가
     빨갛게 잡힌다. 게이트는 규칙형이라 명시 규칙만이 누출을 막는다.
  2. 커밋되는 examples/episode-schema-example.jsonl 은 episode 스키마와 정합해야
     한다 — 문서·테스트용 예시가 스키마 drift 로 거짓이 되는 것을 막는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import episode  # noqa: E402


def test_okf_exclude_paths_seal_episodes_and_procedures():
    cfg = yaml.safe_load((_REPO_ROOT / "schema" / "okf_export.yaml").read_text(encoding="utf-8"))
    excl = cfg.get("exclude_paths", [])
    assert "episodes/**" in excl  # 방어 이중망 (wiki/ 밖이라도 명시)
    assert "procedures/**" in excl


def test_gitignore_isolates_episodes():
    gi = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() == "episodes/" for line in gi)  # 운영 맥락 누출 차단


def test_procedures_git_tracked_but_okf_excluded():
    # 결정(2026-06-27): procedures = 공유 가능 워크플로우 → git 추적(US-004 예시 커밋),
    # 단 OKF 공개 번들엔 제외(git ≠ OKF 공개). episodes(사적 로그)와 의도적 비대칭.
    gi = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(line.strip() == "procedures/" for line in gi)  # git-tracked
    cfg = yaml.safe_load((_REPO_ROOT / "schema" / "okf_export.yaml").read_text(encoding="utf-8"))
    assert "procedures/**" in cfg.get("exclude_paths", [])  # OKF 제외 유지


def test_episode_schema_example_is_valid(tmp_path):
    path = _REPO_ROOT / "examples" / "episode-schema-example.jsonl"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "예시가 비어 있으면 안 됨"
    for line in lines:
        rec = json.loads(line)
        episode.append(rec, episodes_dir=tmp_path)  # 스키마 위반 시 EpisodeSchemaError
