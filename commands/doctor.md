---
description: llm-brain 설치 진단·수정 또는 읽기 전용 guided 운영 프로필 안내
---

llm-brain의 doctor 커맨드입니다. 설치를 진단·복구하거나, `--guided`로 쓰기 전
운영 프로필을 선택합니다.
`$ARGUMENTS`에 따라 아래를 실행하세요.

## 인자

- 인자 없음 → **진단만** (llm-brain 제품/개인 데이터 변경 없음)
- `--fix` → 안전 복구: 누락 디렉토리 생성 + `schema/sources.yaml`이 없으면 `sources.example.yaml`에서 복사. **기존 파일은 절대 덮어쓰지 않음.**
- `--guided` → **읽기 전용** 프로필 3개(`Demo`, `Personal-private`, `Share-ready`)만 표시
- `--guided --profile demo|personal-private|share-ready` → 선택한 프로필의 명시적 다음 행동 1개만 표시

`--guided`는 `--fix`와 함께 쓸 수 없고, 진단·디렉터리 생성·config 복사·개인
콘텐츠 스캔을 실행하지 않습니다.
`doctor.py` 자체는 제품/개인 데이터를 변경하지 않지만, 실행기인 `uv run`은 Python
환경이나 패키지 캐시를 생성·갱신할 수 있습니다.

### Guided 프로필

- **Demo** — 기존 `examples/seed-wiki/wiki`를 읽는 일회성 설치 검증 안내(브라우저 UI 체험은 `wikiweb`의 데모 절차 사용)
- **Personal-private** — `schema/sources.yaml`이 있으면 사용자 설정을 preview하고, fresh clone처럼 없으면 존재하는 `schema/sources.example.yaml` 템플릿 preview 안내
- **Share-ready** — canonical `schema/okf_export.yaml`, local
  `schema/okf_export.local.yaml`, 모든 후보의 명시적 `scope: shared|private` 확인 후
  정확한 `scripts/okf_export.py --share --approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT`
  다음 행동 하나를 안내

## 실행

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/doctor.py $ARGUMENTS
```

(uv 미설치 시: `.venv/bin/python scripts/doctor.py $ARGUMENTS`)

## 점검 항목

- **필수 디렉토리**: `raw/`(7 하위 채널)·`wiki/`·`schema/`·`scripts/`·`commands/`·`procedures/`·`examples/`
- **스크립트(메모리 OS 포함)**: ingest·curate·express·okf_export·export_graph·sync_raw + **episode·brain_context·memory_health·procedures·lib/frontmatter_utils**
- **커맨드**: ingest·curate·express·query·okf·doctor·wikiweb
- **설정**: `schema/config.yaml`(LLM 엔진)·`schema/sources.yaml`(소스 — gitignored, 없으면 WARN)
- **의존성**: pyyaml·fastapi·uvicorn·httpx·python-frontmatter (`uv sync`로 설치)
- **claude CLI**: cli 엔진(기본) 사용 시 필요 (없으면 WARN)

## 결과 해석

- ❌ **FAIL** = 설치 문제 → 해결 필요(디렉토리는 `doctor --fix`, 의존성은 `uv sync`, 스크립트/커맨드 누락은 플러그인 재설치·`git pull`).
- ⚠️ **WARN** = 선택/환경별(설정 파일·claude CLI 등) — 필요 시 안내대로.
- exit 0 = FAIL 없음(설치 정상) · exit 1 = FAIL 있음.

> 먼저 `doctor --guided`로 운영 프로필을 고를 수 있습니다. 실제 초기화가 필요할
> 때만 별도로 `doctor --fix`를 실행하세요. 의존성은 그 전에 `uv sync`.
