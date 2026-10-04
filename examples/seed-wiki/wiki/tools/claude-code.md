---
title: Claude Code CLI
type: tool
tags: [claude-code, anthropic, cli, agent-system]
created: 2026-05-23
updated: 2026-05-23
sources:
- https://docs.claude.com/en/docs/agents-and-tools/claude-code/overview
distill_level: 0
access_count: 0
---

# Claude Code CLI

Anthropic이 공식 배포하는 터미널 기반 AI 코딩 에이전트. 브라우저 없이 로컬 코드베이스에 직접 접근해 파일 읽기·쓰기·실행까지 수행한다.

## 설치

```bash
npm install -g @anthropic-ai/claude-code
claude  # 대화형 REPL 진입
```

## ChatGPT 대비 4가지 핵심 차이

| 항목 | Claude Code | ChatGPT (웹/앱) |
|------|------------|----------------|
| **컨텍스트 소스** | 로컬 파일 직접 읽기 (`Read`, `Grep`, `Bash`) | 사용자가 붙여넣기 |
| **에이전트 시스템** | `.claude/agents/` 폴더로 서브에이전트 정의 가능 | 플러그인 중심, 파일 기반 확장 불가 |
| **Hooks** | `settings.json` hook으로 저장·커밋 등 이벤트마다 결정론적 자동화 | 없음 |
| **MCP 연동** | Model Context Protocol 서버 직접 연결 (Obsidian, GitHub, Supabase 등) | 제한적 |

## 사용자 확장 구조

```
프로젝트 루트/
└── .claude/
    ├── agents/          # 서브에이전트 정의 (YAML 또는 .md)
    ├── commands/        # 슬래시 커맨드 (/ingest, /curate 등)
    └── settings.json    # hooks + permissions
```

- **`agents/`**: 반복 작업을 에이전트로 캡슐화. 예: `ingest-agent.md`, `curate-agent.md`
- **`commands/`**: `/명령어` 형태로 호출. 프롬프트 템플릿 + 파라미터 정의
- **`settings.json`**: `PreToolUse` / `PostToolUse` / `Stop` 훅으로 결정론적 자동화 부착

## `claude -p` 헤드리스 모드

```bash
claude -p "wiki/transformer.md를 요약해줘" --output-format json
```

- `--print` (`-p`): 단일 응답만 출력 후 종료 (REPL 미진입)
- API 키 불필요 — Anthropic 계정 로그인 상태면 바로 사용
- 스크립트·cron·파이프라인에서 LLM 호출을 직접 내장 가능

## llm-brain에서의 역할

llm-brain은 Claude Code를 **컴파일러 실행 환경**으로 사용한다.

- `/ingest`, `/curate`, `/query` 등 슬래시 커맨드가 `.claude/commands/`에 정의
- `wiki-web` AI 답변 기능: `claude -p "질문"` CLI 호출로 wiki 컨텍스트를 넘겨 응답 생성
  - 별도 API 키 없이 로그인 세션 재사용 가능
- `index.md` 기반 파일 탐색 → `Read` 도구로 wiki 페이지 로드 → 답변 생성까지 단일 프로세스

## 주요 내장 도구

| 도구 | 용도 |
|------|------|
| `Read` | 파일 내용 읽기 |
| `Write` / `Edit` | 파일 생성·수정 |
| `Bash` | 쉘 명령 실행 |
| `Grep` / `Glob` | 코드베이스 탐색 |
| `WebSearch` / `WebFetch` | 외부 URL 조회 |

## 관련 개념
- [[llm-wiki-pattern]]
- [[obsidian]]
