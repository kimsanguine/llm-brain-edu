# llm-brain 실습 데모 — raw 입력 자료

옵시디언/세컨드 브레인을 처음 시작하는 수강생을 위한 **연습용 raw 입력 자료**입니다.
아직 자기 메모가 쌓이지 않았어도, 이 자료로 "흩어진 메모 → 구조화된 위키" 컴파일
과정을 그대로 체험할 수 있습니다.

## 무엇이 들어 있나

서로 다른 직무의 사람들이 쌓은 메모 **17개**입니다. (실명·실제 정보 없음)

```
til/         # 매일 배운 것 6개 (인터뷰·JTBD·OKR·리텐션·PRD·우선순위)
clippings/   # 웹 아티클 클리핑 2개 (Opportunity Solution Tree·A/B 테스트)
meetings/    # 회의록 2개 (제품 동기화·디스커버리 리뷰)
notes/       # 메모 7개 (도구 스택 + 마케팅 2 · 행정 2 · 이커머스 2)
```

`notes/` 의 여섯 개는 **여러분 같은 실무자의 메모**입니다. 직무마다 두 편씩 있습니다.

| 직무 | 파일 | 무엇이 반복되나 |
|---|---|---|
| **마케팅** | `2026-01-24-campaign-weekly.md` | 매주 같은 성과표를 다시 만든다 |
| | `2026-01-27-content-plan.md` | 매달 주제를 고르는데 지난달 근거가 없다 |
| **총무·행정** | `2026-01-25-research-fund-rules.md` | 같은 규정 질문에 매번 근거를 다시 찾는다 |
| | `2026-01-28-deadline-tracker.md` | 분기마다 같은 마감 달력을 새로 만든다 |
| **이커머스** | `2026-01-26-cs-repeat-questions.md` | 지난 CS 답변을 못 찾아 매번 새로 쓴다 |
| | `2026-01-29-sourcing-criteria.md` | 예전에 뺐던 상품을 또 검토한다 |

여섯 편 모두 **`반복업무` 라는 같은 태그**로 묶여 있습니다. 직무는 다른데 고민이 같습니다.
"지난번에 뭐라고 했더라"를 못 찾는 것. 브레인이 없애려는 게 바로 그 시간입니다.

컴파일한 뒤 화면(`uv run python -m wiki_app`)의 **지도**를 보면, 직무마다 작은
덩어리가 하나씩 생긴 게 보입니다. 8주 뒤 여러분 덩어리에는 **여러분 메모**가
들어가 있어야 합니다.

> 자기 직무에 가까운 두 편을 먼저 읽어 보세요. 남의 메모라도 "아, 나도 이거 매주 하는데"가
> 나오면 그게 여러분이 브레인에 넣을 첫 자료입니다.

## 실습 순서

학생용 설치 안내인 저장소 루트의 `README_수강생용.md`를 따라 `uv sync`와
`uv run python scripts/doctor.py --fix`를 마친 뒤 진행합니다. Claude Code는 필요하지 않습니다.
아래 명령은 모두 **저장소 루트**(`llm-brain-edu`)에서 실행합니다.

### 1. 시드 17편을 raw에 넣기

맥과 리눅스:

```bash
cp -Rn examples/seed-raw/til examples/seed-raw/clippings examples/seed-raw/meetings examples/seed-raw/notes raw/
```

윈도우 PowerShell:

```powershell
foreach ($dir in "til", "clippings", "meetings", "notes") {
    New-Item -ItemType Directory -Force "raw/$dir" | Out-Null
    Get-ChildItem "examples/seed-raw/$dir" -File | ForEach-Object {
        $target = Join-Path "raw/$dir" $_.Name
        if (-not (Test-Path $target)) { Copy-Item $_.FullName $target }
    }
}
```

같은 이름의 기존 파일은 덮어쓰지 않습니다. `examples/seed-raw/README.md` 자체는
실습 자료가 아니므로 복사하지 않습니다.

### 2. 위키 만들기

```bash
uv run python scripts/compile.py
```

키가 없으면 RULE 경로로 실행됩니다. 원문과 태그를 보존한 페이지를 만들며,
AI 요약이나 도메인 분류는 하지 않습니다. 키가 있으면 LIVE 경로로 자료가 외부 AI에
전송됩니다. 키를 넣어 다시 정리하려면 학생용 안내의 `--recompile` 절차를 따르세요.

### 3. 검색과 지도 확인하기

```bash
uv run python -m wiki_app
```

터미널에 출력된 주소를 브라우저로 엽니다. 기본 포트가 사용 중이면 다음 빈 포트를 씁니다.
검색창에 `마케팅`, `연구비`, `CS`를 입력하고 각 직무의 두 메모를 확인하세요.
지도에는 문서의 직접 링크와 같은 태그를 공유하는 페이지 연결이 함께 표시됩니다.

## 기대 결과

빈 브레인에 시드만 넣어 RULE로 실행했을 때:

- 위키 페이지 **17개**, 카테고리는 모두 `concepts/`
- 원본 그래프 **50개 링크**: 문서 간 wikilink 1개와 문서→태그 링크 49개
- 대시보드의 미처리 RAW **0개**
- 지도에서는 태그를 페이지 간 연결로 바꿔 보여주므로 선 개수는 원본의 50개와 다릅니다.
  하나의 태그를 7개 이상이 공유하면 그 태그는 지도 연결에서 제외합니다.

개인 메모가 이미 있으면 수치는 더 커질 수 있습니다. RULE에서는 원문을 옮기므로
`tools/`나 `insights/`로 자동 분류된다는 뜻이 아닙니다. 실제 개인정보가 없는
내 메모를 추가하면서, 시드와 내 기록의 검색 결과를 비교하세요.
