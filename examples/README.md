# Examples — seed-wiki + seed-raw

두 가지 데모를 제공한다:

| 폴더 | 무엇 | 언제 |
|---|---|---|
| **`seed-wiki/`** | 이미 컴파일된 5페이지 sample **wiki** (결과물) | fresh clone 후 즉시 `wiki_app` 데모를 보고 싶을 때 |
| **`seed-raw/`** | 가상 PM 11개 **raw 노트** (입력) | `raw → wiki` **컴파일 과정**(`/llm-brain:ingest`)을 직접 체험하고 싶을 때 |

> 빈손으로 시작하는 수강생은 `seed-raw/`를 `raw/`에 복사해 ingest하면 "흩어진 메모 → 연결된 위키 그래프"를 체험할 수 있다. 자세한 실습 순서는 `seed-raw/README.md` 참조.

## seed-wiki 레이아웃

seed-wiki는 **자기 완결형**이라 그대로 프로젝트 루트에 복사하면 app이 읽는 구조와 1:1로 맞는다.

- `examples/seed-wiki/index.md` → 루트 `index.md`로 복사 (app은 루트 `index.md`를 읽음)
- `examples/seed-wiki/wiki/` → 루트 `wiki/`로 복사 (app은 `wiki/<category>/<slug>.md` + `wiki/graph.json`을 읽음)

> app은 `wiki_root = <프로젝트 루트>/wiki`, index는 `wiki_root`의 부모인 루트 `index.md`를 읽는다. seed의 `index.md` 5개 슬러그와 `wiki/` 5개 페이지가 정합하므로 `/api/index`의 `total_pages`가 디스크 페이지 수(5)와 일치한다.

## 사용법

### Option A — 데모만 보고 자기 wiki 시작 (권장)

루트 `index.md`는 fresh clone에 포함된 **작성자 개인 인덱스(97페이지)**다. 데모용 5페이지 index로 잠깐 교체하므로, 먼저 백업한다.

```bash
# (1) 작성자 index.md 백업 — 데모 후 복원용
cp index.md index.md.bak

# (2) seed-wiki를 app이 읽는 위치로 복사
cp -r examples/seed-wiki/wiki ./wiki        # → wiki/concepts, wiki/tools, wiki/graph.json
cp examples/seed-wiki/index.md ./index.md   # → 루트 index.md (5페이지 데모용)

# (3) wiki_app 실행
uv run python -m wiki_app
# → http://localhost:8000 에서 5개 sample 페이지 검색·페이지뷰 가능
#   /api/index 의 total_pages = 5 (디스크와 정합)

# (4) 데모 종료 후 — 작성자 index 복원 + 데모 wiki 정리
mv index.md.bak index.md
rm -rf wiki                                  # wiki/ 는 .gitignore 대상이라 git에 흔적 없음
```

이후 자신의 raw 소스를 `raw/`에 추가하고 ingest → wiki/ 구축.

### Option B — 자기 wiki만 사용 (seed 건너뛰기)

`examples/`를 무시하고 README의 빠른 시작 가이드만 따르세요.

## seed-wiki 구성

- `wiki/concepts/llm-wiki-pattern.md` — Karpathy 패턴
- `wiki/concepts/second-brain-code.md` — Tiago Forte CODE 프레임워크
- `wiki/concepts/distill-progressive.md` — Progressive Summarization
- `wiki/tools/claude-code.md` — Claude Code CLI
- `wiki/tools/obsidian.md` — Obsidian
- `wiki/graph.json` — wikilink 그래프 (13 links)
- `index.md` — 5페이지 데모 인덱스 (루트로 복사됨)

상호 wikilink 13개로 연결돼 있어, wiki_app의 검색·페이지뷰·wikilink 클릭 모두 즉시 작동합니다.

## CI 영향

이 seed 데이터는 `tests/conftest.py`의 `_HAS_USER_WIKI` fallback에도 사용됩니다. GitHub Actions가 `examples/seed-wiki/wiki/`(+ `examples/seed-wiki/index.md`)를 wiki 데이터로 활용해 21개 wiki-dependent test를 skip 없이 실행할 수 있습니다 (CI workflow에 복사 step 추가 후).
