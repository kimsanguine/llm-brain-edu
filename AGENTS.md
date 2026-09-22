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
6. API 키, 개인 경로, 원문 개인정보를 출력, 커밋, 공유하지 않는다.

## 수업의 표준 흐름

- 메모 넣기: uv run python scripts/ingest.py --note "내용"
- 위키 만들기: uv run python scripts/compile.py
- 화면 확인: uv run python -m wiki_app
- API 기반 LIVE 컴파일은 OPENROUTER_API_KEY가 설정된 경우에만 사용한다.

Codex에 파일 작업을 요청할 때는 목표, 대상 파일 또는 폴더, 완료 기준을 함께 적는다. 예: "AGENTS.md를 읽고, raw/notes의 새 메모를 확인한 뒤 근거가 있는 내용만 wiki에 반영해. 변경 파일과 출처를 보고해."

## 선택 호환

Claude Code 플러그인과 commands/의 슬래시 명령은 기존 사용자를 위한 선택 호환 경로다. 수업 본문과 수강생 지원은 Codex 경로를 기준으로 한다. 다른 에이전트 도구도 이 파일의 가드레일과 같은 Python 실행 경로를 지킬 수 있지만, 수업의 공식 지원 범위는 Codex다.

