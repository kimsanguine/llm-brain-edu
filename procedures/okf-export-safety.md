---
title: okf export 안전 절차 — 커밋 전 dry-run 보안 게이트
memory_type: procedural
version: "1.0"
tags:
  - okf
  - export
  - security
  - one-way-door
---

# okf export 안전 절차

`wiki/` 를 OKF v0.1 호환 번들 `okf/` 로 투영한다. `okf/` 는 커밋·push 되면 history 가
영구(one-way door)이므로 **반드시 dry-run 보안 게이트를 먼저 통과**한다.

## 스텝

1. **먼저 dry-run** — 파일을 쓰기 전에 `/llm-brain:okf --dry-run` 으로 export 대상·제외·
   통계만 출력한다(`scripts/okf_export.py`).
2. **사람이 3가지 확인** (커밋 전 one-way door 게이트):
   1. `business/` 가 제외됐는가.
   2. `sensitive_hits == 0` 인가.
   3. `excluded` 카운트가 기대값과 같은가.
3. **격리 확인** — export 목록에 `episodes`·`procedures`·`memory_health_report` 가
   등장하지 않는지 단언한다(Agent Memory OS 의 사적 운영맥락 — OKF 누출 금지).
   `episodes/**`·`procedures/**` 는 `schema/okf_export.yaml` exclude_paths 의 이중망.
4. **local 설정 경고 확인** — fresh clone/CI 엔 `schema/okf_export.local.yaml` 이 없어
   민감 키워드 게이트가 비활성(stderr 🔴 경고)이다 — 그 상태로는 커밋하지 않는다.
5. **번들 생성** — 게이트 통과 후 `okf/` 를 생성한다. 외부 공유본은
   `/llm-brain:okf --strip-internal` 로 `x-llmbrain-*` 내부 필드를 전부 제거한다.
6. **stale 주의** — `okf/` 는 export 시점 스냅샷이다. `wiki/` 갱신 후 재export 하지 않으면 stale.
