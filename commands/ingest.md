---
description: raw/ 소스 ingest → wiki/ 컴파일 (URL·파일·텍스트 지원)
---

llm-brain의 ingest 커맨드입니다. 아래 절차를 순서대로 실행하세요.

## 인자 파싱

`$ARGUMENTS`를 파싱해 모드를 결정합니다:

- `https://...` 또는 `http://...` 로 시작 → URL 모드
- `--file <경로>` 포함 → 파일 모드
- `--note "<텍스트>"` 포함 → 노트 모드
- `--resonance high|medium|low` 옵션이 있으면 해당 레벨 사용
- `--priority-only` → resonance: high 미처리 파일만 처리
- 그 밖에 존재하는 파일 경로(`~/…`, `./…`, `/…`) → 파일 모드(`--file <경로>`)
- 그 밖의 텍스트 → 노트 모드(`--note "<텍스트>"`). 스크립트는 위치 인자를 받지 않는다
- 인자 없음 → 미처리 파일 목록만 확인

## Step 1: 스크립트 실행

인자에 따라 아래 중 해당하는 명령 실행:

```bash
# URL 수집
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/ingest.py --url <URL> [--resonance <level>]

# 파일 추가
uv run python scripts/ingest.py --file <경로> [--resonance <level>]

# 텍스트 노트
uv run python scripts/ingest.py --note "<텍스트>" [--resonance <level>]

# 미처리 목록 확인 (인자 없음)
uv run python scripts/ingest.py [--priority-only]
```

목록 모드: exit code 0 = 처리할 파일 없음, exit code 1 = 미처리 파일 있음. 저장 모드(`--url`·`--file`·`--note`)는 저장 성공 시 0.

## Step 2: wiki 컴파일 (교육판: compile.py)

교육판에서는 **wiki 페이지를 직접 쓰지 않습니다.** 아래 명령 하나가 raw → wiki 정리, `index.md`,
`wiki/graph.json`, 완료 표시까지 합니다. `schema/config.yaml`의 엔진으로 LIVE(키가 있거나
`engine: cli`)인지 RULE인지 정하고 화면에 찍습니다.

그래프 delta를 보려면 컴파일 **전에** 스냅샷을 먼저 뜹니다(Step 4-0).

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/compile.py
```

## Step 3: 근거 원장 갱신 (AI 답변·query 준비)

```bash
uv run python scripts/claims.py build
```

`claim ledger written`이 나오면 `/llm-brain:query`와 웹 AI 답변이 새 페이지를 근거로 쓸 수 있습니다.

## Step 4: 그래프 delta 처리

> wiki 페이지가 0개이거나 Step 2에서 변경 사항이 없으면 이 단계를 건너뜁니다.

**4-0. 스냅샷** (Step 2 compile 실행 전 반드시 먼저):

```python
import sys
sys.path.insert(0, "scripts")
from ingest import snapshot_graph
snapshot_graph()  # wiki/graph.json → wiki/.graph_prev.json 복사
```

**4-1.** graph.json 갱신은 Step 2의 compile.py가 이미 했습니다.

**4-2. delta 계산 및 출력**:

```python
import sys
sys.path.insert(0, "scripts")
from ingest import run_delta_pipeline, print_delta
delta = run_delta_pipeline()
if delta:
    print_delta(delta)
else:
    print("[ingest] delta — 변경 없음")
```

## Step 5: Canvas 생성

delta가 있으면 `wiki/canvas/ingest-delta.canvas`를 생성합니다:

```python
import sys
sys.path.insert(0, "scripts")
from ingest import generate_ingest_delta_canvas
generated = generate_ingest_delta_canvas()
if not generated:
    print("[ingest] canvas 생성 생략 (delta 없음)")
```

Obsidian에서 `wiki/canvas/ingest-delta.canvas`를 열어 신규/갱신 노드와 맥락을 확인할 수 있습니다.

## 가드레일 (절대 위반 금지)

- `raw/`는 읽기 전용 (원문 수정은 사용자가 명시적으로 요청할 때만)
- `raw/` 근거 없이 wiki 사실 수정 금지
- Claude 학습 데이터만으로 wiki 작성 금지
