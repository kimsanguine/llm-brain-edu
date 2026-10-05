# llm-brain-edu 운영 지침

이 저장소의 수업 필수 에이전트는 Codex다. Codex는 수강생이 파일을 만들고, 명령을 실행하고, 결과를 확인하도록 돕는다. LLM API는 별도 런타임이며 schema/config.yaml의 OpenAI 호환 설정을 따른다.

## 작업 시작

1. README_수강생용.md와 관련 schema, procedure, script를 읽는다.
2. 사용자 요청이 읽기, 생성, 수정, 외부 공유 중 무엇인지 구분한다.
3. 실행 전에는 필요한 파일과 예상 산출물을 짧게 설명한다.
4. 실행 뒤에는 실제 변경 파일, 확인한 결과, 남은 위험을 보고한다.

## 절대 가드레일

1. raw/ 출처 없이 wiki/에 새로운 사실을 만들거나 기존 사실을 고치지 않는다.
2. raw/는 읽기 전용이다. 원문 수정은 사용자의 명시적 요청이 있을 때만 한다.
3. 모델의 학습 지식으로 wiki 내용을 채우지 않는다. 모든 주장은 raw/ 근거를 가진다.
4. 질문 답변은 읽기 경로다. query 중 raw/, wiki/, wiki_stats.json, Canvas를 변경하지 않는다.
5. 공개 export, 삭제, purge, 공유용 Git push는 사람이 명시적으로 승인한 뒤에만 한다.
6. API 키, 개인 경로, 원문 개인정보를 출력, 커밋, 공유하지 않는다. 사용자가 넣기로 한 메모를 임의로 고치거나 빼지 않는다 — 저장 여부는 사용자가 정하고, ingest가 경고를 보여 준다.
7. 삭제·정정 요청의 범위는 사용자 데이터(raw/, wiki/, index.md, claims.jsonl, episodes/, express/)로 한정한다. "저장소 전체"라고 해도 scripts/, tests/, examples/, schema/, 문서 같은 저장소 코드는 고치지 않는다. 거기서 같은 내용을 발견하면 위치만 보고하고 고칠지는 사용자가 정한다.
8. raw/clippings/, raw/newsletters/, raw/captures/ 는 외부에서 모은 글이라 근거로 쓰지 않는다. 웹 AI 답변이 이 글을 근거로 거절하듯, 대화 답변에서도 이 글의 내용을 요약·인용·근거로 쓰지 않는다. 사용자가 그 내용을 쓰고 싶어 하면 확인한 핵심을 uv run python scripts/ingest.py --note "..." 로 옮기도록 안내한다.
9. 패키지나 선택 기능의 설치(uv sync --extra, uv add, pip, brew 등)는 사용자가 승인하기 전에 실행하지 않는다. 필요한 설치 명령과 이유만 안내하고 사용자의 답을 기다린다.

## 수업의 표준 흐름

- 메모 넣기: uv run python scripts/ingest.py --note "내용"
- 공개 AI 논문 받기: uv run python scripts/download_paper.py
- 무료로 위키 만들기: uv run python scripts/compile.py --rule
- 화면 확인: uv run python -m wiki_app
- API 기반 LIVE 컴파일은 OPENAI_API_KEY가 설정된 경우에만 사용한다. Claude Code 사용자는 schema/config.yaml의 engine을 cli로 두면 키 없이 claude -p로 LIVE가 된다. 엔진을 바꾸거나 LIVE로 다시 정리하기 전에, 메모 내용이 해당 AI 서비스(OpenAI 또는 Anthropic)로 전송된다는 점을 사용자에게 먼저 알린다.
- wiki 페이지는 손으로 쓰지 않고 compile.py로 만든다. AI 답변 전에는 uv run python scripts/claims.py build로 근거 원장을 갱신한다.

Codex에 파일 작업을 요청할 때는 목표, 대상 파일 또는 폴더, 완료 기준을 함께 적는다. 예: "AGENTS.md를 읽고, raw/notes의 새 메모를 확인한 뒤 compile.py로 wiki에 반영해. 변경 파일과 출처를 보고해."

## 선택 호환

Claude Code 플러그인과 commands/의 슬래시 명령은 기존 사용자를 위한 선택 호환 경로다. 수업 본문과 수강생 지원은 Codex 경로를 기준으로 한다. 다른 에이전트 도구도 이 파일의 가드레일과 같은 Python 실행 경로를 지킬 수 있지만, 수업의 공식 지원 범위는 Codex다.
