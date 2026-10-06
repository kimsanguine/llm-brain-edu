---
name: llm-brain-curate
description: llm-brain 위키의 품질을 점검한다(audit, distill, lifecycle, reweave). "curate 해줘", "위키 점검해 줘" 같은 요청에 쓴다.
metadata:
  short-description: 위키 품질 점검(audit 등)
  plugin: llm-brain
---

# llm-brain curate (Codex)

Claude Code 의 `/llm-brain:curate` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/curate.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/curate.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/curate.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:curate` 은 이 스킬(`$llm-brain-curate`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 사용자가 모드를 말하지 않으면 `--audit` 만 실행한다. `--distill` 은 위키 페이지를 압축해 고치므로 사용자가 직접 요청할 때만 실행한다.
- audit 은 보고서(`wiki/curate_report.md`)와 `log.md` 기록을 만든다. wiki 페이지와 raw 는 고치지 않는다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
