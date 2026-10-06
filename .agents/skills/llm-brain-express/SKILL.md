---
name: llm-brain-express
description: llm-brain 위키를 근거로 블로그, 강의, 요약, 리포트 초안을 만든다. "express blog 주제", "글 초안 써 줘" 같은 요청에 쓴다.
metadata:
  short-description: 위키 기반 글 초안 생성과 publish
  plugin: llm-brain
---

# llm-brain express (Codex)

Claude Code 의 `/llm-brain:express` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/express.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/express.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/express.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:express` 은 이 스킬(`$llm-brain-express`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 본문은 초안에 담긴 근거(CONTEXT) 안의 사실만 쓴다. 없는 사실을 만들지 않고, 쓴 글은 사용자가 읽고 확인하도록 알린다.
- 본문을 쓰지 않은 빈 초안은 publish 하지 않는다. 본문을 다 쓴 뒤에는 자리표시 줄과 CONTEXT 블록을 지운다.
- publish 한 글을 위키에 넣으려면 `compile.py --rule` 과 `claims.py build` 를 이어서 실행한다.
- 외부에서 가져온 글(`raw/clippings` 등)은 요약하되 출처를 밝히고, 원문을 문장 그대로 옮겨 공개 초안으로 만들지 않는다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
