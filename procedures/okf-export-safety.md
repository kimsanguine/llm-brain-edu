---
title: okf export 안전 절차, private 검토와 Share-ready 사람 승인
memory_type: procedural
version: "1.1"
tags:
  - okf
  - export
  - security
  - one-way-door
---

# okf export 안전 절차

`wiki/` 를 OKF v0.1 호환 번들 `okf/` 로 투영한다. `okf/` 는 커밋·push 되면 history 가
영구(one-way door)이므로 먼저 공유 범위와 제외 정책을 검토한다. 개인용 export와
공유용 `--share`는 별도 경로이며, `--strip-internal`은 내부 필드 제거일 뿐 공유 승인이 아니다.

## 스텝

1. **먼저 private dry-run**: 파일을 쓰기 전에
   `uv run python scripts/okf_export.py --dry-run`으로 대상, 제외와 통계를 검토한다.
   이것은 공유 승인 증거가 아니다. `--share --dry-run` 조합은 허용되지 않으며
   `--share`가 자체 preflight를 수행한다.
2. **사람이 3가지 확인** (커밋 전 one-way door 게이트):
   1. `business/` 가 제외됐는가.
   2. `sensitive_hits == 0` 인가.
   3. `excluded` 카운트가 기대값과 같은가.
3. **격리 확인** — export 목록에 `episodes`·`procedures`·`memory_health_report` 가
   등장하지 않는지 단언한다(Agent Memory OS 의 사적 운영맥락 — OKF 누출 금지).
   `episodes/**`·`procedures/**` 는 `schema/okf_export.yaml` exclude_paths 의 이중망.
4. **공유 정책 확인**: canonical `schema/okf_export.yaml`과 gitignored
   `schema/okf_export.local.yaml`이 모두 필요하다. local 파일에는
   `exclude_slugs`와 `sensitive_patterns`를 명시하며 실명이나 민감 키워드는 이 파일에만 둔다.
   빈 목록은 예시일 뿐, 실제 자료를 검토해 필요한 제외를 정한다. 공유 후보의
   `scope: shared|private`와 허용된 `type`을 확인한다. 정책 부재, scope 미지정 또는
   알 수 없는 값, 민감 hit, broken page, wiki 내부 symlink 등은 출력 전 hard-stop이다.
5. **사람 승인 후 공유 번들 생성**: 사람이 후보와 정책을 검토하고 아래 승인 값을
   직접 입력한 뒤에만 실행한다. 에이전트는 승인 값을 자동 생성하거나 추론하지 않는다.

   ```bash
   uv run python scripts/okf_export.py --share \
     --approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT
   ```

   기본 출력은 `okf-share/`와 `share-manifest.json`이다. manifest는 경로와 본문 없이
   집계와 설정 SHA-256을 기록한다. 개인용 `okf/` 또는 `--strip-internal` 결과로
   대체하지 않는다. 상세 게이트는 `commands/okf.md`를 따른다.
6. **결과 검토와 별도 공유 승인**: 산출물과 redacted manifest를 사람이 확인한다.
   export 승인은 커밋, push 또는 외부 전달 승인이 아니다. 이 작업들은 별도 명시 승인
   후에만 수행한다. 번들은 생성 시점 스냅샷이므로 wiki 갱신 뒤에는 검토와 export를 다시 한다.
