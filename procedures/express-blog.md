---
title: express blog 절차 — wiki 기반 블로그 초안 생성
memory_type: procedural
version: "1.0"
tags:
  - express
  - blog
  - draft
  - feedback-loop
---

# express blog 절차

`wiki/` 를 근거로 블로그 초안을 생성하고, ingest 피드백 루프에 다시 흘려보낸다.

## 스텝

1. **주제 지정** — `/llm-brain:express blog "주제"` 로 호출(또는 "express blog 해줘").
2. **실행** — `scripts/express.py` 가 주제 관련 `wiki/` 페이지를
   `collect_related_pages` 로 모아 블로그 초안을 작성한다.
3. **저장** — 초안을 `express/blog/YYYY-MM-DD-{slug}.md` 로 저장한다.
4. **피드백 루프** — blog 타입은 `raw/blog/` 에도 복사해 다음 ingest 가 자기 산출물을
   소스로 다시 읽을 수 있게 한다(②→③→① 되먹임).
5. **출처 정합성 확인** — 초안이 인용한 wiki 페이지·`raw/` provenance 가 실제로 존재하는지,
   wiki 에 없는 내용을 지어내지 않았는지 확인한다.
