import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import ingest
from ingest import (
    snapshot_graph,
    run_delta_pipeline,
    ingest_file,
    find_unprocessed,
    mark_done,
    main,
    _get_resonance,
)


@pytest.fixture
def tmp_wiki(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    return wiki_dir


@pytest.fixture
def tmp_raw(tmp_path, monkeypatch):
    """ingest의 RAW_DIR/WIKI_ROOT/STATE_FILE를 tmp_path로 격리한다.

    ingest_file()는 RAW_DIR에 복사하고, find_unprocessed()/_get_resonance()는
    같은 RAW_DIR를 읽으므로 self-contained 검증이 가능하다.
    """
    wiki_root = tmp_path / "brain"
    raw_dir = wiki_root / "raw"
    raw_dir.mkdir(parents=True)
    monkeypatch.setattr(ingest, "WIKI_ROOT", wiki_root)
    monkeypatch.setattr(ingest, "RAW_DIR", raw_dir)
    monkeypatch.setattr(ingest, "STATE_FILE", wiki_root / ".ingest_state.json")
    return wiki_root


def test_snapshot_graph_copies_file(tmp_wiki):
    """graph.json이 있으면 .graph_prev.json으로 복사해야 한다."""
    graph = {"nodes": [], "links": []}
    (tmp_wiki / "graph.json").write_text(json.dumps(graph))

    snapshot_graph(tmp_wiki)
    prev_path = tmp_wiki / ".graph_prev.json"
    assert prev_path.exists()
    assert json.loads(prev_path.read_text()) == graph


def test_snapshot_graph_no_op_when_missing(tmp_wiki):
    """graph.json이 없으면 오류 없이 종료해야 한다."""
    snapshot_graph(tmp_wiki)
    assert not (tmp_wiki / ".graph_prev.json").exists()


def test_run_delta_pipeline_first_run(tmp_wiki, graph_stub):
    """
    .graph_prev.json이 없고 graph.json이 있으면
    전체 page 노드를 신규로 취급해야 한다.
    """
    (tmp_wiki / "graph.json").write_text(json.dumps(graph_stub))
    result = run_delta_pipeline(tmp_wiki)
    assert result is not None
    new_ids = {n["id"] for n in result["new_nodes"]}
    assert "alpha" in new_ids
    assert "beta" in new_ids


def test_run_delta_pipeline_no_change(tmp_wiki, graph_stub):
    """prev == current이면 None을 반환해야 한다."""
    same = json.dumps(graph_stub)
    (tmp_wiki / "graph.json").write_text(same)
    (tmp_wiki / ".graph_prev.json").write_text(same)
    result = run_delta_pipeline(tmp_wiki)
    assert result is None


def test_run_delta_pipeline_no_graph_file(tmp_wiki):
    """graph.json이 없으면 None을 반환해야 한다."""
    result = run_delta_pipeline(tmp_wiki)
    assert result is None


# ── resonance 보존 (버그 9) ──────────────────────────────────
# WHY: --resonance high로 캡처한 .md/.txt가 --priority-only(=resonance high만)
# 목록에 잡혀야 한다. 기존엔 md/txt는 shutil.copy2만 하고 resonance를
# 비-md/txt의 .extracted.md에만 기록해, 가장 흔한 TIL 포맷(markdown)의
# high 캡처가 조용히 누락됐다.


def test_ingest_md_resonance_high_is_persisted_and_prioritized(tmp_raw):
    """--file x.md --resonance high → resonance가 보존되고 priority-only에 잡힌다."""
    src = tmp_raw / "til.md"
    src.write_text("# TIL\n\n오늘 배운 것.\n")

    dst = ingest_file(src, resonance="high")

    # 복사본에서 resonance 조회가 high여야 한다 (읽는 쪽과 동일 경로).
    assert _get_resonance(dst) == "high"

    # priority-only 목록에 복사본이 포함돼야 한다.
    pending = find_unprocessed(priority_only=True)
    assert dst in pending


def test_ingest_txt_resonance_high_is_persisted_and_prioritized(tmp_raw):
    """.txt도 md와 동일하게 resonance 보존·우선순위 조회가 돼야 한다."""
    src = tmp_raw / "note.txt"
    src.write_text("그냥 평문 메모.\n")

    dst = ingest_file(src, resonance="high")

    assert _get_resonance(dst) == "high"
    pending = find_unprocessed(priority_only=True)
    assert dst in pending


def test_ingest_md_without_resonance_is_unchanged(tmp_raw):
    """resonance 미지정 시 동작 불변 — frontmatter 주입 없이 원본 복사, priority-only 제외."""
    body = "# TIL\n\n출처 없는 평범한 노트.\n"
    src = tmp_raw / "plain.md"
    src.write_text(body)

    dst = ingest_file(src, resonance=None)

    # resonance 미지정이므로 조회 결과 없음.
    assert _get_resonance(dst) is None
    # 원본 내용이 그대로여야 한다 (frontmatter를 임의 주입하지 않음).
    assert dst.read_text() == body
    # priority-only 목록에서 제외돼야 한다.
    pending = find_unprocessed(priority_only=True)
    assert dst not in pending


def test_ingest_md_with_existing_resonance_frontmatter_is_overridden(tmp_raw):
    """원본 frontmatter에 resonance가 있어도 --resonance 인자가 우선 반영돼야 한다."""
    src = tmp_raw / "had-low.md"
    src.write_text("---\ntitle: 기존\nresonance: low\n---\n\n본문\n")

    dst = ingest_file(src, resonance="high")

    assert _get_resonance(dst) == "high"
    pending = find_unprocessed(priority_only=True)
    assert dst in pending


# ── raw→ingest 파이프라인 계약 테스트 (QA 갭 #5c) ─────────────
# WHY: raw/ 소스 → ingest 탐지/상태관리/종료코드의 3대 계약이
# 회귀 없이 고정돼야 한다. run_daily.sh(현 OpenClaw cron)가
# ingest.py 종료 코드(미처리=1, 없음=0)로 LLM 호출 여부를 결정하므로,
# 이 계약이 깨지면 데일리 자동화가 조용히 오작동한다.
# SPEC.md "종료 코드 의미": 0=처리할 새 파일 없음 / 1=미처리 1개+.
# 이 테스트들은 현 ingest.py 동작을 *고정*하는 계약 테스트다.


def _write_raw(wiki_root: Path, rel: str, body: str) -> Path:
    """raw/ 하위 rel 경로에 샘플 파일을 생성하고 절대 경로를 반환한다."""
    f = wiki_root / "raw" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


# (a) 탐지 계약 — 샘플 raw 추가 → 미처리로 보고


def test_find_unprocessed_detects_new_raw_file(tmp_raw):
    """raw/에 새 지원 파일이 생기면 find_unprocessed()가 미처리로 보고한다."""
    sample = _write_raw(tmp_raw, "notes/sample.md", "# 샘플\n\n새 raw 노트.\n")

    pending = find_unprocessed()

    assert sample in pending


def test_find_unprocessed_ignores_unsupported_extension(tmp_raw):
    """지원 외 확장자(.png 등)는 미처리 목록에 포함하지 않는다 (현 동작 고정)."""
    _write_raw(tmp_raw, "notes/keep.md", "# 지원 형식\n")
    unsupported = _write_raw(tmp_raw, "notes/skip.png", "binary-ish")

    pending = find_unprocessed()

    assert unsupported not in pending
    assert all(p.suffix.lower() in ingest.SUPPORTED_EXTENSIONS for p in pending)


# (b) mark-done 계약 — 상태 기록 + 재탐지 시 제외


def test_mark_done_records_processed_and_excludes_on_redetect(tmp_raw):
    """--mark-done 상당 동작 → .ingest_state.json 기록 + 재탐지 제외."""
    sample = _write_raw(tmp_raw, "notes/done-me.md", "# 처리될 노트\n")
    rel = str(sample.relative_to(tmp_raw))

    # 처리 전: 미처리로 잡힌다.
    assert sample in find_unprocessed()

    mark_done()

    # .ingest_state.json에 WIKI_ROOT 상대경로로 기록돼야 한다.
    state_file = ingest.STATE_FILE
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert rel in state["processed"]

    # 재탐지 시 처리완료 파일은 제외된다.
    assert sample not in find_unprocessed()


def test_mark_done_then_new_file_is_still_detected(tmp_raw):
    """mark-done 이후 추가된 새 raw 파일은 다시 미처리로 잡혀야 한다 (델타 계약)."""
    first = _write_raw(tmp_raw, "notes/first.md", "# 첫 노트\n")
    mark_done()
    assert first not in find_unprocessed()

    second = _write_raw(tmp_raw, "notes/second.md", "# 둘째 노트\n")

    pending = find_unprocessed()
    assert second in pending
    assert first not in pending


# (c) 종료 코드 계약 — 미처리 있음→exit 1, 없음→exit 0
# main()의 실제 sys.exit(...) 경로를 in-process로 검증한다.
# (tmp_raw가 WIKI_ROOT/RAW_DIR/STATE_FILE를 tmp로 격리하므로
#  subprocess 없이도 self-contained로 동작 고정이 가능하다.)


def test_main_exits_1_when_unprocessed_present(tmp_raw, monkeypatch):
    """미처리 파일이 1개 이상이면 종료 코드 1 (SPEC 종료 코드 계약)."""
    _write_raw(tmp_raw, "notes/pending.md", "# 미처리\n")
    monkeypatch.setattr(sys, "argv", ["ingest.py"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1


def test_main_exits_0_when_no_unprocessed(tmp_raw, monkeypatch):
    """처리할 새 파일이 없으면 종료 코드 0 (SPEC 종료 코드 계약)."""
    _write_raw(tmp_raw, "notes/handled.md", "# 처리완료될 노트\n")
    mark_done()  # raw/ 전체를 처리완료로 표시 → 미처리 0
    monkeypatch.setattr(sys, "argv", ["ingest.py"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0


def test_main_exits_0_when_raw_empty(tmp_raw, monkeypatch):
    """raw/가 비어 미처리가 없으면 종료 코드 0."""
    monkeypatch.setattr(sys, "argv", ["ingest.py"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
