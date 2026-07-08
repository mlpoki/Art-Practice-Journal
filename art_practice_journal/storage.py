from __future__ import annotations

import os
import json
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".pdf", ".txt", ".rtf", ".md"}


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    db_path: Path
    attachments_dir: Path
    thumbnails_dir: Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path(root: Path | None = None) -> Path:
    return (root or app_root()).resolve() / "config.json"


def load_config(root: Path | None = None) -> dict[str, str]:
    path = config_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def save_config(config: dict[str, str], root: Path | None = None) -> None:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_app_paths(root: Path | None = None) -> AppPaths:
    base = (root or app_root()).resolve()
    config = load_config(base)
    data_dir = Path(config.get("data_dir", str(base / "data"))).expanduser().resolve()
    paths = AppPaths(
        root=base,
        data_dir=data_dir,
        db_path=Path(config.get("db_path", str(data_dir / "art_journal.db"))).expanduser().resolve(),
        attachments_dir=Path(config.get("attachments_dir", str(data_dir / "attachments"))).expanduser().resolve(),
        thumbnails_dir=Path(config.get("thumbnails_dir", str(data_dir / "thumbnails"))).expanduser().resolve(),
    )
    ensure_app_dirs(paths)
    return paths


def ensure_app_dirs(paths: AppPaths) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    paths.thumbnails_dir.mkdir(parents=True, exist_ok=True)


def classify_file(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "file"


def copy_attachment(source: str | Path, paths: AppPaths, entry_date: str | None = None) -> Path:
    src = Path(source)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(str(src))

    try:
        year, month = (entry_date or date.today().isoformat()).split("-")[:2]
    except ValueError:
        today = date.today()
        year, month = str(today.year), f"{today.month:02d}"

    target_dir = paths.attachments_dir / year / month
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in src.stem).strip()
    safe_stem = safe_stem or "attachment"
    target_name = f"{safe_stem}-{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
    target = target_dir / target_name
    shutil.copy2(src, target)
    return target


def open_with_system(path: str | Path) -> None:
    target = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess

        subprocess.Popen(["open", str(target)])
    else:
        import subprocess

        subprocess.Popen(["xdg-open", str(target)])
