---
name: llm-brain-wikiweb
description: llm-brain 웹 화면(검색, 페이지 보기, 지식 지도)을 띄운다. "웹 화면 띄워 줘" 같은 요청에 쓴다.
metadata:
  short-description: wiki_app 웹 화면 실행
  plugin: llm-brain
---

# llm-brain wikiweb (Codex)

Claude Code 의 `/llm-brain:wikiweb` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/wikiweb.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/wikiweb.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/wikiweb.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:wikiweb` 은 이 스킬(`$llm-brain-wikiweb`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 서버는 `uv run python -m wiki_app` 으로 띄우고 터미널에 찍힌 주소를 알려 준다. 끝낼 때는 Ctrl + C 로 종료한다.
- 웹 화면의 AI 답변 버튼은 `schema/config.yaml` 의 엔진 설정이 필요하다. 이 과정에서는 필수가 아니다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
