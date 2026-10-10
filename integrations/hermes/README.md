# Hermes에 내 Brain 연결하기

한 번의 연결 설정과 `/llm-brain` 입구 하나로 **찾기, 읽기, 메모 저장, 한 건 정리, 품질 점검**을 준비합니다. 일반 질문은 검색과 읽기, 명시적인 저장, 정리, 점검은 관리 도구로 처리합니다. 기존 Brain을 다른 예제로 바꾸지 않습니다. Hermes의 Mem0, Holographic, 모델과 폴백은 그대로 사용합니다.

**MCP는 자료실로 가는 통로, 스킬은 그 통로로 일을 처리하는 매뉴얼**입니다. 스킬만 등록한다고 자료실 연결이 생기지는 않습니다.

저장할 내용을 매번 다시 설명하지 않고 다음 업무에서 근거로 꺼내 쓰는 것이 목표입니다. **원본은 영수증, 지식 페이지는 정리한 안내서, 목차는 안내서를 찾는 지도**라고 생각하세요.

## 폴더에서 찾을 것

| 파일 | 역할 |
|---|---|
| connect.py | 조회와 관리 연결을 한 번에 점검하고 승인 후 등록 |
| llm-brain/SKILL.md | 조회와 명시적 관리를 구분하는 통합 매뉴얼, 새 설치 기본 |
| llm-brain-manage/SKILL.md | 기존 설치의 관리 명령 호환용, 새 통합 설치에는 추가하지 않음 |

MCP 실행 코드는 기존 연결과 호환되도록 `wiki_app/`에 유지합니다. 예전 `scripts/connect_hermes.py`도 그대로 쓸 수 있으며 같은 `--with-management` 옵션을 지원합니다. 관리만 추가하는 기존 `scripts/connect_brain_management.py`도 유지합니다.

## 1. 기존 설치본 업데이트

실제 Brain 폴더에서 시작합니다. 경로가 다르면 첫 줄을 본인의 설치 위치로 바꿉니다. **폴더를 삭제하거나 다시 clone하지 않습니다.**

macOS:

```bash
cd "$HOME/llm-brain-edu"
git status
```

Windows 일반 PowerShell:

```powershell
cd "$HOME\llm-brain-edu"
git status
```

ZIP으로 받은 폴더라면 `git pull`을 실행하지 말고 Codex에 기존 자료와 수정 파일을 보존하는 업데이트 방법을 요청합니다. Git 저장소라도 로컬 코드 변경이 있으면 먼저 보존 방법을 확인합니다. 정상적인 Git 설치본에서 변경을 확인하고 업데이트를 승인한 경우만 실행합니다.

```bash
git pull --ff-only
```

pull이 거절되면 `reset`이나 강제 덮어쓰기를 하지 않습니다. 기존 미추적 `raw/`, `wiki/` 자료는 업데이트를 위해 삭제할 대상이 아닙니다.

## 2. 필요한 부품 준비

아래 설치는 필요한 이유와 범위를 확인하고 승인한 뒤 실행합니다. MCP 부품을 Brain의 가상환경에 준비하며 실제 Hermes 프로필을 바꾸지 않습니다.

```bash
uv sync --extra mcp
```

OCR도 쓰고 있다면 `uv sync --extra mcp --extra ocr`로 함께 유지합니다. 아래 모든 `uv run`에서도 같은 두 extra를 사용합니다. 한 extra만 지정하면 이전 선택 기능이 환경에서 제외될 수 있습니다. Mac과 PowerShell 명령은 같습니다. Windows 전체 실행은 실기기 미검증입니다.

## 3. 변경 없이 연결 점검

같은 Brain 폴더에서 실행합니다.

```bash
uv run --extra mcp python integrations/hermes/connect.py --with-management
```

`brain`과 `brain_manage` 연결안의 `--brain-root` 뒤에 **내 실제 Brain 경로**가 나오는지 확인합니다. 표시만 하며 설정, 스킬과 지식 파일은 바꾸지 않습니다. `--with-management`는 준비할 기능을 고르는 옵션이며, 혼자서는 설정 변경 승인이 아닙니다.

조회만 필요한 분은 `--with-management`를 빼면 됩니다. 그 경로의 상세 안내는 [기존 조회 연결 안내](../../HERMES_MCP.md)를 참고합니다.

## 4. 승인한 프로필에 한 번만 등록

실제 사용하는 프로필의 설정 파일을 확인합니다. 아래는 default 예시입니다. 다른 프로필은 **그 프로필의 실제 config.yaml 경로**를 넣어야 합니다.

다음 명령은 두 MCP 연결과 통합 스킬 하나를 해당 프로필에 추가하는 승인입니다. 관리 연결에는 쓰기 권한이 있으므로 내용을 이해한 뒤 실행합니다. **Brain의 LIVE 정리 호출 허용은 포함하지 않습니다.** Hermes 자체가 클라우드 모델로 대화하면 요청과 읽은 내용은 해당 서비스로 전송될 수 있습니다.

macOS:

```bash
uv run --extra mcp python integrations/hermes/connect.py --with-management --apply "$HOME/.hermes/config.yaml"
```

Windows PowerShell:

```powershell
uv run --extra mcp python integrations/hermes/connect.py --with-management --apply "$HOME\.hermes\config.yaml"
```

Codex를 사용하는 분은 명령 대신 요청해도 됩니다.

```text
내 실제 Brain과 사용 중인 Hermes 프로필의 config.yaml을 먼저 확인해 주세요.
integrations/hermes/connect.py --with-management로 변경 없는 점검을 해 주세요.
대상 경로와 추가할 두 MCP, 통합 llm-brain 스킬을 보여 주고 내 승인을 기다려 주세요.
승인 후 --apply로 한 번에 등록하되 기존 Mem0, 모델, 폴백, 다른 MCP와 스킬은 보존하세요.
--allow-model-calls는 추가하지 마세요. 충돌하면 덮어쓰지 말고 멈추세요.
키와 개인 문서 본문은 출력하지 마세요.
```

**이미 조회 MCP가 연결된 분도 같은 등록 단계**를 사용합니다. 동일한 Brain을 가리키는 기존 읽기 전용 런타임 연결은 유지하고 부족한 관리 연결만 추가합니다. 다른 Brain을 가리키거나 관리 연결 또는 스킬 내용이 다르면 멈춥니다. 기존 사용자 지정 스킬을 자동으로 덮어쓰지 않습니다.

설정이 변경될 때 `config.yaml.brain-hermes.bak` 백업을 한 번 만듭니다. 같은 설정의 재실행은 설정과 백업을 바꾸지 않습니다. 충돌하는 백업도 덮어쓰지 않습니다. 실패 중 일부가 반영됐을 수 있으므로 설정과 통합 스킬을 각각 확인합니다. 백업에는 비밀정보가 있으니 Git이나 Slack에 올리지 않습니다.

이전 공개 조회 스킬이 이미 설치되어 있으면 기본 등록은 충돌로 중단합니다. `--migrate-public-skill`은 알려진 이전 공개 스킬(SHA-256 `fa0532027c29fb3bb00a586f25633f49fa37b9253a6b3705234ba0d099f0ac9b`)만 백업 후 통합 버전으로 바꾸는 별도 승인입니다. 사용자 수정본은 이 옵션으로도 변경하지 않습니다. 이전 `/llm-brain-manage`는 설치되어 있다면 그대로 보존됩니다.

승인한 경우에만 위 등록 명령에 `--migrate-public-skill`을 추가합니다. `--with-management`와 `--apply`가 모두 필요합니다. 스킬 백업은 해당 프로필의 `skills/llm-brain/SKILL.md.brain-public.bak`입니다. 백업 충돌은 설정 변경 전 거절합니다. 복원할 때는 현재 스킬과 백업을 먼저 비교하고, 되돌릴 범위를 확인한 뒤 이 백업을 복원합니다. 스킬 복원은 MCP 연결이나 Brain 자료를 되돌리는 작업과 별개입니다.

## 5. 도구와 스킬 확인

같은 프로필의 Hermes에서 `/reload-mcp` 또는 재시작으로 설정을 다시 읽습니다. Slack Gateway는 운영 담당자가 같은 프로필의 설정을 반영해야 합니다. 공동 채널의 재시작과 새 대화는 팀과 먼저 합의합니다.

```bash
hermes -p default mcp test brain
hermes -p default mcp test brain_manage
```

다른 프로필이면 `default`를 실제 이름으로 바꿉니다. 조회 연결에서는 `brain_search`, `brain_read`, 관리 연결에서는 `brain_save_note`, `brain_organize_note`, `brain_audit`를 확인합니다. 새 대화에서 `/llm-brain` 스킬도 확인합니다. 조회만 연결했다면 같은 스킬로 조회할 수 있지만 저장과 정리는 관리 연결 미확인으로 거절합니다.

이것은 도구 연결 점검입니다. 자연어 요청을 실제로 처리했는지는 아래 실습에서 별도로 확인합니다.

## 6. 제공 메모 저장하고 실제 원본 열기

Hermes 대화에 붙입니다. Slack에서는 에이전트가 있는 공간에서 실제 앱을 멘션해 요청합니다. 제공 내용은 가상 사례입니다.

```text
/llm-brain 아래 가상 업무 메모를 내 Brain에 저장해 주세요.
note_id는 moonlight-briefing-01로 사용하세요. 아직 정리와 Brain의 LIVE 모델 호출은 하지 마세요.

# 달빛학원 브리핑 기준
매주 월요일 브리핑에는 지난주 진행한 일과 이번 주 할 일을 구분합니다.
각 항목에는 확인할 근거와 담당자를 표시합니다.
확인하지 않은 내용은 미확인으로 남기고 외부 발송 전에 사람이 검토합니다.
```

반환된 `raw/notes/...md`를 Finder나 파일 탐색기에서 엽니다. 제목과 세 문장을 확인해야 저장을 확인한 것입니다. 같은 내용과 ID로 재시도하면 같은 원본을 재사용합니다. 다른 메모에는 새 ID를 씁니다. 원본을 임의로 편집하면 정리가 중단될 수 있습니다.

`note_id`는 메모에 붙이는 관리 번호이며 wiki slug가 아닙니다. 이름표가 있어 같은 저장 요청을 다시 보내도 두 장으로 쌓이지 않습니다. 아직 정리하지 않은 원본은 위키 검색으로 찾을 수 없으므로 지정 ID 정리는 관리 도구를 직접 호출합니다.

## 7. 한 건 정리하고 새 대화에서 재사용

```text
/llm-brain moonlight-briefing-01만 rule 방식으로 정리해 주세요.
다른 미처리 자료는 건드리지 마세요. 정리한 페이지를 다시 읽고 원본 출처를 보여 주세요.
```

`brain_organize_note`에 해당 note_id를 직접 전달했는지 확인합니다. 실제 결과의 `mode: RULE`, `pages`에 반환된 slug로 다시 읽은 `wiki/...md`와 `sources`를 확인합니다. **RULE은 검색 가능한 페이지로 원문을 옮기는 방식이며 AI 요약이 아닙니다.** 페이지와 원본의 세 문장을 대조합니다. 목차와 그래프, 처리 상태, 실행 기록도 갱신됩니다.

`/new`로 새 대화를 시작한 뒤 이전 메모를 붙이지 않고 요청합니다.

```text
/llm-brain 달빛학원 브리핑 기준을 실제 검색하고 페이지를 읽어 주세요.
그 기준으로 브리핑 빈 양식을 만들어 주세요. 출처와 새 제안을 구분해 주세요.
파일 저장과 외부 발송은 하지 마세요.
```

양식에 지난주/이번 주, 근거/담당자, 미확인/사람 검토가 들어갔는지 확인합니다. **지난 대화를 외우는 것이 아니라 저장된 지식을 다시 읽는 것**입니다. 양식은 화면 초안이며 파일이 자동 저장된 것은 아닙니다.

AI 정리가 필요한 경우는 담당자와 따로 준비합니다. `--allow-model-calls`가 허용된 관리 연결과 명시적인 `mode=live`가 모두 필요합니다. 선택 메모, 정리 규칙(`schema/ingest.md`), 분류 설정(`schema/domains.yaml`)이 Brain에 설정된 모델 서비스로 전달되고 비용이 생길 수 있으므로 먼저 동의를 받습니다. 전체 목차는 전송하지 않습니다. 기존 연결과 다른 권한 설정은 자동 교체하지 않으며 변경과 복원 범위를 확인합니다. 실패 후 RULE이면 AI 요약 성공이 아닙니다.

## 8. 품질 점검 보고서 확인

```text
/llm-brain 내 Brain의 품질을 점검해 주세요.
자료를 수정하거나 병합, 삭제하지 말고 점검 보고서 위치만 알려 주세요.
```

`wiki/curate_report.md`를 직접 엽니다. 대상 페이지가 없는 링크와 이 점검 기준에서 다른 페이지가 참조하지 않는 오래된 페이지 등을 검토합니다. 후보가 있으면 페이지, 문제, 확인할 원본, 유지 또는 수정 검토를 기록합니다. 보고서가 비었다고 모든 사실이 정확한 것은 아닙니다. 점검은 보고서와 필요한 후보 목록, 실행 기록만 만들고 기존 지식 페이지를 고치지 않습니다.

## 안전 경계와 검증 범위

- 스킬은 매뉴얼이지 권한 차단 장치가 아닙니다. 조회 MCP는 읽기 전용, 관리 MCP는 지정 메모 저장과 정리, 점검에 한정합니다. 등록 후에도 사용자 요청 없이 대화를 자동 저장하지 않습니다.
- 공개 가상 메모로 따라 합니다. 고객 정보, API 키, 개인정보는 입력하지 않습니다. 다른 프로세스에서 같은 Brain을 동시에 정리하지 않습니다.
- 출처 경로는 확인 단서입니다. 출처를 반환했다는 사실만으로 원문 정확성이 검증된 것은 아닙니다. 조회는 긴 본문 처음 20,000자까지 반환하며 일부 읽음 여부를 확인합니다.
- 로컬 파일도 Hermes가 클라우드 모델로 답변하면 외부로 전달될 수 있습니다. 연결 등록, 실제 도구 실행, 자연어 답변, Slack 응답은 각각 확인합니다.
- 2026-10-10 격리 자료실의 실제 MCP 저장, RULE 정리, 새 조회 객체의 재조회, 점검 보고서와 설정 보존을 검증했습니다. 통합 스킬은 무료 Hermes 모델로 저장, 한 건 정리와 점검을 실행했습니다. 새 대화 재사용은 시간 초과와 실패 뒤 설명을 보강한 세 번째 실행에서 실제 검색·읽기, 한국어 양식과 출처를 확인했습니다. 통신 재시도가 있었으며 반복 안정성을 보장하지 않습니다. 이전 공개 스킬의 저장 PASS와 정리 FAIL 기록도 보존합니다. 자세한 결과는 [검증 기록](VERIFICATION.md)을 확인하세요.
- Hermes 대화 모델은 호출했지만 Brain LIVE 정리는 호출하지 않았습니다. 독립 Codex CLI는 모델·MCP 시작 전 OS 권한 오류로 차단됐습니다. 실제 유료 LIVE, 운영 프로필, Slack 전체 흐름, Windows와 새 환경 설치는 미검증입니다.

## 출처

- [Hermes MCP 공식 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [Hermes 스킬 공식 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- 이 저장소 `wiki_app/brain_mcp.py`, `wiki_app/brain_management.py`, `wiki_app/hermes_bundle_setup.py`와 관련 테스트가 구현 범위의 근거입니다.
