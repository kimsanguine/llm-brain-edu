---
name: llm-brain-okf
description: llm-brain 위키를 OKF 번들로 내보낸다(공유용 export). "okf 해줘" 같은 요청에 쓴다.
metadata:
  short-description: wiki 를 OKF 번들로 export (보안 게이트 포함)
  plugin: llm-brain
---

# llm-brain okf (Codex)

Claude Code 의 `/llm-brain:okf` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/okf.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/okf.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/okf.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:okf` 은 이 스킬(`$llm-brain-okf`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 공개 export 는 되돌릴 수 없는 일이다. 먼저 `--dry-run` 으로 대상, 제외, 민감 검사 결과를 보여 주고 사용자가 승인한 뒤에만 실제로 내보낸다.
- export 한 결과를 커밋하거나 push 하지 않는다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
