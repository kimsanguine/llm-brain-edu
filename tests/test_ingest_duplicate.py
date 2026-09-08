"""is_duplicate() + hard dedup 계약 테스트 — v0.3.0 재배선 후 동작 기준.

v0.2.0까지 is_duplicate()는 저장 후 호출되고 반환값(bool)이 버려졌다(soft).
v0.3.0 WS-4에서 아래 계약으로 재배선됐다:

- is_duplicate(file) -> (is_dup, target_slug, score)
  · 판정만 담당(출력 없음). 출력·차단은 호출부(main) 책임.
  · target_slug = 일치한 index.md wikilink의 원본 표기. score: 완전일치=1.0.
  · slug 정규화(날짜 접두사 제거·`_`→`-`·소문자)는 v0.2 동작 그대로.
- main()은 저장 **전**에 예정 경로(_planned_*_path)로 판정한다.
  · 중복이면 저장 보류 + [[target_slug]] 강화 라우팅 제안 + exit 0 (차단≠오류).
  · 차단 시 raw 파일이 디스크에 남지 않고 episode도 기록되지 않는다.
  · --force 시에만 기존처럼 저장 강행(경고 출력 + episode 기록).
  · --url 경로도 slug가 URL 파생이므로 fetch **없이** 차단된다.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import episode
import ingest
from ingest import is_duplicate


@pytest.fixture
def tmp_brain(tmp_path, monkeypatch):
    """ingest의 WIKI_ROOT를 tmp_path로 격리한다 (test_ingest_delta.py 패턴)."""
    wiki_root = tmp_path / "brain"
    raw_dir = wiki_root / "raw"
    raw_dir.mkdir(parents=True)
    monkeypatch.setattr(ingest, "WIKI_ROOT", wiki_root)
    monkeypatch.setattr(ingest, "RAW_DIR", raw_dir)
    monkeypatch.setattr(ingest, "STATE_FILE", wiki_root / ".ingest_state.json")
    return wiki_root


def _write_index(wiki_root: Path, body: str) -> None:
    (wiki_root / "index.md").write_text(body)


def _capture_episode(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(episode, "append", lambda record, **kw: captured.update(record=record))
    return captured


# ---------------------------------------------------------------------------
# ① 동일 slug 중복 감지 → (True, 원본 slug, 1.0)
# ---------------------------------------------------------------------------

def test_duplicate_slug_returns_true(tmp_brain):
    """index.md에 같은 slug의 [[wikilink]]가 있으면 (True, slug, 1.0)."""
    _write_index(tmp_brain, "# Index\n\n- [[agent-memory]]\n")
    file = tmp_brain / "raw" / "agent-memory.md"
    assert is_duplicate(file) == (True, "agent-memory", 1.0)


def test_duplicate_with_alias_wikilink_returns_true(tmp_brain):
    """[[slug|표시명]] alias 형태 wikilink도 slug 부분으로 매칭한다."""
    _write_index(tmp_brain, "- [[agent-memory|에이전트 메모리]]\n")
    file = tmp_brain / "raw" / "agent-memory.md"
    assert is_duplicate(file) == (True, "agent-memory", 1.0)


# ---------------------------------------------------------------------------
# ② 비중복 → (False, None, 0.0)
# ---------------------------------------------------------------------------

def test_non_duplicate_returns_false(tmp_brain):
    _write_index(tmp_brain, "- [[agent-memory]]\n- [[rag-pipeline]]\n")
    file = tmp_brain / "raw" / "totally-new-topic.md"
    assert is_duplicate(file) == (False, None, 0.0)


# ---------------------------------------------------------------------------
# ③ slug 정규화: 날짜 접두사 제거 · 언더스코어→하이픈 · 소문자 (v0.2 동작 유지)
# ---------------------------------------------------------------------------

def test_date_prefix_is_stripped_before_compare(tmp_brain):
    """파일명의 YYYY-MM-DD- 접두사는 slug 비교 전에 제거된다."""
    _write_index(tmp_brain, "- [[agent-memory]]\n")
    file = tmp_brain / "raw" / "2026-07-04-agent-memory.md"
    assert is_duplicate(file)[0] is True


def test_underscore_normalized_to_hyphen(tmp_brain):
    """파일명 언더스코어는 하이픈으로 정규화된다."""
    _write_index(tmp_brain, "- [[agent-memory]]\n")
    file = tmp_brain / "raw" / "agent_memory.md"
    assert is_duplicate(file)[0] is True


def test_case_insensitive_returns_original_index_slug(tmp_brain):
    """비교는 소문자 기준이되, target_slug는 index.md의 원본 표기를 반환한다."""
    _write_index(tmp_brain, "- [[Agent-Memory]]\n")
    file = tmp_brain / "raw" / "AGENT-MEMORY.md"
    assert is_duplicate(file) == (True, "Agent-Memory", 1.0)


def test_all_normalizations_combined(tmp_brain):
    """날짜 접두사 + 언더스코어 + 대문자가 겹쳐도 정규화 후 매칭한다."""
    _write_index(tmp_brain, "- [[agent-memory]]\n")
    file = tmp_brain / "raw" / "2026-01-01-Agent_Memory.md"
    assert is_duplicate(file) == (True, "agent-memory", 1.0)


def test_path_containing_wikilink_is_not_matched(tmp_brain):
    """(v0.2 동작 유지) `/`가 든 wikilink([[concepts/agent-memory]])는
    regex `[^\\]|/]`에서 제외돼 slug로 추출되지 않는다 → 중복 미감지."""
    _write_index(tmp_brain, "- [[concepts/agent-memory]]\n")
    file = tmp_brain / "raw" / "agent-memory.md"
    assert is_duplicate(file) == (False, None, 0.0)


# ---------------------------------------------------------------------------
# ④ index.md 부재 / 빈 파일 / 판정 순수성
# ---------------------------------------------------------------------------

def test_missing_index_returns_false(tmp_brain):
    """index.md가 없으면 조기 (False, None, 0.0) (예외 없음)."""
    file = tmp_brain / "raw" / "agent-memory.md"
    assert is_duplicate(file) == (False, None, 0.0)


def test_empty_index_returns_false(tmp_brain):
    """index.md가 빈 파일이면 wikilink 0개 → 비중복."""
    _write_index(tmp_brain, "")
    file = tmp_brain / "raw" / "agent-memory.md"
    assert is_duplicate(file) == (False, None, 0.0)


def test_is_duplicate_prints_nothing(tmp_brain, capsys):
    """v0.3.0: 판정 함수는 출력하지 않는다 — 메시지는 main()의 책임."""
    _write_index(tmp_brain, "- [[agent-memory]]\n")
    assert is_duplicate(tmp_brain / "raw" / "agent-memory.md")[0] is True
    assert is_duplicate(tmp_brain / "raw" / "new-topic.md")[0] is False
    assert capsys.readouterr().out == ""


def test_file_itself_need_not_exist(tmp_brain):
    """is_duplicate는 파일명(stem)만 보므로 대상 파일이 디스크에 없어도 동작한다
    — 저장 전 '예정 경로' 판정이 성립하는 근거."""
    _write_index(tmp_brain, "- [[agent-memory]]\n")
    ghost = tmp_brain / "raw" / "agent-memory.md"  # 미생성
    assert not ghost.exists()
    assert is_duplicate(ghost)[0] is True


# ---------------------------------------------------------------------------
# ⑤ hard-block (main 수준): 저장 보류 · exit 0 · raw/episode 미생성
# ---------------------------------------------------------------------------

def test_main_note_duplicate_blocks_save(tmp_brain, monkeypatch, capsys):
    """동일 슬러그 노트 재투입 시 저장 보류 — raw 파일 없음·episode 없음·exit 0."""
    # note 슬러그는 HHMM-note (분 경계 레이스 방지로 현재·다음 분 둘 다 등록)
    now = datetime.now()
    slugs = "\n".join(
        f"- [[{t.strftime('%H%M')}-note]]"
        for t in (now, now + timedelta(minutes=1))
    )
    _write_index(tmp_brain, slugs + "\n")
    captured = _capture_episode(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--note", "중복 노트"])

    with pytest.raises(SystemExit) as exc:
        ingest.main()

    assert exc.value.code == 0  # 차단은 오류가 아님
    assert list((tmp_brain / "raw").rglob("*.md")) == []  # raw 미저장
    assert captured == {}  # episode 미기록
    out = capsys.readouterr().out
    assert "[중복 차단]" in out
    assert "--force" in out


def test_main_blocked_message_suggests_routing(tmp_brain, monkeypatch, capsys):
    """차단 메시지는 기존 노드 [[target_slug]] 강화 라우팅을 제안한다 (자동 병합 없음)."""
    src = tmp_brain / "src-agent-memory.md"
    src.write_text("dup content")
    date_str = datetime.now().strftime("%Y-%m-%d")
    _write_index(tmp_brain, "- [[src-agent-memory]]\n")
    _capture_episode(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--file", str(src)])

    with pytest.raises(SystemExit) as exc:
        ingest.main()

    assert exc.value.code == 0
    assert not (tmp_brain / "raw" / "docs" / f"{date_str}-src-agent-memory.md").exists()
    assert "[[src-agent-memory]]" in capsys.readouterr().out


def test_main_url_duplicate_blocks_before_fetch(tmp_brain, monkeypatch, capsys):
    """--url 경로: slug가 URL 파생이므로 fetch 없이 저장 전 차단된다."""
    def _no_fetch(*args, **kwargs):
        raise AssertionError("차단됐어야 하므로 httpx.get이 호출되면 안 된다")
    monkeypatch.setattr(ingest.httpx, "get", _no_fetch)
    _write_index(tmp_brain, "- [[example-com-agent-memory]]\n")
    _capture_episode(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--url", "https://example.com/agent-memory"])

    with pytest.raises(SystemExit) as exc:
        ingest.main()

    assert exc.value.code == 0
    assert list((tmp_brain / "raw").rglob("*.md")) == []
    assert "[중복 차단]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# ⑥ --force: 기존처럼 저장 강행 (경고 출력 + episode 기록)
# ---------------------------------------------------------------------------

def test_main_force_saves_despite_duplicate(tmp_brain, monkeypatch, capsys):
    src = tmp_brain / "src-agent-memory.md"
    src.write_text("dup content")
    date_str = datetime.now().strftime("%Y-%m-%d")
    _write_index(tmp_brain, "- [[src-agent-memory]]\n")
    captured = _capture_episode(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--file", str(src), "--force"])

    with pytest.raises(SystemExit) as exc:  # 미처리 파일 존재 → exit 1 (기존 계약)
        ingest.main()

    assert exc.value.code == 1
    dst = tmp_brain / "raw" / "docs" / f"{date_str}-src-agent-memory.md"
    assert dst.exists()  # 저장 강행됨
    assert captured["record"]["task_type"] == "ingest_file"  # episode 기록됨
    assert "--force로 저장을 강행" in capsys.readouterr().out


def test_main_non_duplicate_saves_normally(tmp_brain, monkeypatch, capsys):
    """비중복이면 --force 없이도 기존과 동일하게 저장된다."""
    _write_index(tmp_brain, "- [[other-topic]]\n")
    captured = _capture_episode(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--note", "새 주제"])

    with pytest.raises(SystemExit) as exc:
        ingest.main()

    assert exc.value.code == 1  # 미처리 파일 존재 (기존 계약)
    assert len(list((tmp_brain / "raw" / "notes").glob("*.md"))) == 1
    assert captured["record"]["task_type"] == "ingest_note"
    assert "[중복 차단]" not in capsys.readouterr().out
