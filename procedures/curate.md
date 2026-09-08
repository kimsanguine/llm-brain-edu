---
title: curate 절차 — wiki 품질 관리(감사·압축·수명)
memory_type: procedural
version: "1.0"
tags:
  - curate
  - wiki
  - distill
  - lifecycle
---

# curate 절차

`wiki/` 의 품질을 유지한다 — 감사(audit), 점진 압축(distill), 수명 관리(lifecycle).

## 스텝

1. **모드 선택** — 목적에 맞는 플래그로 `scripts/curate.py` 를 호출:
   - `/llm-brain:curate --distill` — `distill_level` 을 점진 압축(원문→요약→핵심→한줄).
   - `/llm-brain:curate --lifecycle` — TTL 초과 페이지를 archive 후보로 분류.
   - `/llm-brain:curate --all` — 전체 실행(audit + distill + lifecycle).
2. **규칙 적용** — `schema/curate.md` 의 규칙에 따라 각 페이지를 평가한다.
3. **압축 처리** — distill 모드는 자주 접근되거나 distill_level 이 낮은 페이지를
   `distill_queue.md` 에 우선 처리 대상으로 기입한다(자문 버킷 — 실제 제거 아님).
4. **수명 처리** — lifecycle 모드는 `age > ttl` 이고 inbound 링크가 0 인 페이지를
   archive 후보로 본다. 재사용되는 페이지는 보존(rescue)한다.
5. **리포트 확인** — `curate_report.md`·`distill_queue.md` 의 사유를 사람이 검토한 뒤
   실제 archive/압축 여부를 결정한다(비가역 정리는 사람이 승인).
