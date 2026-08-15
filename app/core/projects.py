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
from app.core import effects, framing, style_map

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


# 사진 한 장이 화면에 머무는 기본 시간(초). 너무 짧으면 눈이 못 따라간다.
DEFAULT_IMAGE_DURATION = 3.0


def normalize_images(raw: Any) -> list[dict[str, Any]]:
    """사진 목록을 저장할 모양으로 다듬는다. 순서는 받은 그대로 지킨다.

    각 칸의 뜻:
        id       화면에서 이 사진을 가리키는 이름
        path     원본 사진의 실제 경로 (복사하지 않는다)
        duration 이 사진이 보이는 시간(초). seg_id 가 있으면 무시된다
        seg_id   짝지어진 자막(가사) 줄. 값이 있으면 그 줄이 시작할 때 이 사진이 나온다
    """
    items: list[dict[str, Any]] = []
    for index, entry in enumerate(raw or []):
        if isinstance(entry, str):
            entry = {"path": entry}
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        try:
            duration = float(entry.get("duration", DEFAULT_IMAGE_DURATION))
        except (TypeError, ValueError):
            duration = DEFAULT_IMAGE_DURATION
        items.append(
            {
                "id": str(entry.get("id") or f"i{index + 1:03d}"),
                "path": path,
                "duration": max(0.1, round(duration, 3)),
                "seg_id": entry.get("seg_id") or None,
            }
        )
    return items


def default_project(
    name: str,
    video_path: str | None,
    mode: str,
    images: Any = None,
    audio_path: str | None = None,
) -> dict[str, Any]:
    """새 프로젝트의 기본 내용. TECH_SPEC 5절의 데이터 모델."""
    image_list = normalize_images(images)
    # 사진이 들어 있으면 사진 영상 프로젝트다. mode 에 세 번째 값을 만들지 않는다 —
    # mode 는 왼쪽 패널을 무엇으로 바꿀지 정하는 값이고, 두 단추짜리 토글이 깨진다.
    output = dict(framing.DEFAULT_OUTPUT)
    canvas = None
    if image_list:
        output["aspect"] = framing.DEFAULT_CANVAS_ASPECT
        width, height = framing.canvas_size(output["aspect"])
        canvas = {"width": width, "height": height}

    return {
        "version": SCHEMA_VERSION,
        "id": "",  # new_project()에서 채운다
        "name": name,
        "video_path": video_path,
        # 음원 영상에서 쓰는 소리 파일. 영상 프로젝트에서는 언제나 None 이다.
        # (사진만 있는 프로젝트에서 이 소리가 **영상 길이를 정하는 주인공**이 된다)
        "audio_path": audio_path,
        # 배경음악 — 이미 영상이 있는 프로젝트에 **깔아 주는** 음악이다.
        # 주인공 음원(audio_path)과 역할이 정반대라 칸을 따로 둔다:
        #   audio_path 는 길이를 정하고, bgm_path 는 영상 길이에 맞춰진다.
        # 옛 프로젝트에는 이 칸이 없으므로 읽을 때 .get() 으로 꺼낸다.
        "bgm_path": None,
        "bgm_volume": 20,  # 배경이므로 작게. 0~100
        # 사진 영상의 사진 목록. 비어 있으면 지금까지와 똑같은 영상/대본 프로젝트다.
        "images": image_list,
        # 사진들이 들어갈 화면 크기. 사진이 없으면 None (원본 영상이 기준이 된다).
        "canvas": canvas,
        "mode": mode,  # "video" 또는 "script"
        "script": "",  # 대본 모드 원문
        "segments": [],
        "style": style_map.apply_preset("basic"),
        # 내보낼 때의 화면비 (롱폼·숏폼). 기본은 원본 그대로라 옛 프로젝트와 동작이 같다.
        "output": output,
        # 화면 효과 막대. **비어 있는 것이 기본이다** — 아무 효과도 미리 넣지 않는다.
        # 사용자가 타임라인에 막대를 놓아야만 생긴다 (app/core/effects.py).
        "effects": [],
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


def new_project(
    name: str,
    video_path: str | None = None,
    mode: str = "video",
    images: Any = None,
    audio_path: str | None = None,
) -> dict[str, Any]:
    """프로젝트 폴더를 만들고 project.json을 기록한 뒤 그 내용을 돌려준다."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_id = f"{stamp}_{_slugify(name)}"

    data = default_project(
        name=name, video_path=video_path, mode=mode, images=images, audio_path=audio_path
    )
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
    # 화면 효과 막대는 사용자가 보낸 값이므로 저장 직전에 한 번 거른다. 영상 길이는
    # 여기서 모르므로(사진 영상은 원본 영상이 없다) 길이 자르기는 렌더링 때 한 번 더 한다.
    if "effects" in data:
        data["effects"] = effects.normalize(data.get("effects"))

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
                # 옛 프로젝트에는 이 키들이 없다. 없으면 빈 값으로 받아 그대로 열리게 한다.
                "audio_path": data.get("audio_path"),
                "image_count": len(data.get("images") or []),
                "segment_count": len(data.get("segments", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )

    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items
