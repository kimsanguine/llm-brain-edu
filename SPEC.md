# llm-brain — Technical Specification

## 시스템 개요

- **제품명**: llm-brain (Second Brain Compiler)
- **버전**: v2.0
- **GitHub**: github.com/kimsanguine/llm-brain
- **아키텍처**: `raw/`(원본) → `wiki/`(정제) 2계층 + `express/`(출력) 레이어
- **컨셉**: LLM을 컴파일러로 사용하는 개인 지식 관리 시스템. Karpathy 원본 패턴 기반, 5축 확장.

---

## 디렉토리 구조 (전체)

```
260516_llm_brain/
├── CLAUDE.md                    # Claude Code 운영 가이드 (역할·가드레일·명령어)
├── README.md
├── SPEC.md                      # 이 파일
├── pyproject.toml               # uv 의존성 (name: llm-wiki)
├── index.md                     # 전체 wiki 목차
├── log.md                       # 실행 이력
├── wiki_stats.json              # 페이지 접근 통계 (access_count, last_accessed)
├── .ingest_state.json           # 처리 완료 raw 파일 목록
├── .sync_state.json             # 소스별 마지막 동기화 시각
├── .launchd.log                 # launchd 실행 로그
│
├── scripts/                     # 자동화 스크립트
│   ├── ingest.py                # raw/ 탐지·스크랩·노트 저장 + 상태 관리 + episode 기록
│   ├── sync_raw.py              # sources.yaml → raw/ 델타 미러링
│   ├── curate.py                # wiki 감사·압축·lifecycle + memory_score·rescue (--health, --suggest-bridges)
│   ├── export_graph.py          # wikilink 그래프 export → wiki/graph.json
│   ├── okf_export.py            # wiki/ → OKF v0.1 호환 번들 okf/ 투영 (export 포트)
│   ├── express.py               # wiki → 창작물 초안 컨텍스트 준비 + 재사용 메타·episode 기록
│   ├── canvas_utils.py          # Obsidian Canvas JSON 생성 유틸 (force-directed 레이아웃)
│   ├── episode.py               # append-only 에피소드 원장 (append/read_recent) — Agent Memory OS
│   ├── brain_context.py         # 작업기억 팩 조립 (semantic+episode+procedure+제약) — Agent Memory OS
│   ├── memory_health.py         # 읽기전용 메모리 건강 리포트 → wiki/memory_health_report.md
│   ├── procedures.py            # 재사용 절차 로더 (list_procedures/read_procedure)
│   ├── lib/
│   │   └── frontmatter_utils.py # 공용 frontmatter 파서 (read_fm/write_fm, fail-loud)
│   └── setup.sh                 # 초기 설정 (venv·폴더·config 생성)
│
├── commands/                    # 플러그인 슬래시 커맨드 (ingest·curate·express·okf·query)
│
├── procedures/                  # 재사용 절차 메모리 (.md, git-tracked + OKF 제외) — Agent Memory OS
│   └── {slug}.md                # memory_type: procedural (ingest·curate·express-blog·okf-export-safety)
│
├── episodes/                    # 에피소드 원장 (.gitignore 대상, OKF 제외) — Agent Memory OS
│   └── YYYY-MM.jsonl            # 월별 샤드, append-only (turn-after 쓰기)
│
├── examples/                    # 시드·예시 (커밋 대상)
│   ├── episode-schema-example.jsonl  # 에피소드 스키마 예시 1줄 (문서·테스트용)
│   ├── seed-raw/                # 초기 raw/ 시드
│   └── seed-wiki/               # 초기 wiki/ 시드
│
├── schema/                      # 운영 규칙 파일
│   ├── sources.yaml             # 소스 경로·TTL·필터 설정
│   ├── sources.example.yaml     # 소스 설정 템플릿
│   ├── config.yaml              # LLM 엔진 선택 (cli / api)
│   ├── domains.yaml             # 도메인 분류 규칙 및 키워드 매핑
│   ├── ingest.md                # ingest 절차·품질 기준 규칙
│   ├── curate.md                # curate 단계별 규칙
│   ├── okf.md                   # OKF ↔ llm-brain 매핑 규칙 레퍼런스
│   └── okf_export.yaml          # okf_export 제외 설정 (exclude_paths·domains·slugs)
│
├── raw/                         # 원본 소스 (.gitignore 대상)
│   ├── til/                     # OpenClaw TIL 미러 (sync_raw)
│   ├── meetings/                # OpenClaw 회의록 미러 (sync_raw)
│   ├── newsletters/             # AI 뉴스레터 미러 (sync_raw)
│   ├── context/                 # 비즈니스 컨텍스트 미러 (sync_raw)
│   ├── blog/                    # habix blog 콘텐츠 미러 (sync_raw + express 피드백)
│   ├── clippings/               # URL 수동 스크랩 (ingest --url)
│   ├── notes/                   # 텍스트 수동 노트 (ingest --note)
│   └── docs/                    # 로컬 파일 추가 (ingest --file)
│
├── wiki/                        # LLM 정제 결과 (.gitignore 대상)
│   ├── concepts/                # AI·기술 개념 페이지
│   ├── tools/                   # 도구·프레임워크 페이지
│   ├── people/                  # 인물 페이지
│   ├── projects/                # 프로젝트 인사이트 페이지
│   ├── business/                # 시장·경쟁사·전략 페이지
│   ├── lecture/                 # 강의 지식 페이지
│   ├── insights/                # TIL 정제본·반복 패턴
│   ├── archive/                 # lifecycle으로 이동된 만료 페이지
│   ├── curate_report.md         # curate 실행 결과 보고서
│   ├── distill_queue.md         # distill 우선순위 큐
│   └── graph.json               # wikilink 그래프 데이터 (export_graph.py 생성)
│
├── express/                     # 창작물 출력 레이어
│   ├── blog/                    # 블로그 포스트 초안
│   ├── lecture/                 # 강의 슬라이드 초안
│   ├── summary/                 # 주간·월간 요약 초안
│   └── report/                  # 심층 리포트 초안
│
├── okf/                         # 기존 private OKF v0.1 projection
│   ├── index.md                 # 번들 루트 목차 (type별 그룹 + 디렉토리 index 링크)
│   ├── log.md                   # export 이력 + 변환 경고
│   ├── .okf-bundle              # 번들 센티넬 (재export 시 안전 정리용 마커)
│   └── {dir}/                   # 디렉토리별 미러 + index.md (business/·canvas/ 제외)
├── okf-share/                   # --share gate 통과 bundle + redacted manifest
│
├── wiki_app/                    # HTML 검색·페이지뷰 (FastAPI + vanilla JS, port 8000)
│   ├── __main__.py              # uv run python -m wiki_app
│   ├── api.py                   # 6 endpoints (/api/index, /api/search, /api/page/{slug}, /api/page/{slug}/graph, /api/ai-answer, /api/ai-answer/stream). ai-answer 비스트림·스트림 양 핸들러가 finally에서 episode 기록(fail-soft)
│   ├── search.py                # Index + B 알고리즘 + C 확장 (본문 grep)
│   ├── pages.py                 # 페이지 로더 (frontmatter + body + graph metadata)
│   ├── render.py                # markdown-it + [[wikilink]] SPA 앵커 후처리
│   ├── access.py                # 명시적 access_count 기록 helper (원자적 쓰기·threading.Lock)
│   └── static/
│       ├── index.html           # 3 views (empty / results / empty-results)
│       ├── styles.css           # Pretendard + 디자인 톤
│       └── app.js               # 상태관리·검색·페이지뷰·AI 모달
│
└── .obsidian/                   # Obsidian vault 설정 (Graph View 연동)
```

---

## 스크립트 인터페이스

### scripts/ingest.py

raw/ 폴더에서 미처리 파일을 탐지하고, URL·파일·노트를 raw/에 저장하며, 처리 상태를 `.ingest_state.json`으로 관리한다. 실제 wiki 컴파일은 LLM(claude CLI 또는 API)이 담당한다.

#### WIKI_ROOT 계산 방식

```python
WIKI_ROOT = Path(__file__).parent.parent  # scripts/../ → 프로젝트 루트
```

`scripts/ingest.py`가 `scripts/` 내에 있으므로, `__file__`의 두 단계 상위가 프로젝트 루트가 된다.

#### 지원 파일 형식 및 추출 라이브러리

| 확장자 | 추출 방법 |
|--------|----------|
| `.md`, `.txt` | 직접 읽기 (`Path.read_text`) |
| `.pdf` | `fitz` (pymupdf) — `fitz.open` + `page.get_text()` |
| `.docx` | `python-docx` — `Document(file).paragraphs` |
| `.pptx` | `python-pptx` — `slide.shapes[].text_frame.text` |

#### CLI 인자 전체

| 인자 | 타입 | 설명 |
|------|------|------|
| `--url URL` | str | 지정 URL을 스크랩해 `raw/clippings/YYYY-MM-DD-{slug}.md`로 저장 |
| `--file PATH` | str | 로컬 파일을 `raw/docs/YYYY-MM-DD-{filename}`으로 복사. `.md`·`.txt` 외 형식은 `.extracted.md`도 함께 저장 |
| `--note TEXT` | str | 텍스트를 `raw/notes/YYYY-MM-DD-HHmm-note.md`로 저장 |
| `--mark-done` | flag | 현재 `raw/`의 모든 파일을 처리 완료로 `.ingest_state.json`에 기록 |
| `--resonance` | choices: `high`\|`medium`\|`low` | `--url`·`--file`·`--note`와 함께 사용. 저장 파일의 frontmatter에 `resonance: {값}` 기록 |
| `--priority-only` | flag | 미처리 파일 중 frontmatter에 `resonance: high`인 파일만 출력 |
| `--force` | flag | hard dedup 중복 차단을 무시하고 저장 강행 (v0.3.0) |

#### 종료 코드 의미

| 코드 | 의미 |
|------|------|
| `0` | 처리할 새 파일 없음. **hard dedup 차단으로 저장이 보류된 경우도 0** (차단은 오류가 아님) |
| `1` | 미처리 파일이 1개 이상 존재 (`run_daily.sh`가 이를 감지해 LLM 호출 결정) |

#### resonance 필터 동작

`--priority-only` 플래그 사용 시, `.ingest_state.json` 미등록 파일 중 frontmatter 첫 줄에 `resonance: high` 패턴(`re.search(r"^resonance:\s*(\S+)", ...)`)이 있는 파일만 반환한다. `.md`·`.txt` 형식만 frontmatter 파싱 대상이며 다른 형식은 None 처리한다.

#### 중복 검사 동작 (hard dedup — v0.3.0)

`is_duplicate(file) -> (is_dup, target_slug, score)` 함수가 `--url`·`--file`·`--note` 저장 **전에** 호출된다. `index.md`의 `[[wikilink]]` 목록을 파싱해 저장 예정 파일명 slug(날짜 접두사 `YYYY-MM-DD-` 제거, `_→-`, 소문자 변환)와 비교하고, 완전일치 시 `(True, index의 원본 slug 표기, 1.0)`을 반환한다 (v0.3.0은 완전일치만 — 유사도 확장은 P1). 함수는 판정만 담당하고 출력·차단은 `main()`이 수행한다.

- 저장 예정 경로는 `_planned_url_path`·`_planned_file_path`·`_planned_note_path`가 저장 함수와 공유하는 단일 출처로 계산한다. `--url`도 slug가 URL에서 파생되므로 **fetch 없이** 저장 전 판정이 성립한다.
- 중복이면 기본 동작 = **저장 보류**: raw 파일 미생성·episode 미기록·기존 노드 `[[target_slug]]` 강화 라우팅 제안 메시지 출력 후 `exit 0`. 자동 병합은 하지 않는다(라우팅은 제안까지).
- `--force` 시에만 경고 출력 후 기존처럼 저장 강행(episode 기록 포함).

#### episode 기록 (저장 직후, fail-soft — US-002)

`--url`·`--file`·`--note` 저장 성공 직후 `_record_ingest_episode()`가 staging 에피소드 1건을 `episode.append`한다. `task_type`은 `ingest_url`·`ingest_file`·`ingest_note`, `status`는 `pending_wiki_compilation`(아직 wiki 컴파일 전 단계라 `read_pages`·`procedures_used`는 빈 리스트). **fail-soft**: try/except로 감싸 원장 실패가 ingest의 종료 코드 계약(0/1)을 깨지 않는다(stderr warn 후 계속).

---

### scripts/sync_raw.py

`schema/sources.yaml`에 등록된 소스 경로에서 `raw/` 폴더로 델타 미러링한다. 변경·신규 파일만 복사하며, `raw/` 파일은 삭제하지 않는다.

#### sources.yaml 스키마

`schema/sources.yaml` 섹션 참조.

#### 지원 extensions

기본값: `{".md", ".txt", ".pdf", ".docx", ".pptx"}`.  
`sources[].extensions` 필드가 설정된 경우 해당 확장자로 제한된다.  
형식: `[md, txt]` → 내부에서 `.md`, `.txt`로 변환.

#### 델타 미러링 로직 (mtime 기반)

`.sync_state.json`에서 `source_id`의 마지막 동기화 시각(`last_sync`)을 로드한다. 소스 디렉토리를 재귀 순회하며 `src_file.stat().st_mtime <= last_sync_dt.timestamp()`인 파일은 건너뛴다. 복사 후 `state[source_id] = datetime.now().isoformat()`으로 기록한다.

`exclude_tags`가 설정된 경우, `python-frontmatter`로 파일 frontmatter를 파싱해 `tags`와 교집합이 있으면 건너뛴다.

#### capture 필터 (require_keywords · min_word_count — v0.3.0)

소스별 선택 필드로 raw/ 복사 전에 잡음을 거른다 (`capture_filter_reason(file, source_cfg)`).

- `require_keywords` (list[str]): 나열된 키워드 중 **하나라도** 본문에 포함되면 통과 (대소문자 무시). 하나도 없으면 미복사 + `[필터]` 스킵 로그.
- `min_word_count` (int): 공백 분리 단어 수가 이 값 미만이면 미복사 + 스킵 로그.
- 두 필드 모두 미설정인 소스는 기존과 **완전 동일** 동작. `.md`·`.txt`만 본문 판정 대상이며 그 외 형식(pdf·docx·pptx)은 필터 미적용 통과.

#### .sync_state.json 구조

```json
{
  "til": "2026-05-17T07:00:12.345678",
  "meetings": "2026-05-17T07:00:13.456789",
  "newsletters": "2026-05-16T07:00:10.123456"
}
```

키: `source_id` (sources.yaml의 `id` 필드), 값: ISO 8601 datetime 문자열.

---

### scripts/curate.py

wiki 전체를 감사(audit) + 압축(distill) + 수명 관리(lifecycle)하는 복합 오퍼레이션.
그래프 export는 별도 `scripts/export_graph.py`가 담당한다.

#### CLI 인자 전체

| 인자 | 설명 |
|------|------|
| `--all` | audit + distill + lifecycle 전체 실행 |
| `--audit` | orphan 페이지·stale 링크 탐지 |
| `--distill` | distill 후보 분류 및 `wiki/distill_queue.md` 생성 |
| `--lifecycle` | lifecycle archive/delete 후보 목록 생성 |
| `--purge` | `curate_report.md`의 archive 후보를 `wiki/archive/`로 실제 이동 |
| `--record-access PAGE_SLUG` | `wiki_stats.json`에 페이지 접근 기록 (명시적 opt-in; query는 자동 호출하지 않음) |
| `--health` | graph health 지표 출력 (avg degree, components, BC top, low-degree count) |
| `--suggest-bridges N` | betweenness/structural-hole 기반 missing link 추천 N개 |
| `--reweave` | weak content 스캔(본문<800자 OR 근거<2건 OR H2<3개) → `wiki/reweave_queue.md` 큐 생성 + `wiki/observing/` 만료 페이지 `wiki/rejected/` 이동 (v0.3.0 WS-3, 매일) |
| `--fix` | `--reweave` 조합: 자동 보강 가능분(summary·source_count·updated — memory_health fix 엔진 위임, idempotent)만 즉시 적용. 본문·근거 부족은 alert만(가짜 보강 금지) |
| `--dry-run` | `--reweave` 조합: 아무 파일도 변경·생성하지 않고 계획만 stdout 출력 (리포트·큐·episode 미기록) |
| `--weekly-summary` | `--reweave` 조합: 최근 28일 reweave 에피소드에서 4회+ 반복 weak 노드를 통합/삭제 후보로 리포트. episodes 부재/부족 시 현재 스캔만으로 후보 + "이력 부족" 정직 표기 |

인자 없이 실행하면 `--all`과 동일하게 동작한다.

#### distill_level 단계 정의

`distill_level`은 wiki 페이지 frontmatter 필드. 값이 높을수록 더 많이 압축된 상태.

| 값 | 의미 |
|----|------|
| `0` | 미압축 (ingest 직후 기본값) |
| `1` | 1차 압축 완료 |
| `2` | 2차 압축 완료 |
| `3` | 최종 압축 (더 이상 압축 불필요) |

#### 출력 파일

| 파일 | 생성 조건 |
|------|----------|
| `wiki/curate_report.md` | 항상 생성 (audit·distill·lifecycle·reweave 결과 통합) |
| `wiki/distill_queue.md` | `--distill` 또는 `--all` 실행 시 |
| `wiki/reweave_queue.md` | `--reweave` 실행 시 (판단 필요분 큐 `## 판단 필요분` + 종합 대상 큐 `## 종합 대상`(v0.3.1 WS-1) — LLM 컴파일러가 `commands/curate.md` Step 3에서 소비. `--dry-run` 시 미작성) |
| `wiki/contradiction_queue.md` | `--audit`/`--all` 실행 시 **모순 후보가 1건 이상일 때만**(v0.3.1 WS-5 — 후보 0이면 미생성, 오탐 남발 방지). 가장 최근 raw × 기존 페이지를 `reconcile.detect_contradiction_candidates`로 대조. 화해 서술은 `commands/curate.md` Step |
| `wiki/.synthesis_snapshot.json` | `--reweave`(비 dry-run) 실행 시 — synthesis 대상 본문·근거 스냅샷. 다음 run 에서 `synthesis.guard_no_shrink`로 축소 감지(WARN shrink). gitignored·wiki 페이지 아님 |

#### memory_score — 메타 기억 점수 (US-006, 재사용 우선·결정적)

`compute_memory_score(entry, graph, fm, *, weights=None, caps=None, centrality_weights=None, now=None) -> float`는 slug 1개의 보존 가치(0~100)를 결정적으로 계산한다. 재사용 신호에 가중 60%를 둬 "클릭은 적어도 인용되면 보존"을 구현한다.

```
score = Σ weight·norm(signal),  norm(x) = min(x / CAP, 1.0)
```

| 신호 | 기본 weight | 기본 CAP | 출처 |
|------|------------|---------|------|
| `express_reuse` | 35 | 5 | `build_express_reuse_index()` — `express/` 산출물의 `source_pages`/`[[link]]` 인용 횟수 |
| `episode_ref` | 25 | 10 | `build_episode_ref_index()` — episode `read_pages` 등장 횟수 (`express_*` 에피소드는 제외, 이중계산 방지) |
| `centrality` | 15 | 20 | `w_inbound·inbound + w_betweenness·betweenness` (`wiki/graph.json`; betweenness 미저장 시 0) |
| `access_count` | 10 | 20 | frontmatter / `wiki_stats.json` |
| `recency` | 10 | — | age 선형 감쇠 (≤30일 1.0 → ≥365일 0.0) |
| `source_count` | 5 | 5 | `len(fm["sources"])` |

- 가중치·CAP은 `curate.py`의 `MEMORY_SCORE_*_DEFAULT` 상수가 기본값. 선택적으로 `schema/config.yaml`의 `memory_score:` 섹션이 override한다(사람 튜닝 = Rule 5). config 파일은 현재 비어 있어 기본값으로 동작하며, 부재/부분/오류 키(누락 weight·0/음수 CAP·타입오류)는 항별 기본값 + stderr warn으로 안전 폴백한다(조용한 crash/flaky 금지).
- `now`는 `recency` 결정성용 주입(테스트는 고정 시각 주입).

#### within-tier 정렬 (run_distill, US-006 plug-in ①)

`run_distill()`의 임계 게이트(`access≥10/distill<3`=긴급, `access≥5/distill<2`=우선, `access=0/90일+`=lifecycle)는 **유지**(신규 페이지 보호·backward-compat). `memory_score`는 각 tier **내부 정렬**에만 쓰인다 — score 내림차순, 동점은 slug 오름차순(결정성). `distill_queue.md`에 `score=…(사유)` 주석을 함께 기입한다. 이 버킷은 자문용이라 페이지를 옮기지 않는다.

#### rescue — 재사용 페이지 보존 (run_lifecycle, US-006 plug-in ②)

실제 archive 게이트는 `run_lifecycle()`(`age>ttl AND inbound==0`)이다. 여기서 `_rescue_split()`이 archive 후보에 `memory_score`를 매겨 **상위 `RESCUE_TOP_PCT_DEFAULT`(0.20) 중 score>0**인 페이지를 archive에서 제외해 보존한다(상대 임계 — 출시 직후 재사용 이력이 비어 절대 임계는 과녁이 움직임). 보존 페이지는 `curate_report.md`의 별도 `## Rescued` 섹션에 기록되고, `delete` 후보와 `--purge` 이동 대상(Lifecycle 섹션 한정 정규식)에서도 제외된다. `run_lifecycle()` 반환: `{"archive": [...], "delete": [...], "rescued": [...]}`.

> ✅ **curate episode 기록(US-002, 배선됨):** `curate.py`는 run(audit/distill/lifecycle) 후 `_record_curate_episode`가 실행 요약(orphans·stale_links·distill_queued·archive/delete/rescued 카운트)을 episode로 기록한다(fail-soft). 4 배선점(ingest·express·wiki_app·curate) 모두 완료. (curate는 점수용으로 episode를 읽기도 함 — `build_episode_ref_index`.)

#### reweave — Daily Quality-Driven Curate (v0.3.0 WS-3, 구현됨)

`run_reweave(fix, dry_run, weekly_summary, now)`는 **기존 자산 오케스트레이터**다 (신규 엔진 아님, LLM 호출 0):

1. **weak 스캔**: `memory_health.py`의 weak 판정(`_weak_content_issues` — 본문<800자 OR 근거<2건 OR H2<3개)을 import 재사용. 판단 필요분은 `wiki/reweave_queue.md`(distill_queue와 동일 체크박스 패턴)로 큐잉 — 보강 실행은 `commands/curate.md` Step 3의 LLM 컴파일러 담당.
2. **자동 보강(`--fix`)**: memory_health의 fix 엔진(`_plan_page_fixes` — summary·source_count·updated 기계적 채움, idempotent)에 위임. 쓰기는 `frontmatter_utils.write_fm`(body 무손상). `memory_health.run_fix`를 통째로 쓰지 않는 이유: run_fix는 wiki 전체를 돌아 observing/·rejected/까지 건드리는데 두 폴더는 격리 대상이라, 같은 엔진 조각을 격리 필터와 함께 재구동한다.
3. **observing 만료**: `wiki/observing/`을 직접 스캔해 `gates.evaluate_observing_expiry(page, today)` 적용 → 만료면 `gate_status: rejected` 갱신 후 `wiki/rejected/`로 이동(결정적 파일 작업). 판정 실패(만료일 결손 등)는 파일 무변경 + 리포트 경고로 표면화.
4. **격리**: `find_all_wiki_pages()`가 `observing/`·`rejected/`·`reweave_queue.md`를 제외(정규 audit/distill/lifecycle/merge-review에서 격리), `LIFECYCLE_EXEMPT`에도 두 폴더 등재(TTL decay 면제). okf는 `schema/okf_export.yaml` `exclude_paths`(`observing/**`·`rejected/**`·`reweave_queue.md`)로 봉인.
5. **episode**: 실행 후 `task_type: reweave`로 기록(fail-soft) — `read_pages` = 그 런의 weak 목록. `lib/memory_score.build_episode_ref_index`는 `reweave`를 집계에서 제외한다(express_* 제외와 같은 자기 점수 되먹임 차단).
6. **`--weekly-summary`**: 최근 28일 reweave 에피소드의 `read_pages` + 현재 스캔을 런 단위로 집계해 4회+ 반복 weak 노드를 통합/삭제 후보로 리포트(`## Reweave` → `### Weekly Summary`). 집계 런 <4면 현재 스캔만으로 후보 + "이력 부족" 정직 표기(fail-soft). 실제 이동·삭제는 사용자 승인 필수.

`curate_report.md`에 `## Reweave` 섹션(`fixed: N / alert: M / expired: K` + 상세)이 추가된다. `--dry-run`은 계획만 stdout 출력하고 어떤 파일도 쓰지 않는다.

---

### scripts/export_graph.py

`[[wikilink]]`를 파싱해 D3 force-graph용 JSON으로 export하는 독립 스크립트.

#### 출력 파일

| 파일 | 설명 |
|------|------|
| `wiki/graph.json` | 노드(페이지)·엣지(wikilink) 데이터. `wiki_app` `/api/page/{slug}/graph` 엔드포인트가 이 파일을 읽는다. |

#### 허브 점수 계산 방식

- **허브**: inbound 링크 수 ≥ 5
- **연결**: inbound 링크 수 1–4
- **고립**: inbound 링크 수 = 0 AND age > 90일

#### wiki_stats.json 구조

```json
{
  "page-slug": {
    "access_count": 2,
    "last_accessed": "2026-05-16"
  }
}
```

`curate --record-access PAGE_SLUG`를 명시적으로 호출할 때만 `wiki_stats.json`의
`access_count`와 `last_accessed`를 갱신한다(frontmatter는 갱신하지 않음).
웹 검색·페이지 보기·AI query는 `access.track`을 자동 호출하지 않으며
`raw/`·`wiki/`·`wiki_stats.json`·접근 lock을 변경하지 않는다. distill 시
frontmatter의 기존 `access_count`와 `wiki_stats.json`의 값 중 큰 값을 사용한다.

---

### scripts/okf_export.py

`wiki/`(내부 슈퍼셋)를 OKF v0.1 호환 번들 `okf/`로 투영하는 export 포트. 내부 포맷은 바꾸지 않고 경계(`okf/`)에서만 변환한다. frontmatter 파서(`parse_frontmatter`·`FRONTMATTER_RE`·`WIKILINK_RE`)는 `scripts/export_graph.py`에서 import하며 export_graph는 수정하지 않는다.

변환 규칙 전문은 `schema/okf.md`, 제외 설정은 `schema/okf_export.yaml` 참조.

#### 변환 동작 요약

- **frontmatter**: OKF 예약 6필드(`type`·`title`·`description`·`resource`·`tags`·`timestamp`) 순서로 매핑. `updated`(없으면 `created`)를 `timestamp`로 매핑. 나머지 내부 필드는 `x-llmbrain-{key}`로 보존(`--strip-internal`이면 제거).
- **본문 wikilink**: `[[X]]` → `[X](/<rel>)` 번들 루트 절대경로 마크다운 링크. 별칭은 `[[X|별칭]]` → `[별칭](/<rel>)`. 깨진 링크(대상 없음)는 텍스트화 + `log.md` 기록. 제외 페이지를 가리키던 링크는 별칭을 버리고 slug만 남긴다(redact).
- **description**: fm `description` → 본문 `## 핵심` 첫 문장 → 첫 문단 첫 문장 순으로 규칙 기반 추출(LLM 호출 없음). 300자 절삭.
- **exclude**: 경로 글롭(기본 `business/**`·`canvas/**`) + domain 라벨 + slug. 경로 글롭이 1차 보안 필터.

#### CLI 인자 전체

| 인자 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `--out PATH` | str | `okf/` | 출력 번들 루트. 상대경로는 레포 루트 기준 |
| `--strip-internal` | flag | off | OKF 예약 6필드만 남기고 `x-llmbrain-*` 제거. 단독으로는 Share-ready 승인 아님 |
| `--config PATH` | str | `schema/okf_export.yaml` | private export override. Share-ready는 canonical 기본 경로 외 값을 거부 |
| `--exclude-path GLOB` | str (복수) | `[]` | 추가 제외 경로 글롭. 설정 파일 값에 누적 |
| `--exclude-domain D` | str (복수) | `[]` | frontmatter `domain` 라벨 기준 제외 (보조 필터) |
| `--exclude-slug SLUG` | str (복수) | `[]` | 특정 slug 명시 제외 |
| `--dry-run` | flag | off | 파일 0개 작성, export 대상·통계만 출력 (public 커밋 전 보안 게이트용) |
| `--share` | flag | off | 기존 private export와 분리된 Share-ready hard-stop gate. 기본 출력 `okf-share/` |
| `--approve-share VALUE` | str | 없음 | `--share` 전용 사람 승인 값. 정책의 정확한 값이 아니면 출력 전 중단 |

`exclude_paths`·`exclude_domains`·`exclude_slugs`·`sensitive_patterns` 최종값 = `schema/okf_export.yaml`(커밋됨) + gitignored `schema/okf_export.local.yaml` + CLI 인자(누적).

#### 보안 — 민감정보 게이트

| 메커니즘 | 동작 |
|---|---|
| `exclude_paths` (경로 글롭) | `business/**`·`canvas/**` 등 경로째 번들에서 제외. 1차 방어선 |
| `sensitive_patterns` (본문 스캐너) | included 페이지 본문/description 평문을 대소문자 무시 스캔 → `sensitive_hits`로 dry-run/log 표면화(차단 아님, 사람 검토용). 페이지 제외로 못 막는 본문 평문 실명·운영수치 탐지 |
| `exclude_slugs` (페이지 제외) | dry-run 검토 후 누출 확인된 페이지를 명시 제외 |
| 로컬 분리 | 🔴 실명·내부명 같은 민감 값은 **gitignored `schema/okf_export.local.yaml`에만** 둔다. 커밋되는 `okf_export.yaml`에 넣으면 그 자체가 누출. main()이 두 파일을 병합 |
| fail-loud 경고 | `okf_export.local.yaml` 부재 시(fresh clone/CI) 게이트 비활성 → stderr에 🔴 경고. 그 상태로 커밋 금지 |

기본 export는 기존 private 동작을 유지한다. 공개용 `--share`는 더 엄격한 별도 경계다.
`schema/okf_export.yaml`과 하나 이상의 gitignored local security config가 모두 있어야 하며,
모든 비-구조제외 후보가 명시적 `scope: shared|private` 및 허용된 `type`을 가져야 한다.
local security는 `exclude_slugs`·`sensitive_patterns`만 추가하며 base policy/승인 재정의는 거부한다.
wiki 후보 symlink·root 밖 해석 경로, malformed/recursive YAML, 민감 hit, skipped page, broken link,
빈 공개 번들, 설정/인벤토리 drift는 hard-stop이다.
`--share --out`의 canonical path가 레포 루트 또는 private input root인 `raw/**`·`wiki/**`
안에 있으면 stage·receipt·output을 만들기 전에 hard-stop한다.

통과 시 `strip_internal=True`로 sibling stage에 전체 번들을 만든다. 입력 wiki bytes와 설정
fingerprint를 재검증하고 `share-manifest.json`·`.okf-share-bundle`까지 완성한 뒤 디렉토리
rename으로만 게시한다. portable POSIX에서 기존 디렉토리 갱신은 단일 atomic replace가 아니므로
두 rename 사이 reader가 경로 부재를 볼 수 있다. 첫 rename 전 sibling recovery receipt를 durable
write하며, 각 전환 뒤 hard exit 시 기존/신규 완성본을 다음 share 실행에서 복구한다. published
bundle과 receipt가 모두 없는 상태는 만들지 않는다. manifest는
결정적 JSON이고 included/excluded 수, source reference 수, classification/scope 수,
`sha256:` configuration fingerprint만 기록한다. 페이지 경로·본문·민감 패턴·승인 값은 금지한다.

#### 출력 파일

| 파일 | 설명 |
|------|------|
| `okf/{dir}/{slug}.md` | 변환된 frontmatter + 본문. 실제 wiki 디렉토리 구조를 미러 |
| `okf/{dir}/index.md` | 디렉토리별 목차 (title + description 링크) |
| `okf/index.md` | 번들 루트 목차 (type별 섹션 + Directories 섹션) |
| `okf/log.md` | export 이력 + 변환 경고 (깨진 링크·제외 페이지·skipped) |
| `okf/.okf-bundle` | 번들 센티넬. 재export 시 이 마커가 있는 디렉토리만 안전하게 정리 |
| `okf-share/share-manifest.json` | Share-ready 집계와 configuration fingerprint만 담은 redacted deterministic manifest |
| `okf-share/.okf-share-bundle` | 완성된 share bundle만 원자 교체하기 위한 추가 센티넬 |

#### 안전 가드

- `raw/`·`wiki/`는 읽기 전용. 출력은 `out_dir`(기본 `okf/`)에만.
- `out_dir`가 `wiki_dir`이거나 그 조상(레포 루트 등)이면 거부(`rmtree` 데이터 손실 방지).
- `out_dir`가 심볼릭 링크면 거부(`resolve()` 전 원본 인자로 검사 — 링크 대상 삭제 방지).
- 비어있지 않은 `out_dir`에 `.okf-bundle` 마커가 없으면 덮어쓰기 거부.
- frontmatter 값의 `---`는 em-dash로 치환, date/datetime은 ISO 문자열로 직렬화 (OKF consumer의 `text.split("---")`·`json.dumps` 호환 보장).

#### 호환성 단일 진실 — 링크 정규식

OKF minimal consumer는 본문에서 `\]\((/[^)]+\.md)\)` 패턴으로 엣지를 추출한다. export가 만드는 모든 페이지 링크는 `/`로 시작하는 번들 루트 절대경로 + `.md` 끝이라 이 패턴에 잡힌다. 라운드트립 검증: **콘텐츠 노드 수 = export 페이지 수**, 엣지 수 = 깨지지 않은 wikilink 수.

> ⚠ minimal consumer가 `rglob("*.md")`로 노드를 모으면 페이지 외에 디렉토리별 `index.md`·`log.md`도 노드로 잡힌다(OKF 관례 파일). 라운드트립에서 "노드 = 페이지 수"를 검증하려면 frontmatter `title`이 없는 메타 파일(index/log)을 콘텐츠 노드에서 제외하고 센다.

---

### scripts/express.py

wiki/ 페이지를 읽어 창작물(블로그, 강의, 요약, 리포트) 초안 컨텍스트를 준비한다. 실제 LLM 합성은 Claude Code가 담당하며, 이 스크립트는 관련 페이지 수집·경로 안내 역할을 한다.

#### CLI 인자 전체 (subcommand 방식)

```
uv run python scripts/express.py blog TOPIC
uv run python scripts/express.py lecture TOPIC [--slides N]
uv run python scripts/express.py summary (--week | --month)
uv run python scripts/express.py report TOPIC
```

| subcommand | 인자 | 기본값 | 설명 |
|------------|------|--------|------|
| `blog` | `topic` (positional) | — | 블로그 포스트 초안. 관련 페이지 최대 5개 수집 |
| `lecture` | `topic` (positional), `--slides N` | slides=5 | 강의 슬라이드 초안. 관련 페이지 최대 6개 수집 |
| `summary` | `--week` 또는 `--month` (mutually exclusive, required) | — | 주간(7일) 또는 월간(30일) 요약 |
| `report` | `topic` (positional) | — | 심층 리포트. 관련 페이지 최대 8개 수집 |

#### 관련 페이지 수집 알고리즘 (index.md 파싱 + 키워드 점수)

`collect_related_pages(topic, max_pages)` 함수:

1. `index.md` 전체 텍스트를 로드한다.
2. `topic`을 공백·하이픈·슬래시로 분리해 키워드 목록을 만든다 (2자 이상만).
3. `[[slug]] — 설명` 패턴의 줄을 파싱한다.
4. `slug + 설명` 문자열에서 각 키워드 등장 횟수의 합산을 점수로 계산한다.
5. 점수 내림차순으로 상위 `max_pages`개를 선택한다.
6. 각 slug에 대해 `wiki/` 전체에서 `{slug}.md` 파일을 탐색해 내용을 반환한다.

`summary`는 `collect_recent_pages(days)` 방식: `wiki/insights/`, `wiki/concepts/`, `wiki/projects/`에서 frontmatter `updated:` 또는 mtime 기준으로 최근 N일 이내 파일을 반환.

#### 출력 경로 규칙

```
express/{type}/YYYY-MM-DD-{slug}.md
```

- `blog` → `express/blog/2026-05-17-ai-agent-design-pattern.md`
- `lecture` → `express/lecture/2026-05-17-context-first-orchestration.md`
- `summary` → `express/summary/2026-05-17-weekly-summary.md`
- `report` → `express/report/2026-05-17-habix-competitor.md`

slug 생성: 소문자·숫자·하이픈만 허용, 연속 하이픈 합치기, 60자 절삭.

#### blog 피드백 루프 (raw/blog/ 복사)

`cmd_blog()` 실행 시 `express/blog/` 저장 후 `raw/blog/`에도 동일 파일을 복사한다. 이로써 blog 초안이 다음 ingest 사이클에서 wiki로 재컴파일되는 피드백 루프가 형성된다.

#### 재사용 메타 frontmatter (US-007)

각 초안 frontmatter에 `_reuse_meta_block()`이 재사용 추적 필드를 추가한다: `output_type`, `published_url: null`, `source_pages`(인용한 wiki 페이지 slug 리스트), `derived_insight: null`, `reuse_as: []`. `source_pages`는 `curate.build_express_reuse_index()`가 스캔해 `memory_score`의 `express_reuse` 신호로 환원한다.

#### episode 기록 (저장 직후, fail-soft — US-002)

각 subcommand는 `save_draft()` 성공 직후 `_record_express_episode()`로 에피소드 1건을 `episode.append`한다. `task_type`은 `express_blog`·`express_lecture`·`express_summary`·`express_report`, `status`는 `draft_ready`. `read_pages`는 수집한 wiki 페이지(WIKI_ROOT 상대경로), `procedures_used`는 `["collect_related_pages"]`. **fail-soft**: 헬퍼는 fail-loud(`EpisodeSchemaError`)지만 호출측이 try/except로 감싸 원장 실패가 express 명령을 깨지 않게 한다(stderr warn 후 계속).

---

### scripts/lib/frontmatter_utils.py

신규 코드 + US-003이 건드리는 리더가 공용으로 쓰는 frontmatter 파서(fail-loud). "단일 출처"는 **아니다** — `export_graph.py` 미니파서 등 미접촉 리더는 그대로 둔다(Rule 3, 다음 접촉 시 이관 후보).

| 함수 | 시그니처 | 동작 |
|------|----------|------|
| `read_fm` | `read_fm(text) -> (dict, str)` | `(frontmatter_dict, body)` 반환. 블록 없으면 `({}, text)`. 빈 블록(`safe_load→None`)은 `({}, body)`. 블록은 있으나 YAML invalid거나 dict 아니면 `FrontmatterParseError` raise(조용한 `{}` 반환 금지 — 덮어쓰기 데이터 손실 방지) |
| `write_fm` | `write_fm(fm, body) -> str` | `'---\n{yaml}---{body}'`. 키 순서 보존(`sort_keys=False`), `allow_unicode=True` |

예외: `FrontmatterParseError(ValueError)`. 의존: `pyyaml`.

---

### scripts/episode.py

5층 메모리 OS의 ② "턴 이후 쓰기" 기질. 각 실행(ingest·express·ai_answer)이 구조화된 episode 레코드를 월별 샤드 `episodes/YYYY-MM.jsonl`에 append한다. 헬퍼는 **fail-loud**, 호출측은 **fail-soft**(§C1 참조).

| 함수 | 시그니처 | 동작 |
|------|----------|------|
| `append` | `append(record, episodes_dir=EPISODES_DIR) -> None` | 필수 9키·타입 검증 → 위반 시 `EpisodeSchemaError`(쓰기 0). 샤드명은 `timestamp`의 `YYYY-MM`에서 도출. 직렬화 불가 값(Path·datetime·set 등)도 FS 부작용 전에 `EpisodeSchemaError`로 통일 |
| `read_recent` | `read_recent(task_type=None, topic=None, limit=10, episodes_dir=EPISODES_DIR) -> list[dict]` | 최신 샤드부터 읽어 `timestamp`를 실제 시각(tz-aware)으로 파싱해 desc 결정적 정렬. `task_type` 정확일치 필터, `topic`은 `user_goal`+`inputs` 키워드 매칭. 깨진 줄(JSON 오류·non-dict)은 skip(견고한 read) |

- 필수 키: `timestamp`(str)·`task_type`(str)·`user_goal`(str)·`inputs`(dict)·`read_pages`(list)·`procedures_used`(list)·`outputs`(dict)·`status`(str)·`notes`(str). 상세 계약은 §C1.
- `EPISODES_DIR = scripts/../episodes`. 예외: `EpisodeSchemaError(ValueError)`. 의존: 표준 라이브러리만.

---

### scripts/procedures.py

procedural 기억 로더. `procedures/`의 `.md`(각 `memory_type: procedural`)를 slug 단위로 나열·로드해 `brain_context`의 후보 절차 주입에 쓰인다. frontmatter는 `lib/frontmatter_utils.read_fm` 재사용.

| 함수 | 시그니처 | 동작 |
|------|----------|------|
| `list_procedures` | `list_procedures(procedures_dir=PROCEDURES_DIR) -> list[str]` | `.md` slug를 정렬 반환(결정성). 부재 디렉토리는 `[]`(견고) |
| `read_procedure` | `read_procedure(slug, procedures_dir=PROCEDURES_DIR) -> (dict, str)` | `slug.md` → `(frontmatter, body)`. 파일 부재 시 `FileNotFoundError`(fail-loud — 오타·stale slug 노출) |

`PROCEDURES_DIR = scripts/../procedures`(repo 루트, git-tracked + OKF 제외 = §D 보안 경계).

---

### scripts/brain_context.py

5층 메모리 OS의 "턴 직전 조립" 기질(작업기억 = 휘발성, 저장 안 함). 흩어진 메모리를 **결정적 순서**의 한 팩으로 모아 Claude Code가 곧바로 읽게 한다. 임베딩 없는 file-first 조립(<1s).

#### CLI 인자 전체

| 인자 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `--task` | str | (필수) | 작업 목표(섹션 1) |
| `--topic` | str | (필수) | 관련 페이지·episode·procedure 검색 토픽 |
| `--type` | choices: `query`\|`express`\|`curate`\|`custom` | `custom` | episode `task_type` 필터 파생(`query→ai_answer`, `curate→curate`, 나머지 None) |
| `--max-pages` | int | `5` | 관련 페이지 최대 수 |
| `--json` | flag | off | JSON 출력(기본: 마크다운) |

#### 6 섹션 (결정적 순서)

1. **목표** — `--task` 원문
2. **관련 semantic 페이지** — `express.collect_related_pages(topic, max_pages)` 재사용 + **graph degree 동점 정렬**(정렬 키: 키워드 점수 desc, `graph.json` degree desc, slug asc)
3. **최근 관련 episode** — `episode.read_recent(task_type=파생, topic, limit)`
4. **후보 procedure** — `procedures.list_procedures` + topic 키워드 필터(slug/제목/본문)
5. **제약** — CLAUDE.md 가드레일 4항 정적 주입(raw 출처 없는 wiki 사실 금지 등)
6. **출처 경로** — 포함 페이지의 raw/ provenance

핵심 함수: `build_pack(*, task, topic, type_="custom", max_pages=5, wiki_root=None, episodes_dir=None, procedures_dir=None, limit=5) -> dict`, `render_markdown(pack) -> str`, `render_json(pack) -> str`. 경로 인자는 None이면 저장소 루트 기본값(테스트는 tmp 주입). 의존: `episode`·`express`·`procedures`·`lib.frontmatter_utils`(웹 계층 `wiki_app`에 의존하지 않음 = 격리).

---

### scripts/memory_health.py

5층 메모리 OS의 ③ "오프라인 제어(메타 기억)" 관측기. wiki·episodes·procedures를 읽어 집계 리포트를 생성한다. **기본(`--report`)은 read-only** — curate의 distill/lifecycle/purge와 달리 어떤 wiki 페이지도 이동·삭제·생성·수정하지 않는다(side-effect-free 진단). **페이지 쓰기는 opt-in `--fix`만** 수행한다(v0.3 WS-3).

#### CLI 인자

| 인자 | 설명 |
|------|------|
| `--report` | `wiki/memory_health_report.md` 생성(기본 동작 — 플래그 유무와 무관하게 리포트 생성, **read-only·페이지 무변경**) |
| `--fix` | **opt-in** 자동 보강 가능분만 fix: ⑴ frontmatter `summary` 결손 → 본문 첫 문단 40~200자 추출 ⑵ `source_count` 결손/불일치 → `len(sources)` 캐시 갱신 ⑶ `updated` 형식 결손 채움. 쓰기는 `lib/frontmatter_utils.read_fm/write_fm` 경유(body 무손상)·**idempotent**(정상 페이지 2회 실행 바이트 무변경). **본문·근거 부족은 fix하지 않고 alert만**(가짜 보강 금지), 파싱 실패 페이지도 무변경+alert(fail-loud). 리포트에 `fixed: N / alert: M` 요약 포함 |
| `--dry-run` | fix 대상 목록만 stdout 출력 — 어떤 파일도 변경하지 않음(리포트 미작성) |

#### 출력 파일

| 파일 | 설명 |
|------|------|
| `wiki/memory_health_report.md` | 집계 리포트. `--report`의 유일한 부작용 = 이 파일 쓰기뿐 (`--fix`는 추가로 자동 보강 페이지의 frontmatter만 갱신) |

리포트 섹션: 메모리 타입별 페이지 수 · orphan semantic(inbound 0) · stale 절차(>180일) · 최근 에피소드(개수+`task_type`/`status` 집계+ts 브리프) · top 재사용 페이지 · 저신뢰 페이지(confidence<0.5) · **weak content(본문<800자 OR 근거<2건 OR H2<3개 — path·issues 상세, 기존 기준에 추가)** · archive 후보(`memory_score` 주석) · (`--fix` 시) `fixed: N / alert: M` 요약. curate의 *순수* 헬퍼(`compute_memory_score`·`build_link_graph`·`build_express_reuse_index`·`build_episode_ref_index`·`load_graph_index`)만 재사용한다(curate 쓰기 함수 호출 금지).

🔴 **프라이버시(§D):** episode `notes`/`inputs`/`outputs`/`user_goal` 같은 verbatim 본문은 **절대** 리포트에 넣지 않는다(집계 수치+메타만). 리포트 파일명은 `okf_export.META_FILES`에 등재돼 공개 OKF 번들로 export되지 않는다.

핵심 함수: `generate_report(wiki_root, *, episodes_dir=None, procedures_dir=None, express_dir=None, now=None, fix_result=None) -> str`, `write_report(...) -> Path`(결정성용 `now` 주입 가능), `run_fix(wiki_root, *, dry_run=False, now=None) -> FixResult`(fixed·alerts).

---

## 스키마 명세

### schema/sources.yaml 필드

`sources` 배열의 각 항목:

| 필드 | 필수 | 타입 | 설명 |
|------|------|------|------|
| `id` | 필수 | str | 소스 고유 식별자. `.sync_state.json`의 키로 사용 |
| `source` | 필수 | str | 소스 디렉토리 경로. `~/` 확장 지원 |
| `target` | 필수 | str | `raw/` 하위 대상 경로. 예) `raw/til/` |
| `ttl_days` | 선택 | int | lifecycle TTL. `0`이면 만료 없음 |
| `extensions` | 선택 | list[str] | 복사할 확장자 목록. 미설정 시 전체 5종 지원 |
| `exclude_tags` | 선택 | list[str] | frontmatter `tags`에 이 값이 포함되면 복사 제외 |
| `require_keywords` | 선택 | list[str] | 하나라도 본문에 포함된 파일만 복사 (대소문자 무시, md·txt만 판정) — v0.3.0 |
| `min_word_count` | 선택 | int | 공백 분리 단어 수 미만 파일 제외 (md·txt만 판정) — v0.3.0 |
| `disabled` | 선택 | bool | `true`이면 해당 소스 전체 건너뜀 |
| `note` | 선택 | str | 소스 설명 (사람이 읽는 주석) |

`lifecycle` 섹션:

| 필드 | 설명 |
|------|------|
| `archive_dir` | archive 대상 폴더. 기본값: `wiki/archive/` |
| `domains.{name}.ttl_days` | 도메인별 TTL. `0`이면 lifecycle 대상 제외 |

현재 도메인별 TTL:

| 도메인 | ttl_days |
|--------|----------|
| concepts, tools, people, projects, business, lecture | 0 (영구) |
| insights | 365 |

### schema/config.yaml 필드

| 필드 | 값 예시 | 설명 |
|------|---------|------|
| `llm.engine` | `cli` \| `api` | LLM 호출 방식 선택 |
| `llm.model` | `claude-opus-4-8` | API 모드에서 사용할 모델 ID (기본값) |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | API 모드에서 읽을 환경변수명 |
| `llm.max_tokens` | `8192` | API 모드 최대 토큰 수 |

### wiki 페이지 frontmatter 전체 필드

```yaml
---
title: 페이지 제목
type: concept | tool | person | project | business | lecture | insight
domain: AI/LLM | teaching | habix | tools | personal-projects
tags: [태그1, 태그2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [raw/파일경로1, raw/파일경로2]
distill_level: 0          # 0~3, curate --distill이 관리
access_count: 0           # 자동 pageview 기록 없음; 명시적 curate --record-access의 stats를 distill 시 동기화
last_accessed: null       # YYYY-MM-DD
last_distilled: null      # YYYY-MM-DD
resonance: high | medium | low   # ingest 시 수동 지정 (선택)
# --- Agent Memory OS (US-003) — 아래 6필드는 전부 optional·null-safe, 없어도 기존 페이지 유효 ---
memory_type: semantic | episodic | procedural | meta | working   # (선택)
retention: durable | seasonal | ephemeral   # decay 힌트 (선택)
confidence: 0.9            # 0..1 float (선택)
source_count: 6            # len(sources) 캐시 (선택)
last_verified: YYYY-MM-DD  # 최종 검증일 (선택)
decay_policy: default      # 명명된 정책 키 (선택)
# --- Team-Ready 훅 (v0.3.2 WS-6 P1) — 전부 optional·null-safe, 없어도 기존 페이지 유효 ---
owner: 이름                # 페이지 소유자/기여자 태그 (선택). 다중 기여자 병합은 P2 예약(미구현)
scope: private | shared    # (선택) private=okf 공개 번들 제외 / shared·미지정=포함(하위호환)
---
```

`distill_level`, `access_count`, `last_accessed`, `last_distilled`는 `curate.py`의 `ensure_distill_fields()`가 없으면 자동으로 기본값을 추가한다.

`memory_type`·`retention`·`confidence`·`source_count`·`last_verified`·`decay_policy`는 **Agent Memory OS(US-003) 구현됨** — 전부 optional·null-safe하며, 없는 기존 페이지도 그대로 유효하다(`lib/frontmatter_utils.read_fm` 관용 파싱, 무파손 실측). `memory_health.py`가 `memory_type`(미선언 시 `semantic`)·`confidence`로 페이지를 집계하고, `curate.compute_memory_score`가 `source_count`(=`len(sources)`)를 점수 신호로 쓴다. 필드 정의·decay 시맨틱은 §C2.

`owner`·`scope`는 **Team-Ready 훅(v0.3.2 WS-6 P1) 구현됨** — 둘 다 optional·null-safe(기존 6필드와 동일 원칙). `scope: private`인 페이지는 `okf_export`가 공개 OKF 번들에서 **항상 제외**한다(`business/**`와 같은 레일 — `stats.excluded`+`stats.excluded_private`에 집계, 이를 가리키던 링크는 redact). `scope` 미지정·`shared`는 포함(하위호환·기존 동작 불변). `owner`는 keep 모드에서 `x-llmbrain-owner`로 보존, `--strip-internal`이면 다른 내부 필드와 함께 제거(외부 공유본 소유자 노출 방지). 다중 기여자 병합(owner 기반)은 **P2 예약(미구현)**.

---

## 상태 파일

### .ingest_state.json 구조

```json
{
  "processed": [
    "raw/til/2026-05-15-rag-patterns.md",
    "raw/newsletters/2026-05-14-weekly.md"
  ]
}
```

`processed` 배열: WIKI_ROOT 기준 상대 경로 문자열 목록. `--mark-done` 실행 시 현재 `raw/`의 모든 파일로 덮어쓴다.

### .sync_state.json 구조

```json
{
  "til": "2026-05-17T07:00:12.345678",
  "meetings": "2026-05-16T07:00:10.123456"
}
```

키: `source_id`, 값: ISO 8601 datetime. 없는 키는 `"1970-01-01T00:00:00"`으로 간주한다.

### wiki_stats.json 구조

```json
{
  "page-slug": {
    "access_count": 2,
    "last_accessed": "2026-05-16"
  }
}
```

파일 위치: WIKI_ROOT 바로 아래 (`wiki_stats.json`). 기본 browse/query 경로는 읽기
전용이고, 갱신은 명시적 CLI 동작으로 분리한다.

| 경로 | frontmatter 갱신 | wiki_stats.json 갱신 |
|------|-----------------|----------------------|
| CLI `curate --record-access SLUG` | X | O |

`wiki_app/access.track`은 기존 명시적 library write API로 남지만 검색·페이지 보기·AI
query에서는 호출하지 않는다. `distill` 실행 시 두 값 중 큰 값을 취해 frontmatter와
동기화한다.

---

## 의존성

`pyproject.toml` 기준 (name: `llm-wiki`, requires-python: `>=3.11`):

| 패키지 | 버전 제약 | 용도 |
|--------|-----------|------|
| `pyyaml` | ≥6.0 | `schema/sources.yaml`, `schema/config.yaml` 파싱 |
| `pymupdf` | ≥1.24.0 | PDF 텍스트 추출 (`fitz` 모듈명) |
| `markdownify` | ≥0.12.0 | URL 스크랩 시 HTML → Markdown 변환 |
| `httpx` | ≥0.27.0 | URL 스크랩 HTTP 요청 |
| `python-frontmatter` | ≥1.1.0 | `sync_raw.py`의 `exclude_tags` 필터링용 frontmatter 파싱 |
| `python-docx` | ≥1.1.0 | `.docx` 텍스트 추출 |
| `python-pptx` | ≥0.6.23 | `.pptx` 텍스트 추출 |
| `anthropic` | ≥0.40.0 | API 모드 LLM 호출 (engine: api 선택 시 사용) |

설치: `uv sync` 또는 `pip install -e .`

---

## 자동화 — OpenClaw cron (구 launchd, 2026-06-02 전환)

> **2026-06-02 변경:** launchd 잡 `ai.habix.llm-wiki`는 macOS TCC가 `~/Documents` 하위 스크립트 exec을 차단해 매일 `exit 126`으로 실패(`.launchd.log` 도배)하여 **제거**했다. 데일리 자동화는 이제 OpenClaw cron `llm-wiki-daily`(`~/.openclaw/cron/jobs.json`, `0 07 * * *` Asia/Seoul, `agentTurn`)가 담당하며 STEP 1 `sync_raw.py --quiet` → STEP 2 `ingest.py` 미처리 확인 → STEP 3 CLAUDE.md 규칙대로 claude ingest 후 `ingest.py --mark-done`을 수행한다. **STEP 4(주간 월요일 `curate --audit --lifecycle` + distill)도 2026-06-02 cron 페이로드에 추가**되어 `date +%u == 1`(월요일)에만 실행된다. 아래 launchd/`run_daily.sh` 기술은 **참조용**이다.

### (참조) 구 launchd 설정

### plist 경로

```
~/Library/LaunchAgents/ai.habix.llm-wiki.plist
```

Label: `ai.habix.llm-wiki`

### 실행 시간

매일 오전 7시 0분 (`StartCalendarInterval: Hour=7, Minute=0`).  
`RunAtLoad: false` — 등록 즉시 실행하지 않음.

로그 경로: `260516_llm_brain/.launchd.log` (stdout·stderr 동일 파일)

### run_daily.sh 4단계 플로우

스크립트 위치: `wiki/projects/260515_llm_wiki/scripts/run_daily.sh`

| 단계 | 동작 | 조건 |
|------|------|------|
| **Step 1** | `sync_raw.py --quiet` 실행 — sources.yaml 소스에서 raw/ 델타 미러링 | 항상 실행 |
| **Step 2** | `ingest.py` 실행 — 미처리 raw 파일 수 확인 | 항상 실행 |
| **Step 3** | `claude --dangerously-skip-permissions -p "...ingest 해줘"` 실행 후 `ingest.py --mark-done` | Step 2 exit code = 1 (미처리 파일 있음) 시에만 실행 |
| **Step 4** | `curate.py --audit --lifecycle` 후 `claude -p "...distill 해줘"` 실행 | 매주 월요일(`$(date '+%u') = "1"`)에만 실행 |

---

## LLM 엔진 통합

**공통 진입점**: `scripts/lib/llm_client.py`의 `call_llm(prompt, *, config, max_tokens)`(비스트림, 텍스트 반환)·`stream_llm(prompt, *, config)`(스트림, 텍스트 청크)이 `schema/config.yaml`의 `llm.engine`으로 cli/api 를 분기한다. 반환 형식은 두 엔진 동일(텍스트). config 부재/부분/오류는 항별 기본값 + stderr warn 으로 안전 폴백하며(engine 미설정=cli 기본), `anthropic` 은 함수 내부 지연 import 라 cli 모드에는 미설치여도 무방하다(부재 시 api 모드만 친절한 `LLMError`). `wiki_app/api.py`의 AI 답변 2경로(비스트림·스트림)가 이 진입점을 경유한다.

### CLI 모드 (기본, engine: cli)

`schema/config.yaml`의 `engine: cli` 설정 시 사용. Claude Code CLI를 재사용한다.

```bash
claude --dangerously-skip-permissions -p "프롬프트 내용" >> "$LOG" 2>&1
```

- API 키 불필요
- Claude Code 설치 필수
- `run_daily.sh`에서 직접 호출(세션 없이 단발 실행). wiki_app 경로는 `llm_client`가 `claude -p` subprocess 를 관리(idle timeout·process-group kill·stderr 동시 drain).

### API 모드 (engine: api, 구현됨)

`schema/config.yaml`의 `engine: api` 설정 시 사용. `anthropic` SDK 로 직접 호출한다(`llm_client._call_api`/`_stream_api`).

```python
import anthropic

client = anthropic.Anthropic(api_key=os.environ[config["api_key_env"]])
response = client.messages.create(
    model=config["model"],
    max_tokens=config["max_tokens"],
    messages=[{"role": "user", "content": prompt}],
)
# 텍스트 블록만 추출해 텍스트로 반환(cli 와 동일 형식). 스트림은 messages.create(stream=True)
# 의 content_block_delta 텍스트 델타를 청크로 yield.
```

- 환경변수: `ANTHROPIC_API_KEY` (또는 `api_key_env` 지정값). 부재 시 명확한 `LLMError`(조용한 실패 금지).
- 모델: `claude-opus-4-8` (기본값)
- 최대 토큰: `8192` (기본값)

의존성: `anthropic>=0.40.0`(`pyproject.toml`). cli 전용 사용 시에도 설치돼 있으나, `llm_client`는 지연 import 라 미설치 환경의 cli 모드도 정상 동작한다.

---

## 커맨드 라우팅 테이블

| 사용자 발화 | 실행 스크립트 | LLM 액션 |
|-------------|---------------|----------|
| `uv run python scripts/ingest.py` | `ingest.py` | 없음 (미처리 파일 목록 출력만) |
| `uv run python scripts/ingest.py --url URL` | `ingest.py` | 없음 (스크랩 후 raw/ 저장) |
| `uv run python scripts/ingest.py --file PATH` | `ingest.py` | 없음 (복사 후 raw/ 저장) |
| `uv run python scripts/ingest.py --note TEXT` | `ingest.py` | 없음 (raw/ 저장) |
| `uv run python scripts/ingest.py --priority-only` | `ingest.py` | 없음 (high resonance 목록만) |
| `uv run python scripts/ingest.py --mark-done` | `ingest.py` | 없음 (상태 기록) |
| `uv run python scripts/sync_raw.py` | `sync_raw.py` | 없음 (파일 복사만) |
| `uv run python scripts/curate.py --audit` | `curate.py` | 없음 (정적 분석) |
| `uv run python scripts/curate.py --distill` | `curate.py` | 없음 (`distill_queue.md` 생성만) |
| `uv run python scripts/curate.py --lifecycle` | `curate.py` | 없음 (후보 목록 출력) |
| `uv run python scripts/export_graph.py` | `export_graph.py` | 없음 (`wiki/graph.json` 생성) |
| `uv run python scripts/okf_export.py [--dry-run] [--strip-internal]` | `okf_export.py` | 없음 (규칙 기반 변환 → `okf/` 번들 생성, dry-run은 목록만) |
| `uv run python scripts/brain_context.py --task "…" --topic "…" --type query\|express\|curate\|custom [--max-pages N] [--json]` | `brain_context.py` | 없음 (작업기억 팩 조립 출력 — Claude가 읽고 실행) |
| `uv run python scripts/memory_health.py --report` | `memory_health.py` | 없음 (읽기전용 집계 → `wiki/memory_health_report.md`, 페이지 무변경) |
| `uv run python scripts/doctor.py --guided [--profile demo\|personal-private\|share-ready]` | `doctor.py` | 없음 (repo root를 script 기준으로 확인하고, 제품/개인 데이터 쓰기·개인 콘텐츠 스캔 없이 정확히 3개 프로필 또는 선택 프로필의 다음 행동 1개 출력. Personal-private는 `sources.yaml` 또는 없을 때 committed example을 preview하고 Demo는 UI가 아닌 설치 검증임을 표시. Share-ready는 policy/local config/explicit scope 전제와 정확한 승인 명령을 안내. 단, `uv run` 자체의 Python 환경/cache 생성 가능성은 별도) |
| `uv run python scripts/doctor.py [--fix]` | `doctor.py` | 없음 (기존 설치 진단; `--fix`일 때만 디렉터리·sources 설정 생성) |
| (라이브러리 — `procedures.list_procedures`/`read_procedure`) | `procedures.py` | 없음 (`brain_context`·`memory_health`가 import; 독립 CLI 아님) |
| `uv run python scripts/curate.py --purge` | `curate.py` | 없음 (파일 이동) |
| `uv run python scripts/curate.py --record-access SLUG` | `curate.py` | 없음 (stats 기록) |
| `uv run python scripts/express.py blog TOPIC` | `express.py` | Claude가 `express/blog/*.md` 읽고 본문 작성 |
| `uv run python scripts/express.py lecture TOPIC --slides N` | `express.py` | Claude가 `express/lecture/*.md` 읽고 슬라이드 작성 |
| `uv run python scripts/express.py summary --week` | `express.py` | Claude가 `express/summary/*.md` 읽고 요약 작성 |
| `uv run python scripts/express.py summary --month` | `express.py` | Claude가 `express/summary/*.md` 읽고 요약 작성 |
| `uv run python scripts/express.py report TOPIC` | `express.py` | Claude가 `express/report/*.md` 읽고 리포트 작성 |
| "ingest 해줘" (Claude Code 세션) | `CLAUDE.md` → `ingest.py` | Claude가 raw/ 읽고 wiki/ 컴파일 |
| "curate 해줘" (Claude Code 세션) | `CLAUDE.md` → `curate.py` | Claude가 wiki/ 감사·distill 수행 |
| "RAG에 대해 알려줘" (Claude Code 세션) | `CLAUDE.md` query 모드 | Claude가 `index.md` → wiki 페이지 로드 후 답변 |
| launchd 매일 07:00 | `run_daily.sh` | Step 3·4에서 `claude -p` 호출 |

---

# Agent Memory OS Upgrade — 설계 (Phase 1-3 구현 완료)

> **상태**: **Phase 0-3 구현 완료** (2026-06-28). 본 절은 *구현 설계서(HOW)*다 — 각 모듈의
> 현재형 인터페이스는 위 "스크립트 인터페이스"(`frontmatter_utils`·`episode`·`procedures`·
> `brain_context`·`memory_health`)·"스키마 명세"·"커맨드 라우팅 테이블" 절로 이관 완료. 본 §A~§D는
> 설계 근거(제어 루프·격리·점수 공식·보안 경계)의 단일 출처로 남는다.
> **US-002 완료**: curate `run_*` 후 `episode.append`(실행 요약)까지 배선됨 — 4 배선점
> (ingest·express·wiki_app·curate) 전부. (curate는 점수용 episode 읽기도 병행 — §C4 plug-in.)
> 요구사항과 진행·결정 로그의 내부 원본은 로컬 비공개 보관소에 있다.
> **근거 모델**: AI 에이전트 메모리 5층 구조(작업·에피소드·의미·절차·메타).

## §A — 척추: 폴더가 아니라 제어 루프

5층 모델의 핵심은 폴더 5개가 아니라 **계획시점 읽기 → 턴 이후 쓰기 → 오프라인 제어**의 순환이다.
의미 기억(semantic)은 이미 있는 `wiki/`이고, 나머지는 이 루프의 저장 기질·제어기다.

```
            ① 계획 시점에 읽기 (작업 기억 = 휘발성, 저장 안 함)
   ┌──────────────  scripts/brain_context.py  ──────────────┐
   │  goal + 관련 semantic(wiki) + 최근 episode + 후보 procedure + 제약 │
   └───────────────────────┬─────────────────────────────────┘
                           │ 이 팩을 들고 실행
   ┌───────────────────────▼─────────────────────────────────┐
   │  실행: ingest · express · query(wiki_app) · curate         │
   └───────────────────────┬─────────────────────────────────┘
                           │ ② 턴 이후 쓰기 (append-only, fail-soft)
                  scripts/episode.py → episodes/YYYY-MM.jsonl
                           │
   ┌───────────────────────▼─────────────────────────────────┐
   │  ③ 오프라인 제어 (메타 기억): curate memory_score          │
   │     promote / merge / archive / decay 판정 + rescue        │
   └───────────────────────┬─────────────────────────────────┘
                           │ 되먹임: 건강한 semantic만 생존
                           └────→ 다음 ①이 더 좋은 기억을 읽음
```

차별 레버는 폴더(episodes/·procedures/)가 아니라 **②→③→① 되먹임**이다.

## §B — 모듈 지도 (격리: 각 단위 = 한 책임 + 명시 인터페이스)

| 모듈 | 상태 | 단일 책임 | 인터페이스 | 의존 | PRD US |
|---|---|---|---|---|---|
| `scripts/lib/frontmatter_utils.py` | 신규(토대) | 신규+접촉 리더 **공용** 파서(fail-loud; "단일 출처" 아님) | `read_fm(text)->(dict,body)`, `write_fm(fm,body)->str` | pyyaml | 003 토대 |
| `scripts/episode.py` | 신규 | append-only 에피소드 원장 | `append(record)->None`, `read_recent(task_type,topic,limit)->list[dict]` | 표준 라이브러리 | 001 |
| `scripts/brain_context.py` | 신규 | 작업기억 팩 조립(휘발성) | CLI `--task --topic --type --max-pages [--json]` | `express.collect_related_pages`, `episode.read_recent`, procedures loader | 005 |
| `procedures/` + loader | 신규 | 재사용 절차 저장/로드 | `list_procedures()`, `read_procedure(slug)->(fm,body)` | frontmatter_utils | 004 |
| `scripts/curate.py` | **변경** | +메타 점수·rescue(`run_lifecycle`/`_purge`)·episode 기록 | `compute_memory_score(...)->float`; `run_*` 후 `episode.append` | graph.json, episodes, express/ | 006·002 |
| `scripts/express.py` | **변경** | +재사용 메타 frontmatter, +episode 기록 | `save_draft` 직후 `episode.append` | episode | 007·002 |
| `scripts/ingest.py` | **변경** | +staging episode 기록 | 저장 성공 직후 `episode.append`(status=pending) | episode | 002 |
| `wiki_app/api.py` | **변경** | +AI답변 episode 기록 | 비스트림·스트림 핸들러 **둘 다 `finally`**에서 `episode.append`(최종 status 포함) | episode | 002 |
| `scripts/memory_health.py` | 신규 | 읽기전용 건강 리포트 | `--report` → `wiki/memory_health_report.md` | episode, curate, frontmatter_utils | 008 |
| `schema/okf_export.yaml` | **변경** | 방어 제외 2줄 | `exclude_paths += episodes/**, procedures/**` | — | 보안 |

**격리 원칙:** `brain_context`는 웹 계층(`wiki_app/search.py`)이 아니라 `scripts/express.collect_related_pages`(현 75–106행, 이미 결정적)를 재사용 — 스크립트가 웹에 의존하지 않게. `frontmatter_utils`는 **신규 코드 + US가 건드리는 리더만** 채택(현재 4벌 파서 중 `export_graph.py` 등 미접촉 파일은 그대로 = Rule 3). → 따라서 "단일 출처"가 **아니다**; `export_graph.py` 미니파서는 블록리스트 데이터손실 이력(PROGRESS ① R1)이 있어 **다음 접촉 시 이관 후보**로 둔다(Claude#5a·Codex C6).

## §C — 파일 계약

### C1. 에피소드 레코드 — `episodes/YYYY-MM.jsonl` (월별 샤드, append-only)

1줄 1 JSON 객체. 필수 키:

```json
{ "timestamp": "2026-06-27T07:30:00+09:00",
  "task_type": "express_blog|ingest_url|ingest_file|ingest_note|curate|ai_answer",
  "user_goal": "string",
  "inputs": {},
  "read_pages": ["wiki/concepts/x.md"],
  "procedures_used": ["collect_related_pages"],
  "outputs": {},
  "status": "ok|abstained|pending_wiki_compilation|draft_ready|timeout|error",
  "notes": "string" }
```

- `episode.append(record)`: 필수 키·타입 검증 → 위반 시 `EpisodeSchemaError` (헬퍼는 **fail-loud**).
- **호출측은 try/except로 감싸 warn+continue** (메인 명령 경로는 **fail-soft** = PRD US-002 AC·FR-8).
- 샤드 파일명은 `timestamp`의 `YYYY-MM`에서 도출. 기존 줄은 절대 재작성 안 함.
- `read_recent(task_type=None, topic=None, limit=N)`: 최신 샤드부터, `timestamp` desc 결정적 정렬, `topic`은 `user_goal`/`inputs` 키워드 매칭.

### C2. frontmatter 신규 필드 (US-003, 전부 optional·null-safe)

기존 frontmatter 블록(위 "wiki 페이지 frontmatter 전체 필드")에 **추가된(구현됨)** 필드. `lib/frontmatter_utils.read_fm` 관용 파싱이라 없는 페이지도 유효(무파손 실측):

```yaml
memory_type: semantic      # semantic | episodic | procedural | meta | working
retention: durable         # durable | seasonal | ephemeral (decay 힌트)
confidence: 0.9            # 0..1 float (선택)
source_count: 6           # len(sources) 캐시 (선택)
last_verified: 2026-06-27 # date (선택)
decay_policy: default     # 명명된 정책 키 (선택)
```

`procedures/` 파일은 `memory_type: procedural`. OKF export 시 keep 모드 → `x-llmbrain-*`, `--strip-internal` → 전부 제거(§D).

### C3. brain_context 팩 (US-005)

`brain_context.py --task "..." --topic "..." --type query|express|curate|custom --max-pages N [--json]`
→ 결정적 순서 6 섹션(테스트 가능):

1. **목표** (`--task`)
2. **관련 semantic 페이지** — `express.collect_related_pages(topic, max_pages)` 재사용 + **graph degree tie-breaker**(US-005 요구; 현 함수는 키워드 점수만이라 `graph.json` degree로 동점 정렬을 brain_context에서 보강) + `find_wiki_file`의 비정렬 `rglob` 정렬(결정성, Claude·Codex C5)
3. **최근 관련 episode** — `episode.read_recent(task_type=--type, topic, limit)`
4. **후보 procedure** — procedures loader, topic 키워드 필터
5. **제약** — CLAUDE.md 가드레일(raw 출처 없는 wiki 사실 금지 등) 정적 주입
6. **출처 경로** — 포함 페이지의 raw/ provenance

markdown 기본, `--json`은 동일 구조. <1s 목표(file-first, 임베딩 없음).

### C3-b. claim_ledger (P0 query provenance)

`schema/claim_ledger.md` 계약의 strict `ClaimRecord`를 repository-root
`claims.jsonl`에 저장한다. `scripts/claims.py build`만 atomic replace를 수행하고,
`context`와 API query는 읽기 전용이다.

- required provenance: `claim_id`, `statement`, `kind`, `raw_path`, 정확한 64-hex
  `raw_sha256`, `valid_from`, `valid_until`, `status`, `trust`; `locator`만 optional
- allowed status: `active | stale | superseded`; trust: `trusted | untrusted`
- malformed/partial/unknown-field/duplicate record 하나라도 있으면 API/CLI 전체 fail closed
- source inventory 오류는 전체 ledger 검증을 유지하면서 affected slug/count와 정확한
  `uv run python scripts/claims.py build` 복구 명령만 노출하고 statement/raw path는 숨김
- trusted query/citation: `active + trusted + current validity + current raw hash match`만 허용
- stale와 raw mutation은 각각 `stale`, `source_hash_mismatch`로 구분해 제외
- 외부 capture statement는 single-line canonical JSON data로 격리하고 명령/인용 불허
- LLM citation token: `[claim:slug-N]`; invalid/non-active claim 하나라도 있으면 답변 거부
- usable trusted claim이 없으면 exact `관련 정보 없음`만 허용하고 API/SSE status를
  `abstained`로 구분. LLM/stream을 호출하지 않고 source 목록은 비우며 안전한 제외
  사유 count와 다음 행동 하나 제공. SSE sequence는 meta → exact abstention chunk 1개 → done
- SSE meta는 `delivery_mode: verified-buffered`를 명시하고 UI도 "검증 후 일괄 표시"로
  표현. `_AI_STREAM_MAX_CHUNKS`/`_AI_STREAM_MAX_BYTES` 안에서 buffering 후 동일 gate 적용

### C4. memory_score (US-006, 재사용 우선·결정적)

```
score = 35·norm(express_reuse) + 25·norm(episode_ref) + 15·norm(centrality)
      + 10·norm(access_count)  + 10·recency         +  5·norm(source_count)
```

- `norm(x) = min(x / CAP, 1.0)`. **CAP·가중치는 `schema/config.yaml`** (사람 튜닝 = Rule 5).
- `centrality = w1·inbound_degree + w2·betweenness` (`wiki/graph.json`).
- `recency` = age 감쇠(예: <30일 1.0 → 365일 0.0 선형).
- `express_reuse` = `express/` 산출물이 이 slug를 `source_pages`/`[[link]]`로 인용한 횟수(express/ 스캔, 캐시).
- `episode_ref` = episode `read_pages`에 이 slug가 등장한 횟수. **단 `task_type=express_*` 에피소드는 제외**(Codex C3) — 같은 express 런이 `express_reuse`와 `episode_ref`를 동시에 올리는 이중계산 방지. `episode_ref`는 ingest·ai_answer·curate 등 *비-express* 운영 읽기만 집계.
- **PRD US-006 입력 대비 v1 매핑(추적성):** `resonance` v1 제외(wiki frontmatter 미저장 — 컴파일 시 필터링; v2 후순). `stale_age`는 `recency` 감쇠에 흡수(별도 항 아님). `contradiction_risk`는 v1 제외(교차 페이지 의미 매칭 필요 = 범위 밖). `episode_ref`는 PRD 미열거 신호이나 재사용 우선 철학에 따라 추가. → 나머지 6개(express_reuse·access·recency·centrality·source_count + episode_ref)만 점수화.
- **plug-in ① 정렬 — `curate.py` `run_distill()` 현 343–356행:** 임계 게이트(access≥10/distill<3=urgent 등) **유지**(신규 페이지 보호·backward-compat). 점수는 **tier 내 정렬에만** 사용(이 버킷은 자문용 = `distill_queue.md`에 줄만 쓰고 아무것도 안 옮김 → 보존 결정 못 함).
- **plug-in ② rescue — 실제 archive 게이트(`run_lifecycle`: `age>ttl AND inbound==0`, + `_purge`):** 여기가 페이지를 루프에서 *실제로* 들어내는 곳(Claude#2 HIGH). `run_distill` 자문 버킷이 아님. **rescue 규칙(상대):** archive 후보 집합에서 `memory_score` **상위 N%** 는 archive 제외 → promote/keep-review. **상대 임계 이유(#4):** 출시 직후 express/episode 이력이 비어 재사용 가중치(60%)가 ~0이라 절대 임계는 과녁이 움직임. **술어 불일치 해소:** distill(access==0·age>90) vs lifecycle(inbound==0·age>ttl)이 달라 — PRD가 걱정하는 "재사용되나 inbound 0인 orphan"이 정확히 lifecycle 대상이므로 rescue를 lifecycle에 걸어야 보존이 실제로 작동.
- `distill_queue.md`·`curate_report.md`에 점수+사유 기입(top promote / merge-review / archive-review / decay).
- `config.yaml` **부재** 시 옛 임계 동작 fallback. **부분/오류 키**(누락 weight·CAP, 0/음수 CAP, 타입오류)도 안전 처리(Codex C4): 누락=기본 상수, 오류=해당 항 기본값 + stderr warn(조용한 flaky/crash 금지). 결정성 테스트는 `now`를 고정 주입.

## §D — 보안 경계 (one-way door)

- `episodes/`·`procedures/`는 **repo 루트**(wiki/ 밖) → `okf_export.py`는 `wiki/`만 rglob 스캔하므로 **구조적으로 OKF에 안 보임**.
- **방어 이중망**: `schema/okf_export.yaml` `exclude_paths`에 `episodes/**`·`procedures/**` 명시(향후 wiki/ 밑 오배치 대비). 게이트는 탐지형이 아니라 규칙형이라 명시 규칙만이 누출을 막는다.
- 새 메모리 필드 → keep 모드 `x-llmbrain-*` / `--strip-internal` 전부 제거. **외부 공유는 `--share` 필수이며 strip을 강제**.
- `.gitignore`: `episodes/` 전체. 예외 = `examples/episode-schema-example.jsonl` 1개만 커밋(문서·테스트용).
- 커밋 전 dry-run ceremony(기존)에 점검 항목 추가: export 목록에 `episodes`/`procedures`/`memory_health_report` 미등장 단언.
- 🔴 **memory_health 리포트 누출 차단(Claude#1·Codex C1, HIGH):** `memory_health.py`는 `wiki/memory_health_report.md`에 쓰는데 `okf_export.py`가 `wiki/`를 rglob 스캔하고 현 `META_FILES`에 이 파일이 **없다**(episode 요약 = 격리한 사적 운영맥락의 파생). → ① `memory_health_report.md`를 okf `META_FILES`에 **명시 추가**(루트 직속 skip 작동; title-부재 skip은 취약해 의존 금지) ② 리포트는 **집계 수치만**(verbatim episode 본문 금지). 이 확장은 리포트를 도입하는 **Phase 3에서 동반**.
- **Phase 0 "무변경" 단서(Codex C8):** okf config 2줄·파서 유틸 추가는 *episodes/·procedures/가 wiki/ 밖일 때만* no-op. Phase 0 테스트는 export 결과뿐 아니라 **okf config 값 자체**를 단언.

---

# v0.3 Quality-Driven Curation — 설계 (v0.3.0 구현 완료 2026-07-04)

> 요구사항과 진행·결정의 내부 원본은 로컬 비공개 보관소에 있다.
> **v0.3.0 범위는 구현 완료**: §B의 `lib/memory_score.py` 추출 · `lib/gates.py`(G-1~G-4) ·
> `curate --reweave`(위 "스크립트 인터페이스" curate 절 "#### reweave" 참조) ·
> `memory_health --fix` · ingest hard dedup · sync_raw capture 필터, §C의 observing/rejected·
> reweave_queue, §D 3점 방어. **v0.3.1 구현 완료**: WS-1 synthesis 대상 선정(→ reweave_queue.md
> `## 종합 대상`) + shrink 가드(`synthesis.guard_no_shrink` — 대상 한정 스냅샷) · WS-5 모순 후보
> 탐지(→ `contradiction_queue.md`, 후보 0이면 미생성). **v0.3.2 구현 완료**: §B `lib/llm_client.py`
> (engine: cli|api 통합 진입점 + wiki_app/api.py 경유). **계획으로 남은 것**: §E `run_daily.sh` 배치 개정.

## §A — 척추: LLM 실행 경계 (v0.2.0 계약 불변)

```
[결정적 — scripts/, claude 없이 pytest 통과]        [생성 — commands/curate.md Step, Claude Code 수행]
reweave 스캔 → weak 판정·자동 fix(fm/summary 결손)   synthesis 작성(## 인사이트 (종합))
gates 판정(G-1~G-4) → created/enriched/observing/rejected   reconciliation 서술(## 반론/갱신 + superseded)
모순 후보 탐지 → contradiction_queue.md
synthesis 대상 선정 → reweave_queue.md
```

- 초안 PRD의 curate.py 내 LLM 직접 호출(`synthesize_page` 훅)안은 **기각** — 기존 distill_queue.md 패턴(스크립트=큐, 커맨드=실행)을 확장한다.
- shrink 가드(본문·sources 감소 시 저장 거부 + `WARN shrink`)는 결정적이므로 스크립트 측.

## §B — 모듈 배치

```
scripts/
  lib/memory_score.py   ← curate.py 293–624행(점수 코어: _score_terms·compute_memory_score·build_*_index) 추출 [선행 리팩터, 동작 무변경]
  lib/gates.py          ← Promotion Gates G-1~G-4: evaluate_promotion(candidate) -> Decision. 유사도 = _merge_token_set Jaccard 재사용
  lib/llm_client.py     ← [v0.3.2 구현 완료] "LLM 엔진 통합" 절의 인터페이스(engine: cli|api). call_llm/stream_llm 공통 진입점 + subprocess 수명(_terminate_proc·_kill_process_group, api.py 가 re-export). wiki_app/api.py 의 AI 답변 2경로(비스트림·스트림)가 경유
  curate.py             ~ --reweave 플래그(argparse boolean, 기존 패턴): run_distill+run_lifecycle+find_merge_candidates 오케스트레이트 + weak 신규 기준
  memory_health.py      ~ --fix (자동 보강 가능분만·idempotent; 본문/근거 부족은 alert만 — 가짜 보강 금지)
  ingest.py             ~ is_duplicate 저장 전 재배선 + (is_dup, target_slug, score) 반환
  sync_raw.py           ~ require_keywords·min_word_count 실구현 (sources.yaml 필드 추가)
```

- reweave weak 기준(신규): 본문<800자 OR 근거<2건 OR H2<3개 — 기존 memory_health 기준(orphan·confidence<0.5·stale>180일)에 **추가**, 대체 아님.
- reweave episode: `task_type: reweave` — `build_episode_ref_index` 집계에서 제외(express_* 제외와 같은 이유: 자기 점수 되먹임 차단).

## §C — 파일·frontmatter 계약 (v0.3 신규)

- 신규 폴더: `wiki/observing/`(7일 유예) · `wiki/rejected/`(사유 분류 기각). **gitignored**.
- 신규 큐: `wiki/reweave_queue.md`(구현됨 — v0.3.1 `## 종합 대상` 섹션 추가) · `wiki/contradiction_queue.md`(구현됨, v0.3.1 — 후보 ≥1일 때만 생성) — `distill_queue.md`와 동일 체크박스 패턴. 공개 번들 봉인의 **활성 기전은 `okf_export.collect()`의 "frontmatter title 부재 → skip"**(큐 파일은 title이 없음), `schema/okf_export.yaml` `exclude_paths`의 `reweave_queue.md`는 큐가 title을 얻는 경우 대비 **백스톱**이다(okf `META_FILES` 등재로의 이관은 okf_export.py 접촉 시 — v0.3.0은 무수정). 실증(V1): okf `--dry-run` 에서 `skipped=[('reweave_queue.md','frontmatter title 부재')]`, observing/rejected 는 `excluded`.
- frontmatter 신규(전부 optional): `gate_status: created|enriched|observing|rejected`(episodes JSONL `status`와 충돌 회피 개명) · `observation_expires` · `recurrence: N` · `angles: [..]` · `signal_count: N` · `synthesis_updated` · `superseded_claims: [..]` · `last_reconciled` · [v0.3.2 구현됨] `owner`(소유자 태그) · `scope: private|shared`(private=okf 공개 번들 제외, 미지정=shared 하위호환). 다중 기여자 병합은 P2 예약(미구현).
- frontmatter 쓰기: `lib/frontmatter_utils` 경유(body 무손상; fm 블록 yaml 재직렬화 허용 — "raw write" 정의 확정, PROGRESS ③). 파서 신설 금지.

## §D — 보안 경계 (one-way door, observing/rejected 3점 방어)

`wiki/observing/`·`wiki/rejected/`는 사적 판단 로그(기각 사유 포함)다. okf `_load_pages`가 `wiki/` rglob 무차별 스캔이므로 **폴더 신설과 같은 커밋에**:
1. `schema/okf_export.yaml` `exclude_paths` += `observing/**`·`rejected/**` (+ okf dry-run 미등장 단언 + config 값 자체 단언 — §D Phase 0 단서와 동일 패턴)
2. `curate.find_all_wiki_pages` 제외 집합 += 두 폴더 (정규 audit/distill/lifecycle/merge-review에서 격리)
3. `LIFECYCLE_EXEMPT` 또는 동등 제외 (observing 만료는 gates가 자체 관리, TTL decay와 분리)
+ `.gitignore` += 두 폴더 · `index.md`에 미기록(wiki_app 검색이 index.md 기반이므로 이것으로 웹 비노출).

**scope:private 필터 (v0.3.2 WS-6 P1, team-ready 훅):** `okf_export._is_scope_private`가 frontmatter `scope: private` 페이지를 공개 번들에서 **항상 제외**한다(`exclude_paths`·`--strip-internal` 플래그와 무관 — public 커밋은 one-way door라 플래그 게이트로 두면 flag 없는 fresh clone/CI가 private을 유출한다). `business/**`와 같은 레일: `stats.excluded`에 반영 + `stats.excluded_private`로 분리 집계(dry-run/log에 표면화) + 이를 가리키던 링크는 redact. `scope` 미지정·`shared`는 포함(하위호환). `--strip-internal`은 소유자 노출 방지로 `owner`/`scope` 내부 필드도 제거(비-예약 필드라 x-llmbrain-* 전면 제거의 부산물 — 테스트로 고정).

## §E — 배치 개정 (run_daily.sh)

```
Step 1 sync_raw.py (매일)                       [기존]
Step 2 ingest.py 감지 (매일)                     [기존]
Step 3 claude -p ingest (미처리 시)              [기존 — 경로 drift(~/Documents/llm-wiki) 수정 선행]
Step 4 curate --reweave --fix (매일)             [신규]
Step 5 curate --distill (월요일)                 [기존]
Step 6 curate --reweave --fix --weekly-summary (일요일)  [신규]
```

## §F — 테스트 계약 (경계값)

- gates: 799/800자 · 근거 1/2건 · 유사도 0.74/0.75 · 반복 1/2회 경계 유닛테스트. claude CLI 불요.
- reweave idempotency: 정상 노드 2회 실행 무변경. dedup: 동일 슬러그 재투입 시 미생성(저장 전 차단).
- **착수 전 안전망**: `is_duplicate` 현 동작 고정 테스트(현재 0건) 선작성 후 재배선(RED→GREEN).
- 회귀: memory_score 추출 전후 점수 값 동일 단언 · 기존 ingest/express/query 무변경 · okf 누출 0.
