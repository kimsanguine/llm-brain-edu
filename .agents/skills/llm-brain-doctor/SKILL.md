---
name: llm-brain-doctor
description: llm-brain 설치 상태를 점검한다. "doctor 해줘", "설치 점검해 줘" 같은 요청에 쓴다.
metadata:
  short-description: 설치 진단
  plugin: llm-brain
---

# llm-brain doctor (Codex)

Claude Code 의 `/llm-brain:doctor` 과 같은 일을 하는 Codex 용 스킬이다. 브레인 폴더(`llm-brain-edu`) 안에서 실행한다.

1. `AGENTS.md` 와 `commands/doctor.md` 를 읽고 그 절차를 그대로 따른다. 절차의 정본은 `commands/doctor.md` 하나이고, 이 스킬은 Codex 에서 그 절차를 부르는 입구다.
2. `commands/doctor.md` 의 `$ARGUMENTS` 는 사용자가 이 스킬과 함께 준 입력이다. 문서에 나오는 `/llm-brain:doctor` 은 이 스킬(`$llm-brain-doctor`)로 읽는다.
3. 슬래시 명령에만 있는 Claude Code 전용 도구 이름이 나오면 Codex 의 파일과 터미널 도구로 같은 일을 한다.

이 스킬에서 특히 지킬 것
- 기본은 점검만 한다(`doctor.py`). 폴더와 설정을 만드는 `--fix` 는 사용자가 원할 때만 실행한다.
- 패키지 설치가 필요해 보여도 사용자의 승인 전에는 설치하지 않는다.

끝나면 AGENTS.md 의 보고 형식대로 실제 바뀐 파일, 확인한 결과, 남은 위험을 알린다.
