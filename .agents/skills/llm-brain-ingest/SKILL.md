---
name: llm-brain-ingest
description: llm-brain 에 메모, 파일, 웹 주소를 넣고 위키로 컴파일한다. "ingest 해줘", "이 메모 넣어 줘", "이 링크 담아 줘" 같은 요청에 쓴다.
metadata:
  short-description: 메모·파일·웹 주소를 raw 에 넣고 wiki 로 컴파일
  plugin: llm-brain
---

# llm-brain ingest (Codex)

Claude Code 의 `/llm-brain:ingest` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/ingest.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/ingest.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/ingest.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:ingest` 은 이 스킬(`$llm-brain-ingest`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 넣는 것이 웹 주소, 파일 경로, 메모 글 중 무엇인지 `scripts/ingest.py` 가 알아서 판별한다. 파일 경로처럼 생겼는데 없는 경우는 오류로 알리고 메모로 저장하지 않는다.
- 컴파일은 `--rule` 이 기본이다. AI 서비스로 내용이 전송되는 LIVE 컴파일은 사용자가 승인하기 전에는 하지 않는다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
