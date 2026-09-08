#!/usr/bin/env python3
"""
sync_raw.py — sources.yaml의 소스 경로에서 raw/ 폴더로 델타 미러링.
변경·신규 파일만 복사한다. raw/ 파일은 삭제하지 않는다.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import frontmatter
import yaml

WIKI_ROOT = Path(__file__).parent.parent
SOURCES_FILE = WIKI_ROOT / "schema" / "sources.yaml"
STATE_FILE = WIKI_ROOT / ".sync_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def should_exclude(file: Path, exclude_tags: list[str]) -> bool:
    if not exclude_tags:
        return False
    try:
        post = frontmatter.load(str(file))
        file_tags = post.metadata.get("tags", [])
        if isinstance(file_tags, str):
            file_tags = [file_tags]
        return bool(set(exclude_tags) & set(file_tags))
    except Exception:
        return False


def capture_filter_reason(file: Path, source_cfg: dict) -> str | None:
    """capture 필터(require_keywords·min_word_count) 미달 사유를 반환한다.

    통과(또는 판정 불가)면 None:
    - require_keywords: 하나라도 본문에 포함되면 통과 (대소문자 무시)
    - min_word_count: 공백 분리 단어 수가 이 값 미만이면 미달
    - 두 필드 모두 미설정인 소스는 항상 통과 (기존 동작과 완전 동일)
    - md·txt 외 형식은 텍스트 판정 불가 → 통과
    """
    require_keywords = source_cfg.get("require_keywords") or []
    min_word_count = source_cfg.get("min_word_count") or 0
    if not require_keywords and not min_word_count:
        return None
    if file.suffix.lower() not in {".md", ".txt"}:
        return None
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if require_keywords:
        lowered = text.lower()
        if not any(str(k).lower() in lowered for k in require_keywords):
            return f"require_keywords {require_keywords} 미포함"
    if min_word_count:
        word_count = len(text.split())
        if word_count < min_word_count:
            return f"단어 수 {word_count} < min_word_count {min_word_count}"
    return None


def sync_source(source_cfg: dict, state: dict) -> tuple[int, int]:
    src = Path(source_cfg["source"]).expanduser()
    dst = WIKI_ROOT / source_cfg["target"]
    exclude_tags = source_cfg.get("exclude_tags", [])
    source_id = source_cfg["id"]

    if not src.exists():
        print(f"  [SKIP] 소스 없음: {src}")
        return 0, 0

    SUPPORTED = {".md", ".txt", ".pdf", ".docx", ".pptx"}
    extensions = {
        f".{e.lstrip('.')}" for e in source_cfg.get("extensions", [])
    } or SUPPORTED

    dst.mkdir(parents=True, exist_ok=True)
    last_sync = state.get(source_id, "1970-01-01T00:00:00")
    last_sync_dt = datetime.fromisoformat(last_sync)

    copied = skipped = 0
    for src_file in sorted(src.rglob("*")):
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in extensions:
            skipped += 1
            continue
        if src_file.stat().st_mtime <= last_sync_dt.timestamp():
            skipped += 1
            continue
        if should_exclude(src_file, exclude_tags):
            skipped += 1
            continue
        filter_reason = capture_filter_reason(src_file, source_cfg)
        if filter_reason:
            print(f"  [필터] {src_file.name} 건너뜀 — {filter_reason}")
            skipped += 1
            continue

        rel = src_file.relative_to(src)
        dst_file = dst / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied += 1

    state[source_id] = datetime.now().isoformat()
    return copied, skipped


def _git_clone_or_pull(repo_url: str, local_path: Path, repo_id: str) -> bool:
    """레포를 clone 또는 pull. 성공 시 True."""
    import subprocess
    if local_path.exists():
        r = subprocess.run(
            ["git", "-C", str(local_path), "pull", "--quiet"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  [{repo_id}] git pull 실패: {r.stderr.strip()}")
            return False
    else:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["git", "clone", "--quiet", repo_url, str(local_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  [{repo_id}] git clone 실패: {r.stderr.strip()}")
            return False
    return True


def _inject_frontmatter(src_file: Path, dst_file: Path, extra: dict) -> None:
    """dst_file이 frontmatter를 갖고 있지 않으면 extra를 앞에 추가해 저장."""
    content = src_file.read_text(encoding="utf-8", errors="replace")
    if not content.startswith("---"):
        fm_lines = ["---"] + [f"{k}: {v}" for k, v in extra.items()] + ["---", ""]
        content = "\n".join(fm_lines) + content
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(content, encoding="utf-8")


def sync_git_repo(repo_cfg: dict) -> tuple[int, int]:
    """git 레포를 로컬에 clone/pull 후 raw/로 복사.

    paths 키가 없으면 레포 내 raw/ 서브디렉토리를 통째로 복사.
    paths 키가 있으면 각 path 설정에 따라 선택적으로 복사.

    paths 항목 형식:
      - src: papers          # 레포 내 경로
        target: raw/clippings/  # 로컬 대상 (없으면 repo cfg의 target 사용)
        include: ["README.md"]  # 이 이름의 파일만 (없으면 전체)
        rename: "paper-{parent}-{topic}.md"  # 파일명 패턴 (없으면 원본명)
        frontmatter:           # 자동 주입할 frontmatter
          type: paper
          resonance: high
    """
    repo_url = repo_cfg["url"]
    repo_id = repo_cfg["id"]
    local_path = Path(repo_cfg.get("local_path", f"~/.llm-brain-cache/{repo_id}")).expanduser()

    if not _git_clone_or_pull(repo_url, local_path, repo_id):
        return 0, 0

    SUPPORTED = {".md", ".txt", ".pdf", ".docx", ".pptx"}
    copied = skipped = 0

    path_rules = repo_cfg.get("paths")

    if not path_rules:
        # 기존 방식: raw/ 서브디렉토리 전체 복사
        src_raw = local_path / "raw"
        if not src_raw.exists():
            return 0, 0
        for src_file in sorted(src_raw.rglob("*")):
            if not src_file.is_file() or src_file.name == ".gitkeep":
                skipped += 1
                continue
            if src_file.suffix.lower() not in SUPPORTED:
                skipped += 1
                continue
            dst_file = WIKI_ROOT / "raw" / src_file.relative_to(src_raw)
            if dst_file.exists() and dst_file.stat().st_mtime >= src_file.stat().st_mtime:
                skipped += 1
                continue
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
        return copied, skipped

    # paths 규칙 기반 복사
    default_target = repo_cfg.get("target", "raw/clippings/")
    for rule in path_rules:
        src_dir = local_path / rule["src"]
        if not src_dir.exists():
            continue
        target_dir = WIKI_ROOT / rule.get("target", default_target)
        target_dir.mkdir(parents=True, exist_ok=True)
        include_names = set(rule.get("include", []))
        fm_extra = rule.get("frontmatter", {})

        for src_file in sorted(src_dir.rglob("*")):
            if not src_file.is_file():
                continue
            if include_names and src_file.name not in include_names:
                skipped += 1
                continue
            if src_file.suffix.lower() not in SUPPORTED:
                skipped += 1
                continue
            if src_file.name == ".gitkeep":
                skipped += 1
                continue

            # 파일명 결정
            rename_pattern = rule.get("rename")
            if rename_pattern:
                # {slug}: 날짜-포함 폴더명, {topic}: 상위 topic 폴더명
                slug = src_file.parent.name
                # topic = src_dir 바로 아래 첫 번째 디렉토리 이름
                try:
                    rel_parts = src_file.relative_to(src_dir).parts
                    topic = rel_parts[0] if len(rel_parts) > 2 else ""
                except ValueError:
                    topic = ""
                dst_name = (rename_pattern
                            .replace("{slug}", slug)
                            .replace("{topic}", topic)
                            .replace("{name}", src_file.stem))
            else:
                dst_name = src_file.name

            dst_file = target_dir / dst_name
            if dst_file.exists():
                skipped += 1
                continue

            if fm_extra:
                _inject_frontmatter(src_file, dst_file, fm_extra)
            else:
                shutil.copy2(src_file, dst_file)
            copied += 1

    return copied, skipped


def main() -> None:
    config = yaml.safe_load(SOURCES_FILE.read_text())
    state = load_state()

    print(f"[sync_raw] {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    total_copied = 0

    # 일반 로컬 소스 동기화
    for source in config.get("sources", []):
        if source.get("disabled"):
            continue
        copied, skipped = sync_source(source, state)
        print(f"  [{source['id']}] 복사 {copied}개, 건너뜀 {skipped}개")
        total_copied += copied

    # git 레포 소스 동기화 (llm-brain-private 등)
    for repo in config.get("git_repos", []):
        if repo.get("disabled"):
            continue
        copied, skipped = sync_git_repo(repo)
        print(f"  [{repo['id']}] git 복사 {copied}개, 건너뜀 {skipped}개")
        total_copied += copied

    save_state(state)
    print(f"[sync_raw] 완료 — 총 {total_copied}개 파일 복사")

    if total_copied == 0 and "--quiet" not in sys.argv:
        print("[sync_raw] 새 파일 없음. ingest 불필요.")
        sys.exit(0)


if __name__ == "__main__":
    main()
