# llm-brain 실습 데모 — raw 입력 자료

옵시디언/세컨드 브레인을 처음 시작하는 수강생을 위한 **연습용 raw 입력 자료**입니다.
아직 자기 메모가 쌓이지 않았어도, 이 자료로 "흩어진 메모 → 구조화된 위키" 컴파일
과정을 그대로 체험할 수 있습니다.

## 무엇이 들어 있나

가상의 **PM/기획자 한 명**이 3주간 쌓은 메모 11개입니다. (실명·실제 정보 없음)

```
til/         # 매일 배운 것 6개 (인터뷰·JTBD·OKR·리텐션·PRD·우선순위)
clippings/   # 웹 아티클 클리핑 2개 (Opportunity Solution Tree·A/B 테스트)
meetings/    # 회의록 2개 (제품 동기화·디스커버리 리뷰)
notes/       # 메모 1개 (도구 스택)
```

핵심 개념(**디스커버리·인터뷰·JTBD·리텐션·PRD·우선순위·메트릭**)이 여러 파일에
일부러 반복 등장하도록 설계돼 있어, 컴파일하면 **개념 페이지 + wikilink 그래프**가
자연스럽게 만들어집니다.

## 실습 순서

1. **llm-brain 레포 클론** (설치는 README의 [설치] 참고).

2. 이 폴더의 내용을 레포의 `raw/`로 복사:
   ```bash
   cp -r til clippings meetings notes  ~/<llm-brain 레포>/raw/
   ```

3. Claude Code 세션에서 **컴파일**:
   ```
   /llm-brain:ingest
   ```
   → `wiki/`에 개념·도구·인사이트 페이지가 생기고 `[[wikilink]]`로 연결됩니다.

4. **질의**해 보기:
   ```
   /llm-brain:query "리텐션이 뭐였지?"
   /llm-brain:query "디스커버리 관련 메모 정리해줘"
   ```

5. **그래프·검색 시각화** (로컬 웹):
   ```bash
   uv run python -m wiki_app    # → http://localhost:8000
   ```

6. **표준 번들로 export** (OKF):
   ```
   /llm-brain:okf
   ```

## 기대 결과 (체감 포인트)

11개의 흩어진 메모가 →
- `concepts/` 디스커버리·JTBD·리텐션·PRD·우선순위·메트릭 …
- `tools/` Notion·Figma·Linear·Amplitude
- `insights/` 반복 패턴(예: "인터뷰는 솔루션이 아니라 문제를 묻는다")
- 으로 **연결된 지식 그래프**가 됩니다. 이게 세컨드 브레인의 *aha* 지점입니다.

> 자기 자료가 생기면 같은 방식으로 `raw/`에 넣고 `/llm-brain:ingest`만 하면 됩니다.
