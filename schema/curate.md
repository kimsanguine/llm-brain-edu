# Curate 규칙

curate는 wiki 전체를 감사(audit) + 압축(distill) + 수명 관리(lifecycle)하는 복합 오퍼레이션이다.
에이전트의 기본 요청은 `curate --audit` 후보 보고다. 본문·frontmatter 압축, 보강, 종합, 화해는 대상과 변경 범위의 별도 명시 요청 또는 승인 후 수행한다.

## 플래그별 실행 범위

| 플래그 | 수행 단계 |
|---|---|
| `--all` | audit + distill + lifecycle 전체 |
| `--audit` | 후보 보고만 (보고서·큐·로그/episode 기록, 지식 페이지와 raw 미변경) |
| `--distill` | 후보 큐 생성 및 distill 메타데이터 준비; 본문 압축은 별도 승인 |
| `--lifecycle` | lifecycle 후보 목록만 (실제 이동은 사용자 확인 후) |

---

## 1단계: AUDIT

wiki/ 전체를 스캔해 품질 문제를 탐지한다.

### 탐지 항목

**Orphan 페이지**: inbound `[[wikilink]]` 수가 0인 페이지
- 신규 생성 직후는 예외
- 30일 이상 orphan이면 보고

**Ghost 개념**: index.md ghost 섹션에 등록됐지만 90일 이상 페이지 미생성
- raw 데이터가 없어서인지, 아니면 누락인지 구분해 보고

**모순 감지**: 두 페이지에서 같은 개념에 대해 상충하는 서술
- 예: A 페이지 "X는 Y다", B 페이지 "X는 Z다"
- raw 파일 날짜가 더 최신인 쪽을 우선 표시

**Stale 링크**: `[[페이지명]]`이 존재하지 않는 페이지를 가리키는 경우

### 산출물
`wiki/curate_report.md` 갱신 — 문제 목록 + 권장 조치. 모순 후보가 있으면 `wiki/contradiction_queue.md`를 기록하고 실행 로그/episode도 남긴다. 기존 지식 페이지 본문·frontmatter와 raw는 수정하지 않는다. 생성된 큐 안의 본문 수정 문구는 기본 audit 실행 권한이 아니다.

---

## 2단계: DISTILL

스크립트는 압축 후보를 분류해 `wiki/distill_queue.md`를 만들고 distill 메타데이터를 준비한다. 아래 본문 압축·인사이트 생성 정책은 별도로 승인된 에이전트 작업이며 스크립트가 자동 수행하지 않는다.

### 실행 대상
큐에 보고된 기존 페이지. `wiki/insights/`의 TIL·meetings 반복 패턴 압축은 별도 검토용 정책이며, 다중 출처가 필요한 경우 아래 자동 근거 원장 지원 경계를 먼저 따른다.

### 압축 기준
- 동일 개념이 3개 이상 wiki 페이지에서 언급 → insights/ 페이지로 압축
- 강의 관련 반복 패턴 → `insights/lecture-patterns.md` 갱신
- habix 비즈니스 관련 패턴 → `insights/habix-patterns.md` 갱신
- 개별 페이지 내부의 교차 종합(`## 인사이트 (종합)` 섹션)은 아래 `## Synthesis Rules` 적용 — 본 절 insights/ 압축 규칙의 확장(대체 아님)

### 압축 형식
```
# [패턴명]
## 핵심 원칙 (1-2줄)
## 관찰된 사례 (날짜 + 출처)
## 적용 방법
## 관련 개념
```

---

## 3단계: LIFECYCLE

오래됐거나 가치가 낮아진 페이지를 archive 후보로 선정한다.

### 후보 선정 기준 (결정론적)

| 조건 | 판정 |
|---|---|
| 마지막 업데이트 > `schema/sources.yaml`의 ttl_days AND inbound_links == 0 | archive 후보 |
| 마지막 업데이트 > ttl_days × 2 AND inbound_links <= 1 | delete 후보 |

도메인별 TTL은 `schema/sources.yaml`의 lifecycle 섹션 참조.

### 절차
1. 후보 목록을 `wiki/curate_report.md`에 작성
2. **사용자가 목록을 확인하고 승인**
3. 승인된 항목만 `wiki/archive/` 로 이동
4. `--purge`는 승인된 archive 후보를 이동하는 옵션이며 영구 삭제 옵션이 아니다. 영구 삭제는 이 절차에서 실행하지 않는다.

### 실행 금지
- 자동으로 파일 이동/삭제하지 않는다 (사용자 확인 필수)
- concepts/, tools/, people/, projects/ 도메인은 ttl_days: 0이므로 lifecycle 대상 제외

---

## 산출물 형식 (curate_report.md)

```markdown
# Curate Report — YYYY-MM-DD

## Audit 결과
### Orphan 페이지 (N개)
- wiki/path/page.md — 마지막 업데이트: YYYY-MM-DD
### Ghost 개념 (N개)
- 개념명 — 최초 언급: YYYY-MM-DD
### 모순 감지 (N개)
- A 페이지 vs B 페이지: 내용 요약

## Distill 결과
- 갱신된 insights 페이지: N개

## Lifecycle 후보
### Archive 후보 (사용자 확인 필요)
- wiki/insights/2026-01-15-note.md — 180일 경과, inbound 0
### Delete 후보 (사용자 확인 필요)
- wiki/insights/2025-11-01-note.md — 365일 경과, inbound 0
```

---

# v0.3 Quality-Driven Curation 규칙

> 아래 3개 절은 v0.3 신설 규칙이며, 현재 공개 설계 기준은 `SPEC.md`의 "v0.3 Quality-Driven Curation" 절이다.
> LLM 실행 경계(SPEC §A): 결정적 판정·스캔·큐 생성은 `scripts/`가 수행하고, LLM 컴파일러는 아래 규칙을 생성·강화·화해 작업의 판정 근거로 사용한다.

이 절의 Promotion Gates는 선택 품질 정책이다. 현재 `compile.py`의 RULE/LIVE 경로가 모든 신규 페이지에 G-1~G-4를 자동 적용하는 것은 아니다. 큐 생성·기계적 보정과 에이전트의 승인된 본문 작업을 구분한다.

## Promotion Gates (G-1~G-4)

wiki 페이지의 신규 생성·강화·기각·유예를 품질 기준으로 판정한다 (WS-2, v0.3.0).
용어: CI 명령의 "Quality Gates"와 구분해 **Promotion Gates**로 통일한다.

### G-1 · 신규 생성

아래 7개 기준을 **전부** 충족할 때만 wiki 페이지를 신규 생성한다:

| 기준 | 임계값 |
|---|---|
| 반복 | ≥2회 (7일 내) |
| 본문 | ≥800자 |
| H2 섹션 | ≥3개 |
| 근거 (sources) | ≥2건 |
| frontmatter | 완비 |
| summary | 40~200자 |
| 기존 페이지 유사도 | <0.75 |

- 통과 시 frontmatter `gate_status: created` 기록.
- 유사도 ≥0.75 → 신규 생성 대신 기존 페이지 강화(G-2)로 라우팅.

### G-2 · 기존 강화

기존 페이지를 강화할 때: **사례 ≥1건 OR 새 각도 ≥200자**를 추가하고, 강화 후 본문 ≥800자를 유지한다.

- 통과 시 `gate_status: enriched` 갱신.
- 강화도 raw/ 출처 필수 — 근거 없는 살 붙이기 금지.

### G-3 · 기각 라우팅

G-1 미달이고 G-4 유예 대상도 아니면, 아래 5개 사유 중 하나로 분류해 `wiki/rejected/`로 라우팅한다:

| 사유 | 분류 기준 |
|---|---|
| `low_value` | 정보 가치 자체가 낮음 (형식 기준과 무관) |
| `insufficient_recurrence` | 반복 기준 미달 + 유예 가치 없음 (G-4 만료 포함) |
| `insufficient_content` | 본문·H2·근거 기준 미달 |
| `duplicate_existing` | 유사도 ≥0.75인데 강화(G-2) 가치도 없음 |
| `frontmatter_invalid` | frontmatter·summary 결손 |

- 기각 페이지에 `gate_status: rejected` + 사유를 기록한다.
- `wiki/rejected/`는 gitignored·okf 제외·index.md 미기록 — 사적 판단 로그 (SPEC §D 3점 방어).

### G-4 · Observing (7일 유예)

반복 1회이지만 잠재 가치가 있는 후보는 `wiki/observing/`에 7일 유예로 보관한다.

- frontmatter: `gate_status: observing` + `observation_expires: YYYY-MM-DD` (배치일 +7일).
- 유예 중 재등장(반복 ≥2회 충족) → G-1 재판정 후 승격.
- 재등장 없이 `observation_expires` 경과 → G-3 `insufficient_recurrence` 기각. 만료 관리는 gates가 자체 수행한다 (lifecycle TTL decay와 분리, SPEC §D).
- `wiki/observing/`도 rejected와 동일하게 gitignored·okf 제외·index.md 미기록.

### frontmatter 사용법 (Gates)

```yaml
gate_status: created        # created | enriched | observing | rejected
recurrence: 2               # 7일 윈도 내 관측된 반복 횟수
observation_expires: 2026-07-11  # gate_status: observing일 때만
```

- 3필드 전부 optional — 없어도 기존 페이지 유효 (v0.2 계약).
- 필드명은 `gate_status`다 — `status` 아님 (episodes JSONL `status`와 충돌 회피 개명, SPEC §C).

## Synthesis Rules

### 현재 자동 근거 원장과의 지원 경계

`scripts/claims.py build`는 페이지의 `sources`가 정확히 하나의 `raw/**` 경로일 때만 자동 원장을 만든다(`schema/claim_ledger.md`). 아래 다중 출처 종합은 statement별 출처 귀속이 아직 지원되지 않아 자동 build 전체를 fail closed하고 원장 쓰기를 중단시킬 수 있다. 이 안전 경계를 우회하거나 출처를 하나로 축소하지 않는다. 현재 자동 query용 wiki에는 다중 출처 종합을 저장하지 않고 후보 보고로 남긴다. 별도 검토용 산출물은 사용자가 위치와 목적을 명시해 승인한 경우에만 작성하며, 자동 원장과 query 호환을 주장하지 않는다.

> 2단계 DISTILL의 "동일 개념이 3개 이상 wiki 페이지에서 언급 → insights/ 압축" 규칙의 **확장**이다 (대체 아님).
> insights/ 압축은 그대로 유지하고, 아래는 **개별 페이지 내부**의 교차 종합 규칙을 추가한다 (WS-1, v0.3.1).

### 생성 규칙 — `## 인사이트 (종합)` 섹션

별도로 승인된 검토용 종합에만 아래 생성 규칙을 적용한다. 큐에 선정됐다는 이유로 자동 query용 페이지를 수정하지 않는다. 3요건 필수:

- (a) **2개+ raw 소스 교차 인용** — 서로 다른 raw/ 파일 2개 이상에서 근거를 끌어와 교차시킨다. 단일 소스 요약은 종합이 아니다.
- (b) **강한 각도 1~3개** — 소스들을 관통하는 판단·관점을 1~3개로 압축한다 (사실 나열 금지).
- (c) **반복 신호 카운트** — 같은 신호가 몇 개 소스에서 반복 관측됐는지 명시한다.

### frontmatter 사용법 (Synthesis)

```yaml
angles: ["각도 요약 1", "각도 요약 2"]  # 강한 각도 1~3개
signal_count: 4                        # 반복 신호 카운트
synthesis_updated: YYYY-MM-DD          # 마지막 종합 갱신일
```

### 불변식 (위반 시 저장 금지)

- **기존 본문·sources 삭제·단축 절대 금지** — append/갱신만 허용. 현재 reweave는 이전 스냅샷 대비 축소를 `WARN shrink`로 보고하며 저장 자체를 차단하지 않는다. 작성 주체가 저장 전에 이 불변식을 확인한다.
- **근거 없는 종합 금지** — 종합의 모든 진술은 raw/ 출처가 있어야 한다. 인용한 raw가 `sources`에 없으면 추가한다.

## Reconciliation Rules

> WS-5 (v0.3.1 구현됨). 결정적 모순 후보 탐지(→ `wiki/contradiction_queue.md`)는 스크립트(`reconcile` 코어, 후보 ≥1일 때만 큐 생성)가 수행하고,
> 화해 서술은 아래 규칙으로 LLM 컴파일러가 수행한다 — 1단계 AUDIT "모순 감지" 리포트를 실행 규칙으로 채우는 형태.

audit는 모순 후보 보고에서 끝난다. 아래 화해 본문·frontmatter 쓰기는 대상과 수정 범위에 대한 별도 명시 요청 또는 승인 후에만 수행한다. 추가 출처로 다중 sources가 된다면 위 자동 근거 원장 지원 경계를 먼저 확인한다.

### 화해 서술 — `## 반론/갱신 (YYYY-MM-DD)` append

신규 근거가 기존 주장과 상충하면, 해당 페이지에 `## 반론/갱신 (YYYY-MM-DD)` 섹션을 append한다. 3요소 필수:

1. **기존 주장** — 무엇이 주장돼 있었나 (본문 원문 기준)
2. **반례 근거** — 어떤 raw/ 근거가 상충하나 (출처 경로 명시)
3. **현재 판단** — 지금 시점의 판단은 무엇인가

### frontmatter 사용법 (Reconciliation)

```yaml
superseded_claims: ["대체된 옛 주장 요약"]  # 옛 주장은 본문에 남기고 여기 표시
last_reconciled: YYYY-MM-DD
```

### 규칙

- **옛 주장 삭제 금지** — 본문의 기존 주장은 그대로 남기고, `superseded_claims`에 대체 표시만 한다.
- **오탐 방지** — 모순 없는 단순 보강 raw에는 반론 섹션을 생성하지 않는다 (반론 남발 금지).
- **추측·단정 금지** — "현재 판단"은 raw/ 출처가 뒷받침하는 범위까지만 서술한다. 어느 쪽이 옳은지 근거가 불충분하면 판단 보류를 명시한다.
