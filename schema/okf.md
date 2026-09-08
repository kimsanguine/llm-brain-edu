# OKF ↔ llm-brain 매핑 (Phase 1 Export)

## 역할

`wiki/`(내부 슈퍼셋)를 OKF v0.1 호환 번들 `okf/`로 투영할 때의 **변환 규칙 레퍼런스**다.
`scripts/okf_export.py`가 이 규칙대로 frontmatter·링크·본문을 바꾼다.
내부 포맷(`wiki/`)은 바꾸지 않는다 — 경계(`okf/`)에서만 변환한다.

- 동작 계약과 설계 배경: `SPEC.md`
- 제외 설정: `schema/okf_export.yaml`

## OKF v0.1 핵심 가정

OKF는 **`type`만 필수**고 나머지 예약 필드는 선택이다. 스키마는 **추가 필드를 금지하지 않는다.**
따라서 llm-brain의 풍부한 생애주기 필드를 `x-llmbrain-*` 네임스페이스로 보존해도 OKF 규격에 합법이다.

## 1. frontmatter 필드 대응표

OKF 예약 필드는 아래 순서로 출력한다(`type`·`title` 외에는 소스에 없으면 생략).

| # | OKF 예약 필드 | llm-brain 소스 | 변환 규칙 |
|---|---|---|---|
| 1 | `type` | `type` | 그대로 (OKF type은 자유값 → `concept`·`tool`·`person` 등 합법). **필수** |
| 2 | `title` | `title` | 그대로 |
| 3 | `description` | `description` (없으면 본문) | fm에 있으면 그대로, 없으면 §3 규칙 기반 추출 |
| 4 | `resource` | `resource` | fm에 있을 때만 그대로 |
| 5 | `tags` | `tags` | 있을 때만 그대로 |
| 6 | `timestamp` | `updated`(없으면 `created`) | `updated → timestamp` 키 이름 변경. 둘 다 없으면 생략 |

### x-llmbrain-* 보존 (keep 모드)

`--strip-internal`이 아니면, 예약 6필드에 매핑되지 않은 **나머지 모든 fm 키**를
`x-llmbrain-{key}`로 보존한다.

- 보존 규칙: `k not in {type, title, description, resource, tags, updated}` 이면 `x-llmbrain-` 접두 후 출력.
- 예: `domain → x-llmbrain-domain`, `created → x-llmbrain-created`, `distill_level → x-llmbrain-distill_level`,
  그리고 `access_count`·`last_accessed`·`last_distilled`·`resonance`·`sources` 등 전부.
- `updated`는 `timestamp`로 이미 매핑되므로 `x-llmbrain-updated`로 중복 보존하지 않는다.

### `--strip-internal` (strip 모드)

OKF 예약 6필드만 남기고 `x-llmbrain-*`를 전부 생략한다. 이는 최소 투영일 뿐
Share-ready 승인은 아니며, 공개 경계는 §6의 `--share`를 사용한다.

### 네임스페이스 보존의 근거

- **합법성**: OKF는 `type`만 필수라 추가 필드가 규격 위반이 아니다.
- **자기참조·디버깅**: distill 단계·access 통계·sources 출처가 번들에 남아 있으면
  okf/ 만 봐도 wiki/ 로 역추적이 쉽다.
- **무손실 왕복**: keep 모드 번들은 내부 필드를 잃지 않으므로 향후 재흡수(P2 가정 시)에 유리하다.

## 2. wikilink → OKF 마크다운 링크 변환

OKF consumer는 본문 링크를 **번들 루트 기준 절대경로**로 기대한다.

| 입력 (`wiki/`) | 출력 (`okf/`) |
|---|---|
| `[[rag-patterns]]` | `[rag-patterns](/concepts/rag-patterns.md)` |
| `[[rag-patterns\|RAG 패턴]]` | `[RAG 패턴](/concepts/rag-patterns.md)` |
| 깨진 링크 (대상 페이지 없음) | 텍스트만 남기고 링크 해제 + `okf/log.md`에 경고, `broken_links`에 기록 |

### slug → 번들경로 해석

페이지 로드 단계에서 **slug → 번들경로 맵**을 구축한다(export_graph의 basename fallback 방식 재사용).

- 번들경로 = `"/" + rel` (예: `/concepts/rag-patterns.md`). 파일도 `okf/<rel>`에 동일 미러.
- `[[X]]` 해석 순서:
  1. `X`가 slug에 정확히 있으면 그것
  2. `"/"+X`로 끝나는 slug가 유일하면 그것 (basename fallback)
  3. 둘 다 아니면 **깨진 링크** → 텍스트만 남기고 log 경고

본문은 링크 변환 외에는 건드리지 않는다.

## 3. description 규칙 기반 추출 (LLM 아님)

`description`이 fm에 없을 때만 본문에서 추출한다. **결정적 변환이므로 코드 처리**(모델 호출 아님).

우선순위:
1. frontmatter `description` (있으면 그대로)
2. 본문 `## 핵심…` 섹션 첫 문장 (`핵심`·`핵심 요약`·`핵심 공식` 등 `핵심`으로 시작하는 헤딩)
3. 본문 첫 문단(헤딩 제외) 첫 문장

추출 후 wikilink·마크다운 마크업 제거, 표·다이어그램·코드펜스·번호목록·수식 라인은 건너뛴다. 약어(`Carlos E.`)·번호(`2.`)에서 잘리지 않게 처리하고, 품질 미달(버전 문자열·콜론 라벨·6자 미만)이면 빈 문자열.

## 4. 호환성의 단일 진실 — 링크 정규식

```
\]\((/[^)]+\.md)\)
```

OKF minimal consumer(Google 공개판)는 이 정규식으로 본문에서 엣지를 추출한다.
**이 패턴이 호환성의 단일 진실**이다 — export가 만드는 모든 페이지 링크는 반드시 이 패턴에 잡혀야 한다.

패턴 분해:
- `\]\(` — 마크다운 링크의 `](` 경계
- `(/[^)]+\.md)` — **`/`로 시작**(번들 루트 절대경로)하고 **`.md`로 끝나는** 경로를 캡처
- `\)` — 닫는 괄호

함의:
- 상대경로(`./foo.md`·`foo.md`)는 이 패턴에 안 잡힌다 → 반드시 `/`로 시작하는 절대경로로 출력.
- 외부 URL(`https://...`)이나 `.md` 아닌 링크는 엣지로 취급되지 않는다(의도된 동작).
- 라운드트립 검증: 번들의 노드 수 = export 페이지 수, 엣지 수 = 깨지지 않은 wikilink 수.

## 5. exclude 보안 경계 (경로 글롭)

`schema/okf_export.yaml`의 `exclude_paths`가 **1차 보안 필터**다.

- **경로 글롭** 기준이라 도메인 분류기 오탐 여지가 없다 = 구조적 보장.
  민감 경로(`business/**`)는 분류 라벨과 무관하게 무조건 빠진다.
- 매칭된 페이지는 파일을 안 쓰고 `ExportStats.excluded`에 기록된다.
- `exclude_domains`(frontmatter domain 라벨)·`exclude_slugs`(개별 페이지)는 보조 필터.
  `business/` 밖에 산재한 민감 페이지는 dry-run 검토 후 `exclude_slugs`로 추가한다.

### legacy private dry-run 검토

기본 `okf/`를 검토할 때:

1. `--dry-run`으로 export 대상 목록을 사람이 눈으로 확인
2. `business/` 페이지가 목록에 **0개**임을 확인
3. 그 후에만 커밋

exclude는 *추론*이 아니라 *감사 가능한 설정*이라야 이 게이트가 신뢰할 수 있다 →
제외 규칙을 코드에 숨기지 않고 `schema/okf_export.yaml`에 명시한다.

## 6. Share-ready manifest gate

기본 `okf/` export는 기존 private 동작을 유지한다. 외부 공유는 반드시 별도 `--share`와
사람이 직접 입력한 `--approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT`를 함께 사용한다.

- base policy와 gitignored local security config가 모두 필요하다.
- `--config`는 canonical `schema/okf_export.yaml`만 허용하고, local security config는
  `exclude_slugs`·`sensitive_patterns` 추가만 허용한다. 승인/base policy 재정의는 거부한다.
- 구조적으로 제외되지 않은 모든 후보는 명시적 `scope: shared|private`와 허용된 `type`이 필요하다.
- wiki 후보 symlink와 wiki root 밖으로 해석되는 경로, malformed/recursive YAML은 읽기·출력 전에 거부한다.
- 민감 hit, skipped page, broken link, 빈 공개 번들은 출력 전에 hard-stop한다.
- 통과한 결과만 sibling stage에서 완성한다. 디렉토리 갱신은 두 rename이라 reader-visible 경로의
  연속성을 보장하지 않지만, 첫 rename 전 durable receipt를 기록해 hard exit를 복구 가능하게 한다.
- `share-manifest.json`은 included/excluded, source, classification, scope 집계와 설정 SHA-256만
  기록하며, 경로·본문·민감 패턴·승인 값을 기록하지 않는다.
