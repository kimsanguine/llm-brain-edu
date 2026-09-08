# 내 브레인 개통하기

> 이 문서 하나만 따라 하면 됩니다. **20분** 걸립니다.
> 막히면 30분 넘게 붙잡지 마세요. 슬랙 `#10기-질문` 에 올리시면 됩니다.
> **개강 첫날 수업 후 30분 설치 클리닉**이 있으니 못 끝내도 진도에 지장 없습니다.

## 이게 뭔가요

메모와 문서를 넣어 두면, AI가 정리해서 **검색 가능한 위키**로 만들어 주는 개인 지식 저장소입니다. 우리는 이걸 "브레인"이라고 부릅니다.

앞으로 8주 동안 매주 배우는 기술이 이 브레인의 새 장기가 됩니다. 오늘은 빈 상자를 받아 전원을 켜는 것까지입니다.

**브레인은 여러분 컴퓨터 안에만 있습니다.** 어디로도 올라가지 않고, 강사도 열어 보지 않습니다.

---

## 빠른 시작

### 1단계. 내려받기 (5분)

> 📸 화면 캡처 자리

터미널(맥은 "터미널", 윈도우는 "명령 프롬프트")을 열고 아래를 붙여넣습니다.

```bash
git clone https://github.com/kimsanguine/llm-brain-edu.git
cd llm-brain-edu
```

`git` 이 없다면 [저장소 페이지](https://github.com/kimsanguine/llm-brain-edu)에서 **Code → Download ZIP** 으로 받아 압축을 풀고, 그 폴더로 들어가면 됩니다.

### 2단계. 준비물 설치 (5분)

`uv` 라는 도구 하나만 설치하면 파이썬까지 알아서 챙겨 줍니다.

```bash
# 맥·리눅스
curl -LsSf https://astral.sh/uv/install.sh | sh

# 윈도우 (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

설치 후 **터미널을 새로 엽니다**(그래야 인식됩니다). 그리고 프로젝트 폴더에서:

```bash
uv sync
```

<details>
<summary>파이썬이 이미 있고 uv 를 쓰고 싶지 않다면</summary>

```bash
pip install -r requirements.txt
```

이 경우 아래 명령에서 `uv run python` 대신 `python` 을 쓰면 됩니다.
</details>

### 3단계. 설치 점검 → 초록불 (2분)

```bash
uv run python scripts/doctor.py --fix
uv run python scripts/doctor.py
```

두 번째 명령의 마지막 줄이 이렇게 나오면 성공입니다.

```
  ⚠️ openrouter-key: OPENROUTER_API_KEY 없음 — 없어도 설치는 완료입니다(RULE 경로로 동작)

요약: ✅ 40 · ⚠️ 1 · ❌ 0
✅ 설치 정상. (⚠️ 항목은 선택/환경별 — 필요 시 안내대로)
```

**⚠️ 1개는 정상입니다.** 아직 키를 안 넣었다는 뜻일 뿐이고, 키가 없어도 끝까지 진행됩니다.
❌ 가 0이면 성공입니다.

### 4단계. 메모 3건 넣고 위키 만들기 (5분)

여러분 이야기로 넣어 보세요. 아래 셋이 예시입니다.

```bash
uv run python scripts/ingest.py --note "오늘 배운 것: (한 줄)"
uv run python scripts/ingest.py --note "이번 주 할 일: (한 줄)"
uv run python scripts/ingest.py --note "관심 있는 것: (한 줄)"
```

이제 메모를 위키로 바꿉니다.

```bash
uv run python scripts/compile.py
```

이렇게 나옵니다.

```
[compile] 메모 3건 → 위키 컴파일
  경로: RULE (OPENROUTER_API_KEY 없음 — 원문을 그대로 옮깁니다)
   ✓ wiki/concepts/2026-09-07-1358-note-2.md  [RULE]
   ✓ wiki/concepts/2026-09-07-1358-note-3.md  [RULE]
   ✓ wiki/concepts/2026-09-07-1358-note.md  [RULE]
  index.md 갱신 · 총 3개 페이지
[ingest] 3개 파일 처리 완료로 표시.
[compile] 완료 — 3개 페이지를 만들었습니다.
```

### 5단계. 눈으로 확인하고 캡처 (3분)

```bash
uv run python -m wiki_app
```

브라우저에서 **http://localhost:8000** 을 엽니다. 방금 넣은 메모 3개가 페이지로 보이면 완료입니다.

> 📸 **이 화면을 캡처해서 제출 폼에 올리세요.**

검색창에 아까 쓴 단어를 넣어 보세요. 찾아집니다. 끄려면 터미널에서 `Ctrl + C` 입니다.

---

## 안 될 때

여기서 막히는 건 **아주 흔한 일**이고 여러분 잘못이 아닙니다.

1. 오류 메시지 **전체**를 복사해 슬랙 `#10기-질문` 에 올립니다(스크린샷보다 텍스트가 낫습니다)
2. 어디까지 됐는지 한 줄 적습니다. "3단계 초록불까지 성공, 4단계에서 멈춤"
3. 설치 클리닉에서 함께 해결합니다

### 화면부터 보고 싶다면 (리커버리)

설치가 끝까지 안 되어도, 예제 위키를 넣어 화면이 어떻게 생겼는지 먼저 볼 수 있습니다.

```bash
uv run python scripts/compile.py --seed
uv run python -m wiki_app
```

여러분이 이미 만든 페이지가 있으면 덮어쓰지 않습니다. 나중에 `--seed` 없이 다시 실행하면 내 메모로 만든 위키로 돌아옵니다.

---

## 키를 넣으면 뭐가 달라지나요 (선택)

지금은 `RULE` 경로로 돌고 있습니다. 메모 원문이 그대로 페이지가 됩니다. 위키는 잘 만들어지고 검색도 됩니다.

키를 넣으면 `LIVE` 경로가 되어, **AI가 요약하고 분류하고 관련 페이지끼리 연결**해 줍니다.

```bash
# 맥·리눅스
echo 'export OPENROUTER_API_KEY="발급받은키"' >> ~/.zshrc

# 윈도우
setx OPENROUTER_API_KEY "발급받은키"
```

**새 터미널을 열어야** 적용됩니다. 확인은 맥 `echo $OPENROUTER_API_KEY`, 윈도우 `echo %OPENROUTER_API_KEY%` 입니다.

같은 메모를 두 경로로 만들어 비교해 보면 차이가 한눈에 보입니다.

> ⚠️ 키는 **비밀번호와 같습니다.** 슬랙·깃허브·과제 파일에 절대 붙여넣지 마세요.

---

## 넣지 않을 것 (반입 금칙)

브레인은 내 컴퓨터 안에만 있습니다. 그래도 규칙이 필요합니다. **자산은 쌓기 전에 규칙을 정해야 합니다.** 한번 들어간 것은 되돌리기 어렵습니다.

**넣지 않습니다**

- 회사 기밀 문서 (계약서, 미공개 실적, 내부 전략 자료)
- 고객·동료의 개인정보 (주민번호·연락처·계좌·주소가 든 파일)
- 회사 규정상 외부 반출이 금지된 자료

**판단이 서지 않으면 넣지 않습니다.** 애매한 것을 넣고 후회하는 것보다, 안 넣고 아쉬운 편이 낫습니다.

**넣어도 좋은 것**: 내가 쓴 메모·회의 요약(민감정보 제거), 공개된 자료·기사, 학습 기록, 개인 아이디어

---

## 앞으로 8주

| 주차 | 브레인이 갖게 되는 것 |
|---|---|
| 10 | 눈 — 사진과 PDF를 읽습니다 |
| 11 | 의미 기억 — 흐릿하게 기억나는 것도 찾아집니다. 아침마다 스스로 자료를 먹습니다 |
| 12 | 입 — 출처를 달고 답합니다 |
| 13 | 손 — 다른 AI가 내 브레인에게 물어봅니다 |
| 14 | 신경계 — 흐름이 지도로 보입니다 |

매주 만든 부품은 `extensions/` 폴더에 넣습니다. 자세한 규칙은 `extensions/README.md` 에 있습니다.

**본체(`scripts/`, `wiki_app/`)는 건드리지 않습니다.** 왜 그런지도 `extensions/README.md` 에 적어 두었습니다.

---

## 명령어 요약

| 하고 싶은 것 | 명령 |
|---|---|
| 설치 점검 | `uv run python scripts/doctor.py` |
| 메모 넣기 | `uv run python scripts/ingest.py --note "내용"` |
| 파일 넣기 | `uv run python scripts/ingest.py --file ~/문서/파일.pdf` |
| 위키 만들기 | `uv run python scripts/compile.py` |
| 화면 보기 | `uv run python -m wiki_app` → http://localhost:8000 |
| 예제로 화면 먼저 보기 | `uv run python scripts/compile.py --seed` |
