---
title: ingest 절차 — raw 소스를 wiki 로 컴파일
memory_type: procedural
version: "1.0"
tags:
  - ingest
  - wiki
  - compile
  - raw
---

# ingest 절차

`raw/` 소스(URL·파일·텍스트)를 읽어 `wiki/`를 생성·갱신한다. Claude 가 컴파일러 역할.

## 스텝

1. **가드레일 확인** — `raw/` 출처 없이 `wiki/` 를 신규 생성하거나 사실을 수정하지 않는다.
   학습 데이터만으로 `wiki/` 작성 금지. `raw/` 파일은 읽기 전용(수정 금지).
2. **소스 지정** — 다음 중 하나로 호출:
   - `/llm-brain:ingest https://url --resonance high|medium|low`
   - `/llm-brain:ingest ~/path/to/file.pdf --resonance high`
   - `/llm-brain:ingest '텍스트 내용' --resonance medium`
   - 또는 자연어로 "ingest 해줘".
3. **실행** — `scripts/ingest.py` 가 소스를 파싱하고 상태(staging)를 관리한다.
4. **컴파일 규칙 적용** — `schema/ingest.md` 의 규칙으로 `wiki/` 페이지를 생성·갱신한다.
   페이지 frontmatter 에 `sources: [raw/파일경로]` 와 `--resonance` 가 부여한 중요도를 남긴다.
5. **인덱스 갱신** — `index.md` 를 업데이트해 새/변경 페이지를 등재한다.
6. **검증** — 생성된 페이지가 `raw/` 출처를 인용하는지, `index.md` 에 반영됐는지 확인한다.
