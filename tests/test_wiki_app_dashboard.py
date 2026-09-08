"""test_wiki_app_dashboard — 홈 대시보드 계약.

대시보드는 "지금까지 무엇을 완성했는가"를 보여주는 화면이다. 8주 동안 학생이
자기 진척을 확인하는 유일한 곳이므로, 아래가 깨지면 학생은 자기가 뭘 만들었는지
알 수 없게 된다.

읽기 전용이다 — 대시보드를 열었다고 wiki/·raw/ 가 바뀌면 안 된다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from wiki_app.api import create_app  # noqa: E402


@pytest.fixture
def brain(tmp_path):
    """빈 브레인 한 채. wiki/ 와 그 부모(= 브레인 루트)를 만든다."""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    return tmp_path


def _client(brain):
    return TestClient(create_app(wiki_root=brain / "wiki"))


def _page(brain, slug, title, body="본문", category="concepts"):
    d = brain / "wiki" / category
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(
        f'---\ntitle: "{title}"\ntype: concept\n---\n\n# {title}\n\n{body}\n', encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 빈 브레인에서도 화면이 뜬다
# ---------------------------------------------------------------------------


def test_empty_brain_returns_zeros_not_error(brain):
    """설치 직후(아무것도 없음)에도 200 이어야 한다.

    깨지면: 개강 전 처음 켜 본 학생이 첫 화면에서 500 을 본다.
    """
    r = _client(brain).get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert d["knowledge"]["pages"] == 0
    assert d["installed"] == 0
    assert len(d["organs"]) == 6


def test_works_without_graph_json(brain):
    """graph.json 이 없어도 페이지 수는 센다(export_graph 를 아직 안 돌린 상태).

    깨지면: compile 은 했는데 그래프를 안 만든 학생에게 "0페이지"로 보인다.
    """
    _page(brain, "alpha", "첫 메모")
    _page(brain, "beta", "둘째 메모")
    d = _client(brain).get("/api/dashboard").json()
    assert d["knowledge"]["pages"] == 2


# ---------------------------------------------------------------------------
# 장기 6종 — 8주 진척의 유일한 표시
# ---------------------------------------------------------------------------


def test_organ_detected_by_file_presence(brain):
    """extensions/ 에 파일이 생기면 그 장기가 '설치됨'이 된다.

    깨지면: 학생이 이번 주 이식을 마쳐도 화면이 그대로라, 진척이 보이지 않는다.
    """
    (brain / "extensions" / "w10_vision_ingest.py").write_text("# 이식 ①", encoding="utf-8")
    (brain / "extensions" / "w13_brain_mcp.py").write_text("# 이식 ⑤", encoding="utf-8")
    d = _client(brain).get("/api/dashboard").json()
    assert d["installed"] == 2
    on = {o["name"] for o in d["organs"] if o["installed"]}
    assert on == {"눈", "손"}


def test_organs_always_six_in_week_order(brain):
    """6칸은 설치 여부와 무관하게 항상 보인다 — 앞으로 무엇이 남았는지가 동기다."""
    d = _client(brain).get("/api/dashboard").json()
    weeks = [o["week"] for o in d["organs"]]
    assert weeks == ["10", "11", "11", "12", "13", "14"]
    assert all(o["gain"] for o in d["organs"])  # 무엇을 얻는지 문장이 비면 안 된다


# ---------------------------------------------------------------------------
# 자동화의 증거 — 없으면 학생은 돌았는지 모른다
# ---------------------------------------------------------------------------


def test_automation_logs_are_surfaced(brain):
    """watch/runner 로그의 마지막 줄이 화면 데이터에 올라온다.

    깨지면: 자동화는 성공하면 아무 일도 안 일어난 것처럼 보이므로,
    학생은 아침에 브레인이 돌았다는 사실을 영영 모른다.
    """
    (brain / "watch.log").write_text(
        "2026-09-08 07:00:00  a.md  PASS → raw/docs/a.md\n"
        "2026-09-08 07:00:00  notice.html  BLOCK → review/notice.md\n",
        encoding="utf-8",
    )
    d = _client(brain).get("/api/dashboard").json()
    assert len(d["automation"]["watch"]) == 2
    assert any("BLOCK" in ln for ln in d["automation"]["watch"])


def test_review_queue_is_reported(brain):
    """검수함에 걸린 문서가 이름까지 보고된다(사람이 판단할 몫)."""
    (brain / "review").mkdir()
    (brain / "review" / "notice.md").write_text("차단된 문서", encoding="utf-8")
    d = _client(brain).get("/api/dashboard").json()
    assert d["attention"]["review"] == ["notice.md"]


# ---------------------------------------------------------------------------
# 그래프 · 읽기 전용
# ---------------------------------------------------------------------------


def test_graph_links_limited_to_shown_nodes(brain):
    """보내는 링크는 화면에 그리는 노드 사이의 것만이다.

    깨지면: 없는 노드를 가리키는 선이 허공에 그려진다.
    """
    _page(brain, "a", "에이")
    _page(brain, "b", "비")
    (brain / "wiki" / "graph.json").write_text(json.dumps({
        "nodes": [
            {"id": "a", "kind": "page", "title": "에이", "category": "concepts", "inbound": 1, "outbound": 0},
            {"id": "b", "kind": "page", "title": "비", "category": "concepts", "inbound": 0, "outbound": 1},
        ],
        "links": [{"source": "b", "target": "a", "kind": "wikilink"},
                  {"source": "b", "target": "ghost", "kind": "ghost"}],
    }, ensure_ascii=False), encoding="utf-8")
    k = _client(brain).get("/api/dashboard").json()["knowledge"]
    assert k["links"] == 1                     # wikilink 만 센다
    assert k["graph_links"] == [{"s": "b", "t": "a"}]
    assert k["orphans"] == 0


def test_rule_path_brain_still_shows_links_and_a_map(brain):
    """wikilink 가 하나도 없어도 LINKS 와 지도의 선이 0 이 아니다.

    깨지면: 키 없이 시작한 학생(개강 전 대부분)의 첫 화면이 점만 찍힌 지도와
    LINKS 0 이 된다. RULE 경로는 wikilink 를 못 만들고 태그만 남기므로,
    태그를 안 세면 "쌓이고 있다"가 영원히 안 보인다.
    """
    for slug in ("a", "b", "c"):
        _page(brain, slug, f"메모 {slug}")
    (brain / "wiki" / "graph.json").write_text(json.dumps({
        "nodes": [{"id": x, "slug": x, "title": f"메모 {x}", "kind": "page"} for x in "abc"]
               + [{"id": "tag:반복업무", "kind": "tag"}],
        "links": [{"source": x, "target": "tag:반복업무", "kind": "tag"} for x in "abc"],
    }), encoding="utf-8")

    res = _client(brain).get("/api/dashboard").json()
    assert res["knowledge"]["links"] == 3
    # 같은 태그를 단 셋이 서로 이어진다 → 3 쌍
    assert len(res["knowledge"]["graph_links"]) == 3


def test_a_very_common_tag_does_not_black_out_the_map(brain):
    """한 태그를 7개 넘게 달아도 모두-모두 선으로 지도를 뭉개지 않는다.

    깨지면: 학생이 모든 메모에 같은 태그(예: note)를 달았을 때 선이 수십 개로
    폭발해 지도가 까맣게 칠해진다. 연결이 많은 게 아니라 안 보이는 것이 된다.
    """
    slugs = [f"p{i}" for i in range(8)]
    for x in slugs:
        _page(brain, x, f"메모 {x}")
    (brain / "wiki" / "graph.json").write_text(json.dumps({
        "nodes": [{"id": x, "slug": x, "title": f"메모 {x}", "kind": "page"} for x in slugs],
        "links": [{"source": x, "target": "tag:note", "kind": "tag"} for x in slugs],
    }), encoding="utf-8")

    res = _client(brain).get("/api/dashboard").json()
    assert res["knowledge"]["graph_links"] == []


def test_compiled_notes_leave_the_attention_list(brain):
    """컴파일이 끝난 메모는 "손봐야 할 곳"에서 빠진다.

    깨지면: raw 원본은 컴파일 후에도 남으므로, 다 끝낸 학생에게도 "RAW 14"가
    영원히 떠 있다. 끝냈는데 안 끝난 것처럼 보이면 진척이 안 읽힌다.
    """
    raw = brain / "raw" / "notes"
    raw.mkdir(parents=True)
    (raw / "one.md").write_text("메모 하나", encoding="utf-8")
    (raw / "two.md").write_text("메모 둘", encoding="utf-8")
    before = _client(brain).get("/api/dashboard").json()
    assert before["attention"]["raw_pending"] == 2

    (brain / ".ingest_state.json").write_text(
        json.dumps({"processed": ["raw/notes/one.md"]}), encoding="utf-8")
    after = _client(brain).get("/api/dashboard").json()
    assert after["attention"]["raw_pending"] == 1


def test_broken_state_file_does_not_break_the_screen(brain):
    """상태 파일이 깨져 있어도 화면은 뜬다.

    깨지면: 학생이 실습 중 파일을 잘못 건드렸을 때 대시보드가 통째로 500 이 된다.
    """
    raw = brain / "raw" / "notes"
    raw.mkdir(parents=True)
    (raw / "one.md").write_text("메모", encoding="utf-8")
    (brain / ".ingest_state.json").write_text("{깨진 json", encoding="utf-8")

    r = _client(brain).get("/api/dashboard")
    assert r.status_code == 200
    assert r.json()["attention"]["raw_pending"] == 1


def test_dashboard_does_not_write_anything(brain):
    """대시보드를 열어도 파일이 하나도 바뀌지 않는다(읽기 전용 가드레일)."""
    _page(brain, "a", "에이")
    before = {p: p.stat().st_mtime_ns for p in brain.rglob("*") if p.is_file()}
    _client(brain).get("/api/dashboard")
    after = {p: p.stat().st_mtime_ns for p in brain.rglob("*") if p.is_file()}
    assert before == after


# ---------------------------------------------------------------------------
# 적대 리뷰(Codex)에서 나온 결함들 — 회귀 방지
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broken", [
    "[]",                                   # 배열
    '{"nodes": null}',                      # nodes 가 null
    '{"nodes": [{"kind": "page"}]}',        # 필드 없는 노드
    '{"nodes": "text", "links": 3}',        # 타입이 전부 다름
])
def test_broken_graph_json_does_not_500(brain, broken):
    """JSON 문법은 맞지만 구조가 깨진 graph.json 에도 홈은 떠야 한다.

    깨지면: export_graph 가 중단됐거나 파일이 잘린 학생은 홈에서 500 을 본다.
    위키가 멀쩡해도 화면 자체를 못 연다.
    """
    _page(brain, "a", "에이")
    (brain / "wiki" / "graph.json").write_text(broken, encoding="utf-8")
    r = _client(brain).get("/api/dashboard")
    assert r.status_code == 200
    assert r.json()["knowledge"]["pages"] >= 1     # 파일 스캔으로 폴백


def test_non_utf8_log_does_not_500(brain):
    """로그가 UTF-8 이 아니어도 홈은 떠야 한다.

    깨지면: 다른 도구가 쓴 로그나 깨진 바이트 한 줄 때문에 대시보드 전체가 죽는다.
    """
    (brain / "watch.log").write_bytes(b"\xff\xfe\x00 2026-09-08 PASS\n")
    r = _client(brain).get("/api/dashboard")
    assert r.status_code == 200


def test_node_with_non_string_id_does_not_500(brain):
    """id 가 문자열이 아닌 노드가 섞여도 홈은 떠야 한다.

    깨지면: graph.json 한 줄이 이상해도 대시보드 전체가 500 이 된다.
    (재적대 리뷰에서 나온 정확한 재현 케이스)
    """
    _page(brain, "a", "에이")
    (brain / "wiki" / "graph.json").write_text(json.dumps({
        "nodes": [{"kind": "page", "id": [], "title": "x", "category": "concepts",
                   "inbound": 0, "outbound": 0}],
        "links": [],
    }), encoding="utf-8")
    r = _client(brain).get("/api/dashboard")
    assert r.status_code == 200
