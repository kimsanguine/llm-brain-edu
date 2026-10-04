---
title: Obsidian
type: tool
tags: [obsidian, note-taking, graph-view, wikilink, canvas]
created: 2026-05-23
updated: 2026-05-23
sources:
- https://obsidian.md
- https://jsoncanvas.org/spec/1.0/
distill_level: 0
access_count: 0
---

# Obsidian

로컬 파일 기반 마크다운 노트 앱. **vault = 폴더**가 핵심 철학이다. 외부 서버 없이 마크다운 파일을 그대로 저장하며, 소유권과 이식성이 완전히 사용자에게 있다.

## 기본 개념

- **Vault**: 노트의 루트 폴더. `.obsidian/` 디렉토리에 설정이 저장됨
- **Note**: 일반 `.md` 파일. 어떤 텍스트 에디터로도 열림
- **Wikilink**: `[[페이지명]]` 문법으로 노트 간 연결. 양방향 백링크 자동 생성
- **Frontmatter**: YAML 헤더(`---`)로 메타데이터 지정. 필터·정렬·쿼리에 활용

## Graph View

wikilink로 연결된 페이지를 **노드 그래프**로 시각화하는 핵심 기능.

- 연결이 많은 노트(허브)는 큰 노드로 표시 → 지식 구조의 중심 개념 식별
- 필터: 태그·폴더·연결 수로 표시 범위 조절
- Local Graph: 특정 페이지의 1-2홉 이웃만 표시 (집중 탐색)
- 색상 그룹: 폴더나 태그 기준으로 노드 색 분류 가능

## Canvas (`.canvas` 파일)

JSON Canvas Spec 기반의 시각적 배치 도구.

```json
{
  "nodes": [
    { "id": "1", "type": "file", "file": "wiki/transformer.md", "x": 0, "y": 0, "width": 400, "height": 300 }
  ],
  "edges": [
    { "id": "e1", "fromNode": "1", "toNode": "2" }
  ]
}
```

- 노트를 카드 형태로 캔버스에 배치 + 화살표로 연결
- 개방 스펙 (`jsoncanvas.org`) — Obsidian 종속 아님
- 설계 스케치, 프로젝트 맵, 글 구조 잡기 등에 활용

## Plugin 생태계 & 동기화

커뮤니티 플러그인 1,500개 이상. 주요 플러그인: Dataview(Frontmatter DB 쿼리), Templater(템플릿 스크립트), Tasks(체크박스 트래커), Git(자동 커밋·푸시).

동기화: **Obsidian Sync**(유료, E2E 암호화) / **iCloud·Google Drive**(폴더 동기화, 충돌 주의) / **Git**(무료, 버전 관리).

## llm-brain과의 통합

프로젝트 루트를 vault root로 설정하면 `raw/`와 `wiki/` 양쪽이 Graph View에 표시된다.

```
vault root = 260516_llm_brain/
├── raw/        → 소스 노트 (Obsidian에서 읽기 전용으로 관리)
├── wiki/       → 컴파일된 노트 (Graph View 허브 대부분 여기 집중)
└── .obsidian/  → 설정, 플러그인, Graph View 레이아웃
```

- wikilink(`[[페이지명]]`)가 wiki 페이지 간 연결에 그대로 사용 → Graph View에서 지식 맵 자동 생성
- Obsidian MCP(`mcp__obsidian-vault__*`)로 Claude Code가 vault 파일을 직접 읽고 쓸 수 있음
- `access_count` frontmatter를 Dataview 플러그인으로 쿼리하면 "가장 많이 본 wiki 페이지" 대시보드 구성 가능

## 관련 개념
- [[llm-wiki-pattern]]
- [[distill-progressive]]
- [[claude-code]]
