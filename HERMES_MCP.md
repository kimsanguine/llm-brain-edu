# Hermes에서 내 Brain 활용하기

**조회와 저장, 정리를 한 번에 연결하려면 [새 통합 연결 안내](integrations/hermes/README.md)를 사용합니다.** 아래는 기존 조회 전용 연결의 호환 안내입니다. 기존 읽기 MCP는 그대로 유지됩니다.

이미 Brain에 모아 둔 자료를 Hermes가 찾아 보고, 출처를 붙여 업무 초안을 만드는 연결입니다.
MCP는 자료를 읽는 통로이고, `llm-brain` 스킬은 검색하고 확인하는 업무 매뉴얼입니다.
Mem0와 Holographic의 대화 기억은 그대로 사용합니다. 이 연결은 검색·읽기만 제공하며 자동 저장 기능은 없습니다.

이 안내는 `scripts/connect_hermes.py`가 포함된 버전 기준입니다.
파일이 없다면 먼저 기존 수정 파일과 자료를 보존하는 업데이트 방법을 확인합니다.
기존 Brain을 새 폴더로 교체하거나 이전 런타임을 지우지 마세요.
이미 별도 런타임으로 연결한 사용자는 아래 ‘담당자용 기존 런타임 호환’을 확인합니다.

## 1. 내 Brain 폴더에서 시작하기

먼저 Hermes 설치와 Brain의 기존 메모 정리를 끝냅니다.
이 안내는 `index.md`와 `wiki/`가 있는 실제 Brain을 연결합니다. 빈 예제를 대신 등록하지 않습니다.

macOS 터미널:

```bash
cd "$HOME/llm-brain-edu"
pwd
```

Windows 일반 PowerShell:

```powershell
cd "$HOME\llm-brain-edu"
Get-Location
```

다른 위치에 설치했다면 실제 폴더로 바꿉니다. 이동에 실패하면 다음 명령을 실행하지 않습니다.
Windows 실기기 전체 실행은 미검증입니다. WSL에 설치한 사용자만 같은 WSL 환경에서 진행하며 경로를 섞지 않습니다.

## 2. 연결 부품 준비하기

설치 이유와 범위를 확인하고 승인한 뒤 실행합니다. 이 명령은 Brain의 가상환경에 MCP 부품을 설치합니다.
기존 자료를 복사하거나 메모리 공급자·모델을 바꾸지 않습니다.

```bash
uv sync --extra mcp
```

이미 OCR 선택 기능을 쓰고 있다면 `uv sync --extra mcp --extra ocr`로 두 기능을 함께 유지합니다.
extra는 OCR·MCP처럼 필요한 기능을 골라 설치하는 옵션입니다.
선택 기능을 하나만 지정하면 이전 extra가 환경에서 제외될 수 있습니다.
이 준비 명령은 Mac과 PowerShell에서 같습니다.

## 3. 먼저 점검하기

같은 Brain 폴더에서 실행합니다.

```bash
uv run --extra mcp python scripts/connect_hermes.py
```

OCR도 사용하는 분은 이 명령에서도 `--extra mcp --extra ocr`를 함께 지정합니다.
성공하면 `mcp_servers` 아래 `brain` 연결안이 표시됩니다.
출력의 `--brain-root` 다음 경로가 방금 이동한 실제 자료 폴더인지 확인합니다.
이 출력은 점검용이며 설정 파일에 직접 복사해 붙이지 않습니다.
표시만 할 뿐 Hermes 설정이나 스킬, Brain 지식 파일은 바꾸지 않습니다.
이 실행 폴더를 자료실로 사용하므로 긴 Brain 경로를 따로 입력하지 않습니다.

## 4. 승인 후 연결과 스킬 등록하기

변경 대상은 기본 프로필의 `config.yaml`과 그 옆 `skills/llm-brain/SKILL.md`입니다.
아래 명령을 실행하는 것은 해당 두 대상에 대한 등록 승인입니다.
기존 설정의 원본 백업 `config.yaml.brain-mcp.bak`을 만들고 Brain 연결만 추가합니다.
Mem0, 기본 모델, 폴백 모델, 기존 MCP는 보존합니다.

macOS:

```bash
uv run --extra mcp python scripts/connect_hermes.py --apply "$HOME/.hermes/config.yaml" --install-skill
```

Windows PowerShell:

```powershell
uv run --extra mcp python scripts/connect_hermes.py --apply "$HOME\.hermes\config.yaml" --install-skill
```

OCR 사용자는 여기에서도 두 extra를 지정합니다.
다른 프로필은 그 프로필의 실제 설정 파일로 바꿉니다. 스킬도 그 설정 파일이 있는 프로필에 설치됩니다.
별도 프로필을 쓰는 분은 담당자와 설정 파일 위치를 확인한 뒤 `--apply` 값만 바꾸고,
아래 연결 시험에서도 `default`를 같은 프로필 이름으로 바꿉니다.
동일한 연결·스킬의 재실행은 파일을 바꾸지 않습니다. 내용이 다른 기존 연결·스킬은 덮어쓰지 않고 중단합니다.
이전 별도 런타임 연결은 실행 경로가 다르므로 자동 교체하지 않습니다. 충돌 시 기존 연결을 보존하고 담당자에게 이관을 요청하세요.
실패하면 일부 단계가 완료됐을 수 있습니다. 설정과 스킬을 확인하고, 백업은 임의로 삭제하지 않습니다.

## 5. 실제 도구와 사용 확인하기

터미널에서 기본 프로필을 명시해 연결을 시험합니다.

```bash
hermes -p default mcp test brain
```

`Connected`와 `brain_search`, `brain_read` 두 도구가 보여야 합니다.
이것은 연결 시험이지 자연어 답변 성공은 아닙니다.
별도 프로필이라면 `default` 대신 등록한 프로필 이름을 씁니다.

새 Hermes 대화를 열고 다음처럼 요청합니다.

```text
/llm-brain 내 자료에서 AI 업무 자동화 내용을 찾아 출처와 함께 정리해줘.
```

주제는 본인이 넣은 자료의 주제로 바꿉니다.
답변에서 자료로 확인한 내용, AI의 업무 제안, `wiki/...md` 출처가 구분되는지 확인합니다.
원문 파일을 열어 답변과 대조합니다. 해당 정보가 없으면 관련 자료 없음이 정상 결과입니다.
스킬이 보이지 않으면 등록한 프로필인지 확인하고 새 대화를 시작합니다.

Slack에서는 같은 프로필의 에이전트가 설정을 읽어야 합니다.
기존 게이트웨이의 반영은 `/reload-mcp` 또는 운영자가 확인한 재시작 방식으로 진행합니다.
`/reload-mcp`의 완료 응답을 확인해도 최종 자연어 검색·읽기와 출처를 따로 확인해야 합니다.
공동 채널의 `/new`나 재시작은 다른 사용자의 대화에 영향을 줄 수 있어 먼저 동의를 확인합니다.
Slack의 슬래시 요청은 에이전트가 있는 대화에 보내는 메시지입니다.
현재 이 변경의 실제 Slack 자연어 전체 흐름은 미검증입니다.

## 꼭 알아둘 경계

- 스킬은 사용 절차이지 접근권한 제한 장치가 아닙니다. 읽기 전용은 MCP 코드가 보장합니다.
- 로컬 자료도 클라우드 모델이 답하면 모델 서비스로 전달될 수 있습니다. 민감한 자료로 시험하지 않습니다.
- 검색 결과와 기록된 출처를 반환하지만, 그 출처 원문까지 자동으로 대조하지는 않습니다.
- 긴 페이지는 처음 20,000자까지만 읽고 일부 읽음 표시를 반환합니다.
- 저장·수정·대화 자동 수집은 지원하지 않습니다. 지식 추가는 기존 Brain 수집·정리 절차에서 별도로 합니다.
- 연결한 Brain 폴더와 가상환경을 옮기거나 지우면 연결이 끊깁니다.

## 담당자용 기존 런타임 호환

기존 `wiki_app.hermes_setup --brain-root <실제 Brain 폴더> --server-root <런타임 폴더>` 점검은 유지합니다.
승인 후 `--apply <기존 Hermes 설정 파일>`로 연결합니다. 스킬을 함께 설치하려면 해당 checkout에
`integrations/hermes/llm-brain/SKILL.md`가 있어야 합니다. 이전 8파일 ZIP에는 스킬이 없으므로 스킬 설치 옵션을 사용하지 않습니다.
MCP 서버는 `-B -X utf8 -m wiki_app.brain_mcp`로 시작합니다. 기존 읽기·경로 제한·UTF-8 실행을 유지했습니다.

## 출처

- [Hermes MCP 공식 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [Hermes 스킬 공식 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
