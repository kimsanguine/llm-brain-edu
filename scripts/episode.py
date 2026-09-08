#!/usr/bin/env python3
"""episode.py — append-only 에피소드 원장 (PRD US-001).

5층 메모리 OS 의 ② "턴 이후 쓰기" 기질. 각 실행(ingest·express·curate·ai_answer)이
구조화된 episode 레코드를 월별 샤드 episodes/YYYY-MM.jsonl 에 append 한다.

헬퍼는 **fail-loud**(스키마 위반 = EpisodeSchemaError). *호출측* 은 try/except 로
감싸 warn+continue 하여 메인 명령 경로를 **fail-soft** 로 유지한다(Phase 1, US-002 AC).
episodes/ 는 repo 루트(wiki/ 밖)이며 .gitignore 로 격리된다 — OKF 누출 방지.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

EPISODES_DIR = Path(__file__).parent.parent / "episodes"

# (key, expected_type) — PRD US-001 필수 키.
_SCHEMA: tuple[tuple[str, type | tuple[type, ...]], ...] = (
    ("timestamp", str),
    ("task_type", str),
    ("user_goal", str),
    ("inputs", dict),
    ("read_pages", list),
    ("procedures_used", list),
    ("outputs", dict),
    ("status", str),
    ("notes", str),
)


class EpisodeSchemaError(ValueError):
    """episode 레코드가 필수 키·타입·timestamp 계약을 위반. 조용한 적재 금지(fail-loud)."""


def _shard_name(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError) as exc:
        raise EpisodeSchemaError(f"timestamp 파싱 실패: {timestamp!r}") from exc
    return dt.strftime("%Y-%m")


def _validate(record: dict) -> None:
    for key, typ in _SCHEMA:
        if key not in record:
            raise EpisodeSchemaError(f"필수 키 누락: {key!r}")
        if not isinstance(record[key], typ):
            raise EpisodeSchemaError(
                f"{key!r} 타입 오류: {type(record[key]).__name__} (기대 {typ})"
            )


def append(record: dict, episodes_dir: Path = EPISODES_DIR) -> None:
    """검증 통과 시 월별 샤드에 1줄 append. 위반 시 EpisodeSchemaError(쓰기 0)."""
    _validate(record)
    shard = _shard_name(record["timestamp"])  # bad timestamp 도 쓰기 전에 fail-loud
    try:
        line = json.dumps(record, ensure_ascii=False, sort_keys=False)
    except TypeError as exc:
        # inputs/outputs 에 Path·datetime·set 등 직렬화 불가 값 → 모든 거부를
        # EpisodeSchemaError 로 통일(호출측 except EpisodeSchemaError fail-soft 작동).
        # FS 부작용(mkdir) 전에 raise → 쓰기 0.
        raise EpisodeSchemaError(f"직렬화 불가 값 포함(inputs/outputs 등): {exc}") from exc
    episodes_dir = Path(episodes_dir)
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with (episodes_dir / f"{shard}.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_recent(
    task_type: str | None = None,
    topic: str | None = None,
    limit: int = 10,
    episodes_dir: Path = EPISODES_DIR,
) -> list[dict]:
    """최신 샤드부터 읽어 timestamp desc 결정적 정렬 + 필터. 최대 limit 개.

    깨진 줄(JSON 오류·non-dict)은 skip 한다 — 원장 read 는 견고해야 하며 한 줄
    손상이 전체 read 를 막으면 안 된다(append 측의 fail-loud 와 분리).
    """
    episodes_dir = Path(episodes_dir)
    if not episodes_dir.exists():
        return []
    records: list[dict] = []
    for shard in sorted(episodes_dir.glob("*.jsonl"), reverse=True):  # 최신 달 먼저
        for raw in shard.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if task_type is not None and rec.get("task_type") != task_type:
                continue
            if topic is not None and not _topic_match(rec, topic):
                continue
            records.append(rec)
    records.sort(key=_sort_key, reverse=True)  # 실제 시각 기준(동률은 인코딩 순서로 결정적)
    return records[:limit]


def _topic_match(record: dict, topic: str) -> bool:
    hay = (
        str(record.get("user_goal", ""))
        + " "
        + json.dumps(record.get("inputs", {}), ensure_ascii=False)
    ).lower()
    return topic.lower() in hay


def _sort_key(record: dict) -> datetime:
    """timestamp 를 *실제 시각* 으로 파싱해 정렬 키로. 문자열 정렬은 오프셋 다른 TZ
    (UTC vs +09:00)를 오정렬한다. 파싱 불가/naive 는 안전 정규화(aware 와 비교 가능)."""
    ts = record.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)  # 깨진 ts 는 가장 과거로
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # naive → UTC 가정
    return dt
