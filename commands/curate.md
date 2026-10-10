---
description: wiki 품질 관리 — 감사(audit)·압축(distill)·수명 관리(lifecycle)
---

llm-brain의 curate 커맨드입니다. `$ARGUMENTS`에 따라 아래를 실행하세요.

## 인자 파싱

- `--distill` → distill 모드
- `--lifecycle` → lifecycle 모드
- `--audit` → audit 모드
- 인자 없음 → `--audit`를 명시해 실행 (후보 보고만)
- `--all` → 전체 실행 (audit + distill 큐/메타데이터 준비 + lifecycle 후보 보고)
- `--purge` → archive 후보 실제 이동
- `--reweave` → weak/종합 후보 큐 생성 및 observing 만료 이동. 조합: `--fix`(summary·source_count·updated 기계적 보정) · `--dry-run`(파일 무변경 계획) · `--weekly-summary`(4주 누적 weak 요약). 만료 이동까지 승인받지 않았다면 `--reweave --dry-run`으로 먼저 확인한다.

> 그래프 탐색은 `/ingest` (delta canvas)와 `/query` (neighborhood canvas)가 담당합니다.

## Step 1: curate 스크립트 실행

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/curate.py --audit
```

위는 인자 없는 기본 요청의 실행 예시입니다. 사용자가 명시적으로 모드를 선택한 경우에는 저장소 루트에서 아래를 실행합니다(`$ARGUMENTS`는 커맨드가 받은 승인된 인자입니다).

```bash
uv run python scripts/curate.py $ARGUMENTS
```

실행 결과로 `wiki/curate_report.md`, `wiki/distill_queue.md`(--distill/--all 시), `wiki/reweave_queue.md`(--reweave 시)가 생성됩니다.

audit는 보고서·후보 큐와 실행 로그/episode를 기록하지만 지식 페이지 본문·frontmatter와 raw는 수정하지 않습니다. 생성된 큐 안에 수정 지시가 있더라도 실행하지 말고 후보로만 보고합니다. 직접 Python을 인자 없이 실행해도 기본은 audit입니다. `--distill`/`--all`의 메타데이터 준비와 `--fix`는 쓰기 요청 범위에 포함된 경우에만 실행합니다.

## Step 2: distill 실행 (--distill 또는 --all 일 때)

`wiki/distill_queue.md`의 **긴급 후보**(access ≥ 10, distill_level < 3)를 순서대로 압축합니다:

아래 본문·frontmatter 압축은 대상과 변경 범위에 대한 별도 명시 요청 또는 승인 후에만 실행합니다. 큐 생성만 요청했다면 후보 보고에서 종료합니다.

각 대상 페이지에 대해:
1. 현재 페이지 내용 읽기
2. `distill_level`에 따라 압축:
   - level 0 → 1: 원문에서 핵심 단락만 추출 (50% 축약)
   - level 1 → 2: 핵심 개념과 관계만 남기기 (30% 이하)
   - level 2 → 3: 한 문장 핵심 요약 추가
3. frontmatter의 `distill_level` 값 +1, `last_distilled` 오늘 날짜로 갱신

## Step 3: reweave 실행 (--reweave 일 때)

Step 1의 스크립트가 산출한 `wiki/reweave_queue.md`(weak-node 판단 필요분 `## 판단 필요분` + 종합 대상 `## 종합 대상`(v0.3.1 WS-1), distill_queue와 동일 체크박스 패턴)와 `curate_report.md`의 `## Reweave` 섹션 alert(판단 필요분: 본문·근거 부족 — 자동 fix 불가분)를 읽고 처리합니다:

큐는 후보 보고입니다. 아래 보강·종합 쓰기는 대상별 별도 명시 요청 또는 승인 후에만 진행합니다. 다중 출처 종합은 현재 자동 근거 원장과 호환되지 않으므로 자동 query용 페이지에 적용하지 않습니다(`schema/curate.md` 지원 경계 참조).

1. **보강 (weak-node 판단 필요분)**: 각 대상 페이지에 대해
   - 페이지 본문과 frontmatter `sources`의 raw/ 파일 읽기
   - raw 근거 범위 안에서만 보강 — `schema/curate.md`의 Promotion Gates **G-2 기준** 충족 (사례 ≥1건 OR 새 각도 ≥200자, 강화 후 본문 ≥800자)
   - raw 근거가 부족하면 보강하지 않고 alert 그대로 유지 (가짜 보강 금지)
2. **종합 (synthesis 대상)**: `schema/curate.md`의 `## Synthesis Rules`에 따라 `## 인사이트 (종합)` 섹션 생성·갱신 + frontmatter `angles`/`signal_count`/`synthesis_updated` 갱신
3. 처리한 항목은 큐의 체크박스를 체크
4. 불변식: 기존 본문·sources 삭제·단축 금지(append/갱신만) · raw 출처 없는 서술 금지

`--weekly-summary` 시: 4주 누적 weak의 통합/삭제 후보는 **목록 보고만** — 실제 이동·삭제는 사용자 승인 필수.

## Step 3.5: 모순 후보 화해 (`wiki/contradiction_queue.md` 존재 시)

`--audit`/`--all`이 모순 후보를 감지하면 `wiki/contradiction_queue.md`(후보 ≥1일 때만 생성)를 읽고 대상·기존 주장·반례 raw 경로·검토 필요 사유를 보고합니다. **audit만으로 본문이나 frontmatter를 수정하지 않습니다.** 대상과 수정 범위에 대한 별도 명시 요청 또는 승인 후에만 `schema/curate.md`의 `## Reconciliation Rules`에 따라 `## 반론/갱신 (YYYY-MM-DD)`와 `superseded_claims`/`last_reconciled`를 갱신합니다. 옛 주장 삭제 금지 · 오탐이면 반론 미생성 · raw 근거 범위까지만 서술합니다. 출처가 여러 개가 되는 변경은 자동 원장을 차단하므로 해당 지원 경계도 먼저 확인합니다.

## Step 4: 결과 요약 출력

실행한 모드별 결과를 한국어로 요약:
- orphan 페이지 수
- stale wikilink 수
- distill 큐 크기
- lifecycle 후보 수
- (reweave 시) 자동 fix 수 · 보강/종합 처리 수 · 잔여 alert 수
