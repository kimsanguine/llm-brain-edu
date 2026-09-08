---
description: wiki → private OKF export 또는 명시적 Share-ready manifest gate
---

llm-brain의 okf 커맨드입니다. `wiki/`(내부 슈퍼셋)를 OKF v0.1 호환 번들 `okf/`로
투영합니다. 기본 경로는 기존 개인용 export이고, 외부 공유는 별도의 `--share` gate만 사용합니다.
`$ARGUMENTS`에 따라 아래를 실행하세요.

## 인자 파싱

- `--dry-run` → 파일 미작성, export 대상·제외·통계만 출력 (보안 검토용)
- `--strip-internal` → OKF 예약 6필드만 (x-llmbrain-* 제거, 단독으로는 공유 승인 아님)
- `--exclude-slug <slug>` → 특정 페이지 추가 제외 (복수 가능)
- `--config <경로>` → private export 전용 override. `--share`는 canonical
  `schema/okf_export.yaml`만 허용
- `--out <경로>` → 출력 번들 루트 (기본 private `okf/`, share `okf-share/`)
- `--share` → Share-ready gate + redacted manifest를 거쳐 별도 공개 번들 생성
- `--approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT` → 사람이 직접 입력하는 필수 승인 값
- 인자 없음 → 기본 export (`okf/` 생성)

## 기본 private export

기존 `uv run python scripts/okf_export.py [--dry-run]` 동작은 호환 유지한다. 이는 개인용
OKF projection이며 Share-ready 승인을 의미하지 않는다. `--strip-internal`만으로도 공개 승인이
되지는 않는다.

## 🔴 Share-ready gate (외부 공유 전 one-way door)

공유 산출물을 push하면 history가 영구다(비가역). 민감정보 누출을 막는다:

1. **`schema/okf_export.local.yaml`(gitignored) 존재 확인.** 아래 두 키를 명시한다. 민감 키워드(`sensitive_patterns`)·
   제외 페이지(`exclude_slugs`)는 **반드시 이 로컬 파일에만** 둔다. 커밋되는 `schema/okf_export.yaml`엔
   실명·내부명을 절대 넣지 않는다(그 자체가 누출).
2. 공유 후보 페이지는 `scope: shared|private`가 반드시 있어야 한다. 미지정·알 수 없는 scope,
   허용되지 않은 classification(`type`), skipped/broken page는 hard-stop이다.
3. 다음 명령의 승인 값은 자동 생성·추론하지 말고 사람이 검토 후 직접 입력한다.

```yaml
exclude_slugs: []
sensitive_patterns: []
```

```bash
uv run python scripts/okf_export.py --share \
  --approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT
```

게이트는 base policy 또는 local security config 부재, 민감 hit, scope/policy 위반, wiki 내부
symlink/외부 해석 경로면 출력 전에 중단한다. local config는 `exclude_slugs`와
`sensitive_patterns`만 추가할 수 있고 base policy·승인 값을 바꿀 수 없다.
`--out`의 canonical path가 레포 루트, `raw/**`, `wiki/**` 안이면 stage·receipt·output을
만들기 전에 거부한다.

통과 시 sibling stage에 전체 bundle과 `share-manifest.json`을 만든다. 기존 디렉토리 교체는
portable POSIX에서 단일 atomic rename이 아니므로 두 rename 사이 아주 짧게 경로가 없을 수 있다.
첫 rename 전에 durable recovery receipt를 만들며, hard exit 뒤에는 다음 정상 share 실행이 기존
bundle 복구 또는 새 bundle 완료를 수행한다. 따라서 published bundle과 recovery receipt가 동시에
없는 상태는 만들지 않는다.

manifest에는 included/excluded, source, classification, scope 집계와 configuration SHA-256만
들어간다. 페이지 경로·본문·민감 패턴·승인 값은 기록하지 않는다.

## Legacy Step 1: private dry-run 검토

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/okf_export.py --dry-run $ARGUMENTS
```

출력에서 사람이 **직접 확인**:
- `business 제외 4건`이 목록에 있는가
- `sensitive_hits=0` 인가 (본문 평문 민감정보 후보 0)
- `excluded` 카운트 = business 4 + 민감 slug 수 (기대값과 일치 — local.yaml 부재면 `pages`가 늘고
  민감 페이지가 included로 조용히 섞이니 카운트 대조 필수)

누출 후보가 보이면: 해당 페이지 slug를 `schema/okf_export.local.yaml`의 `exclude_slugs`에 추가하고
dry-run을 다시 돌려 `sensitive_hits=0`으로 수렴시킨다.

## Legacy Step 2: private export

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/okf_export.py $ARGUMENTS
```

`okf/{dir}/{slug}.md` + 디렉토리별 `index.md` + 루트 `index.md` + `log.md` 생성.
변환 규칙: `schema/okf.md` (frontmatter 매핑·정규식 계약). 제외 설정: `schema/okf_export.yaml`.

## Step 3: 결과 요약 (한국어)

- pages / links / ghost / excl_refs / excluded / sensitive_hits 통계
- round-trip 무결성(원하면 `okf/`에 design.md §11 minimal consumer 적용해 dangling 0 확인)
- private `okf/`는 Share-ready 증거가 아니다. 공개 후보는 `--share`의 `okf-share/`와
  redacted manifest만 검토한다. push는 별도 사람 승인 후 수행한다.

## 가드레일
- `raw/`·`wiki/` 읽기 전용. private 출력은 `okf/`, share 출력은 `okf-share/`에만.
- 내부 포맷을 OKF로 교체하지 않는다 — OKF는 경계(포트)에서만.
- 상세: `SPEC.md` (인터페이스와 공개 보안 게이트).
