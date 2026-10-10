# Examples, 수업 seed와 입력 자료

세 가지 예제를 제공한다:

| 폴더 | 무엇 | 언제 |
|---|---|---|
| **`course-seed-wiki/`** | raw 출처가 함께 있는 수업용 위키 5페이지 | `compile.py --seed`로 검색과 페이지 보기를 먼저 체험할 때 |
| **`seed-wiki/`** | 기존 제품 소개용 위키 5페이지 | 이전 결과물 구조를 읽어 볼 때 |
| **`seed-raw/`** | 가상 실무자 raw 노트 17개 (README 제외) | `raw → wiki` 컴파일 과정을 직접 체험할 때 |

> 입력부터 체험하려면 `seed-raw/README.md`의 기존 파일을 덮어쓰지 않는 복사 절차를 따른다. 복사 뒤 `uv run python scripts/compile.py --rule`로 정리 모델 호출 없이 위키를 만들 수 있다.

## seed-wiki 레이아웃

기존 `seed-wiki/`는 결과물 구조를 보여 주는 예제다. 현재 수업의 설치 경로는 아래 `--seed`이며, 이 폴더를 사용자 위키에 수동으로 복사하지 않는다.

- `examples/seed-wiki/index.md`: 기존 5페이지 데모 목차
- `examples/seed-wiki/wiki/`: 기존 페이지와 `graph.json`

> app은 루트 `index.md`와 `wiki/`를 읽는다. `examples/` 안의 파일을 직접 읽는 것이 아니므로 화면 체험에는 아래 수업 seed 설치 명령을 사용한다. 기존 제품 예제의 외부 URL 출처를 현재 raw 기반 근거 원장과 호환된다고 간주하지 않는다.

## 사용법

### Option A, 수업용 데모 보기 (권장)

저장소 루트에서 실행한다. `index.md`는 사용자 위키에서 생성되는 파일이며 fresh clone에 작성자 개인 인덱스가 포함되어 있지 않다.

```bash
uv run python scripts/compile.py --seed
uv run python -m wiki_app
# 터미널에 출력된 실제 주소로 접속 (보통 http://localhost:8000)
```

`--seed`는 `course-seed-wiki/`의 위키, 목차와 공개 raw 원문 5편을 설치하고 처리 상태를 기록한다. 기존 위키 페이지가 있거나 같은 이름의 다른 raw 원문이 있으면 중단한다. `--force`로 자기 자료를 덮어쓰지 않는다. 기존 위키가 있으면 바로 화면을 열거나 README의 논문 실습을 진행한다.

검색창에 `인터뷰`를 넣어 수업용 페이지를 확인한다. 8000번이 사용 중이면 다음 빈 포트를 사용하므로 터미널에 표시된 주소를 연다. 데모 종료는 `Ctrl+C`이며 위키를 삭제하는 정리 단계는 없다. 이후 자신의 메모를 ingest하고 `compile.py --rule`로 위키에 추가한다.

### Option B — 자기 wiki만 사용 (seed 건너뛰기)

`examples/`를 무시하고 README의 빠른 시작 가이드만 따르세요.

## seed-wiki 구성

- `wiki/concepts/llm-wiki-pattern.md` — Karpathy 패턴
- `wiki/concepts/second-brain-code.md` — Tiago Forte CODE 프레임워크
- `wiki/concepts/distill-progressive.md` — Progressive Summarization
- `wiki/tools/claude-code.md` — Claude Code CLI
- `wiki/tools/obsidian.md` — Obsidian
- `wiki/graph.json` — 페이지와 태그를 연결하는 그래프
- `index.md` — 기존 5페이지 데모 인덱스

기존 예제의 그래프와 페이지 연결을 읽어 볼 수 있다. `compile.py --seed`로 설치되는 수업 예제의 내용과는 다르다.

## 테스트 데이터 경계

`tests/conftest.py`는 작성자 전용 자료를 요구하는 `requires_user_wiki` 테스트만 실제 자료가 없을 때 skip한다. seed 설치를 작성자 데이터 검증으로 취급하지 않는다. 격리 fixture를 쓰는 테스트는 사용자 위키와 별도로 실행된다.
