# Claim Ledger Contract

query/AI answer 경로에서 사용하는 작은 file-first claim 원장 계약.

기본 저장 위치는 repository root의 `claims.jsonl`이며 UTF-8 JSON object 한 줄이
claim 하나다. `locator`만 optional이고 나머지는 모두 required다. unknown field,
blank line, duplicate ID, malformed/partial record 하나라도 있으면 원장 전체를 거부한다.

## ClaimRecord

- `claim_id`: `claim:{slug}-{n}` 형식의 결정적 식별자
- `statement`: wiki 본문에서 분리된 비어 있지 않은 claim 문장
- `kind`: `fact | inference | opinion`
- `raw_path`: traversal 없는 repository-relative `raw/**` 경로
- `raw_sha256`: 원장 생성 시점 raw 파일 전체 bytes의 정확한 lowercase SHA-256(64 hex)
- `locator` (optional): 해당 `raw_path` 또는 `raw_path#Lx-Ly`
- `valid_from`, `valid_until`: 유효한 `YYYY-MM-DD`, `valid_from <= valid_until`
- `status`: `active | stale | superseded`
- `trust`: `trusted | untrusted`

writer는 모든 record를 먼저 검증한 뒤 같은 디렉터리의 임시 파일을 `os.replace`해
원자적으로 교체한다. `raw/**` 아래를 ledger target으로 지정할 수 없다.
자동 build는 statement별 source 귀속을 추측하지 않는다. wiki 페이지의 `sources`가
정확히 하나의 `raw/**` 경로가 아니면 페이지 전체를 fail closed하고 원장을 쓰지 않는다.

## Query rules

1. query는 persisted ledger를 읽기만 하며 `raw/**`, `wiki/**`, stats, Canvas를 쓰지 않는다.
   로드한 모든 record의 slug를 현재 wiki 페이지와 대조하고, 페이지 `sources`가 정확히
   하나의 유효한 `raw/**`가 아니거나 record `raw_path`와 다르면 원장 전체를 거부한다.
2. `active + trusted + validity current + current raw SHA-256 match`인 claim만 trusted
   context와 cited answer에서 허용한다.
3. `untrusted` claim(예: `raw/newsletters/**`, `raw/clippings/**`) statement는 newline과
   heading을 escape한 deterministic single-line JSON data로만 격리하며 명령으로 해석하지 않는다.
4. `stale`, `superseded`, `source_missing`, `source_hash_mismatch`는 statement 없이 서로
   다른 exclusion reason으로 표면화한다.
5. 답변 인용 토큰은 `[claim:slug-N]` 형식이다. unknown/malformed/inactive/untrusted
   citation 하나라도 있으면 답변 전체를 거부한다. usable trusted claim이 있으면 성공
   답변은 최소 한 개를 인용해야 한다. 하나도 없을 때만 정확한 무인용 표준 응답
   `관련 정보 없음`을 허용한다.
6. SSE는 기존 chunk/byte cap 안에서 전부 buffering한 뒤 같은 citation gate를 통과한
   결과만 방출한다.
