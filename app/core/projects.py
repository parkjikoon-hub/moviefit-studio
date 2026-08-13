"""프로젝트 저장소 — 프로젝트 하나가 폴더 하나이고, 그 안의 project.json이 모든 작업 내용이다.

구조는 docs/TECH_SPEC.md 5절을 따른다.

    projects/
      20260812_143000_홍보영상/
        project.json     ← 자막 세그먼트, 스타일, 나레이션 설정
        narr/            ← 문장별 나레이션 오디오 (Phase 2)
        out/             ← 내보낸 결과물
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import PROJECTS_DIR
from app.core import framing, style_map

PROJECT_FILE = "project.json"
SCHEMA_VERSION = 1


class ProjectNotFound(Exception):
    """요청한 프로젝트 폴더가 없을 때."""


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _slugify(name: str) -> str:
    """프로젝트 이름을 폴더 이름으로 쓸 수 있게 다듬는다.

    한글은 그대로 두고(윈도우 파일명에 문제없음), 경로에 쓸 수 없는 문자만 걸러낸다.
    """
    name = unicodedata.normalize("NFC", name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "", name)  # 윈도우 금지 문자
    # FFmpeg 필터 문법에서 구분자로 쓰이는 문자들. 폴더 이름에 들어가면 렌더링이 통째로
    # 실패하는데 오류 메시지로는 원인을 찾을 수 없다 (memory/ffmpeg-filter-path-escaping.md)
    name = re.sub(r"[,;\[\]']+", "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name[:40] or "프로젝트"


def default_project(name: str, video_path: str | None, mode: str) -> dict[str, Any]:
    """새 프로젝트의 기본 내용. TECH_SPEC 5절의 데이터 모델."""
    return {
        "version": SCHEMA_VERSION,
        "id": "",  # new_project()에서 채운다
        "name": name,
        "video_path": video_path,
        "mode": mode,  # "video" 또는 "script"
        "script": "",  # 대본 모드 원문
        "segments": [],
        "style": style_map.apply_preset("basic"),
        # 내보낼 때의 화면비 (롱폼·숏폼). 기본은 원본 그대로라 옛 프로젝트와 동작이 같다.
        "output": dict(framing.DEFAULT_OUTPUT),
        "narration": {
            "gap": 0.3,
            "voice": "ko-KR-SunHiNeural",
            "engine": "edge",
            "global_rate": "+0%",
            "global_pitch": "+0Hz",
            "global_volume": "+0%",
            "original_audio_volume": 30,
            "ducking": False,
        },
        "stt": {"language": "ko", "model": "small"},
        "dictionary": [],  # 자막 교정 규칙 (F-12)  [{"from": "피엘에스", "to": "PLS"}]
        "read_dictionary": [],  # 나레이션 읽기 규칙  [{"from": "3D", "to": "쓰리디"}]
        "dictionary_applied": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def project_dir(project_id: str) -> Path:
    """프로젝트 폴더 경로. 상위 폴더로 빠져나가는 입력은 거부한다."""
    if not project_id or "/" in project_id or "\\" in project_id or ".." in project_id:
        raise ProjectNotFound(f"잘못된 프로젝트 이름입니다: {project_id!r}")
    return PROJECTS_DIR / project_id


def new_project(name: str, video_path: str | None = None, mode: str = "video") -> dict[str, Any]:
    """프로젝트 폴더를 만들고 project.json을 기록한 뒤 그 내용을 돌려준다."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_id = f"{stamp}_{_slugify(name)}"

    data = default_project(name=name, video_path=video_path, mode=mode)
    data["id"] = project_id

    pdir = project_dir(project_id)
    (pdir / "narr").mkdir(parents=True, exist_ok=True)
    (pdir / "out").mkdir(parents=True, exist_ok=True)

    save_project(project_id, data)
    return data


def load_project(project_id: str) -> dict[str, Any]:
    path = project_dir(project_id) / PROJECT_FILE
    if not path.exists():
        raise ProjectNotFound(f"프로젝트를 찾을 수 없습니다: {project_id}")
    return json.loads(path.read_text(encoding="utf-8"))


BACKUP_DIR = "backups"
BACKUP_KEEP = 10  # 최근 몇 개를 남길지


def _rotate_backup(pdir: Path) -> None:
    """저장 직전의 내용을 backups/ 에 복사해 두고, 오래된 것부터 지운다.

    실수로 자막을 전부 지우거나 잘못 덮어썼을 때 되돌릴 수 있는 마지막 안전장치다.
    """
    current = pdir / PROJECT_FILE
    if not current.is_file():
        return

    backups = pdir / BACKUP_DIR
    backups.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy2(current, backups / f"project_{stamp}.json")
    except OSError:
        return  # 백업 실패가 저장 자체를 막아서는 안 된다

    saved = sorted(backups.glob("project_*.json"))
    for old in saved[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)


def list_backups(project_id: str) -> list[dict[str, Any]]:
    """되돌릴 수 있는 백업 목록 (최신순)."""
    backups = project_dir(project_id) / BACKUP_DIR
    if not backups.is_dir():
        return []
    items = []
    for path in sorted(backups.glob("project_*.json"), reverse=True):
        stat = path.stat()
        items.append(
            {
                "file": path.name,
                "saved_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size": stat.st_size,
            }
        )
    return items


def restore_backup(project_id: str, filename: str) -> dict[str, Any]:
    """백업 하나를 현재 프로젝트로 되돌린다."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ProjectNotFound(f"잘못된 백업 이름입니다: {filename}")

    path = project_dir(project_id) / BACKUP_DIR / filename
    if not path.is_file():
        raise ProjectNotFound(f"백업 파일을 찾을 수 없습니다: {filename}")

    data = json.loads(path.read_text(encoding="utf-8"))
    return save_project(project_id, data)


def save_project(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """project.json에 기록한다. 저장 도중 프로그램이 죽어도 원본이 깨지지 않도록
    임시 파일에 먼저 쓰고 교체한다. 덮어쓰기 전 내용은 backups/ 에 남긴다."""
    pdir = project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)

    _rotate_backup(pdir)

    data["id"] = project_id
    data["version"] = SCHEMA_VERSION
    data["updated_at"] = _now_iso()

    target = pdir / PROJECT_FILE
    tmp = pdir / (PROJECT_FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return data


def delete_project(project_id: str) -> None:
    """프로젝트 폴더를 통째로 지운다 (되돌릴 수 없음 — 호출 전 UI에서 확인받을 것)."""
    import shutil

    pdir = project_dir(project_id)
    if not pdir.exists():
        raise ProjectNotFound(f"프로젝트를 찾을 수 없습니다: {project_id}")
    shutil.rmtree(pdir)


def list_projects() -> list[dict[str, Any]]:
    """최근 프로젝트 목록 (최근 수정순). 시작 화면에서 쓴다."""
    if not PROJECTS_DIR.exists():
        return []

    items: list[dict[str, Any]] = []
    for pdir in PROJECTS_DIR.iterdir():
        path = pdir / PROJECT_FILE
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # 깨진 프로젝트는 목록에서 조용히 건너뛴다
        items.append(
            {
                "id": data.get("id", pdir.name),
                "name": data.get("name", pdir.name),
                "mode": data.get("mode", "video"),
                "video_path": data.get("video_path"),
                "segment_count": len(data.get("segments", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )

    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items
