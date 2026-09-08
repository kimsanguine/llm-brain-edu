#!/bin/bash
# setup.sh — LLM Wiki 초기 설정 스크립트
# 실행: bash scripts/setup.sh

set -e

WIKI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WIKI_ROOT"

echo "=== LLM Wiki 초기 설정 ==="

# 1. Python 의존성 설치
if command -v uv &>/dev/null; then
    echo "[1/5] uv로 의존성 설치 중..."
    uv sync
    PYTHON=".venv/bin/python"
else
    echo "[1/5] pip로 의존성 설치 중..."
    python3 -m venv .venv
    .venv/bin/pip install -e . --quiet
    PYTHON=".venv/bin/python"
fi

# 2. raw/ 폴더 구조 생성
echo "[2/5] raw/ 폴더 구조 생성..."
mkdir -p raw/{til,meetings,notes,clippings,docs,blog,newsletters}
touch raw/til/.gitkeep raw/meetings/.gitkeep raw/notes/.gitkeep \
      raw/clippings/.gitkeep raw/docs/.gitkeep raw/blog/.gitkeep \
      raw/newsletters/.gitkeep

# 3. wiki/ 폴더 구조 생성
echo "[3/5] wiki/ 폴더 구조 생성..."
mkdir -p wiki/{concepts,tools,people,projects,business,lecture,insights,archive}
touch wiki/concepts/.gitkeep wiki/tools/.gitkeep wiki/people/.gitkeep \
      wiki/projects/.gitkeep wiki/business/.gitkeep wiki/lecture/.gitkeep \
      wiki/insights/.gitkeep wiki/archive/.gitkeep

# 4. sources.yaml 초기화
if [ ! -f schema/sources.yaml ]; then
    echo "[4/5] schema/sources.yaml 생성 (예시 파일 복사)..."
    cp schema/sources.example.yaml schema/sources.yaml
    echo "  → schema/sources.yaml을 열어 소스 경로를 설정하세요."
else
    echo "[4/5] schema/sources.yaml 이미 존재 — 건너뜀"
fi

# 5. config.yaml 초기화
if [ ! -f schema/config.yaml ]; then
    echo "[5/5] schema/config.yaml 생성..."
    cat > schema/config.yaml << 'EOF'
llm:
  engine: cli
  model: claude-opus-4-7
  api_key_env: ANTHROPIC_API_KEY
  max_tokens: 8192
EOF
else
    echo "[5/5] schema/config.yaml 이미 존재 — 건너뜀"
fi

echo ""
echo "=== 설정 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. schema/sources.yaml 편집 → 소스 경로 등록"
echo "  2. schema/config.yaml 편집 → LLM 엔진 선택 (cli / api)"
echo "  3. 첫 ingest 실행:"
echo "     $PYTHON scripts/ingest.py"
echo ""
echo "Obsidian 열기:"
echo "  이 폴더($WIKI_ROOT)를 Obsidian에서 'Open folder as vault'로 열기"

# ── seed-wiki 데모 안내 ──────────────────────────────────────────
if [ ! -f "wiki/concepts/$(ls wiki/concepts/ 2>/dev/null | head -1)" ] 2>/dev/null && [ -d "examples/seed-wiki" ]; then
  echo ""
  echo "📚 wiki/concepts/가 비어있어요. examples/seed-wiki를 복사해 즉시 데모 보시겠어요? (y/n)"
  read -r answer
  if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
    cp -r examples/seed-wiki/concepts examples/seed-wiki/tools wiki/
    cp examples/seed-wiki/graph.json wiki/graph.json
    cp examples/seed-wiki/index.md index.md
    echo "  ✓ seed-wiki 5개 페이지 복사 완료"
    echo "  → uv run python -m wiki_app 으로 데모 확인"
  fi
fi
