"""프로젝트 만들기·읽기·저장하기 API (F-02)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import AUDIO_EXTS, IMAGE_EXTS, MEDIA_EXTS
from app.core import projects as store

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = "새 프로젝트"
    video_path: str | None = None
    mode: str = "video"  # "video" | "script"
    # 사진으로 시작할 때 고른 사진들 (순서가 곧 영상에 나오는 순서다)
    image_paths: list[str] | None = None
    # 음원으로 시작할 때 고른 mp3
    audio_path: str | None = None


@router.get("")
def get_projects() -> dict[str, Any]:
    """최근 프로젝트 목록 (시작 화면용)."""
    return {"projects": store.list_projects()}


@router.post("", status_code=201)
def create_project(req: CreateProjectRequest) -> dict[str, Any]:
    if req.mode not in ("video", "script"):
        raise HTTPException(400, "모드는 'video' 또는 'script'만 가능합니다.")

    if req.video_path:
        path = Path(req.video_path)
        if not path.is_file():
            raise HTTPException(400, f"파일을 찾을 수 없습니다: {req.video_path}")
        if path.suffix.lower() not in MEDIA_EXTS:
            allowed = ", ".join(sorted(MEDIA_EXTS))
            raise HTTPException(400, f"지원하지 않는 형식입니다. 가능한 확장자: {allowed}")

    if req.audio_path:
        apath = Path(req.audio_path)
        if not apath.is_file():
            raise HTTPException(400, f"음원 파일을 찾을 수 없습니다: {req.audio_path}")
        if apath.suffix.lower() not in AUDIO_EXTS:
            allowed = ", ".join(sorted(AUDIO_EXTS))
            raise HTTPException(400, f"음원 형식이 아닙니다. 가능한 확장자: {allowed}")

    # 사진은 여러 장이므로 한 장이라도 잘못되면 어느 것이 문제인지 이름을 밝혀 준다.
    for raw in req.image_paths or []:
        ipath = Path(raw)
        if not ipath.is_file():
            raise HTTPException(400, f"사진 파일을 찾을 수 없습니다: {raw}")
        if ipath.suffix.lower() not in IMAGE_EXTS:
            allowed = ", ".join(sorted(IMAGE_EXTS))
            raise HTTPException(
                400, f"사진 형식이 아닙니다 ({ipath.name}). 가능한 확장자: {allowed}"
            )

    name = req.name.strip() or _fallback_name(req)
    return store.new_project(
        name=name,
        video_path=req.video_path,
        mode=req.mode,
        images=req.image_paths,
        audio_path=req.audio_path,
    )


def _fallback_name(req: CreateProjectRequest) -> str:
    """이름을 안 적었을 때 고른 파일에서 이름을 지어 준다."""
    if req.video_path:
        return Path(req.video_path).stem
    if req.audio_path:
        return Path(req.audio_path).stem
    if req.image_paths:
        return f"사진{len(req.image_paths)}장"
    return "새 프로젝트"


@router.get("/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{project_id}")
def put_project(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """프론트엔드가 2초 디바운스로 보내는 자동 저장."""
    try:
        store.load_project(project_id)  # 존재 확인
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return store.save_project(project_id, data)


@router.get("/{project_id}/backups")
def get_backups(project_id: str) -> dict[str, Any]:
    """되돌릴 수 있는 자동 백업 목록 (저장할 때마다 최근 10개를 남긴다)."""
    try:
        store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"backups": store.list_backups(project_id)}


@router.post("/{project_id}/backups/{filename}/restore")
def restore_backup(project_id: str, filename: str) -> dict[str, Any]:
    """백업 하나를 현재 프로젝트로 되돌린다."""
    try:
        return store.restore_backup(project_id, filename)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/{project_id}", status_code=204)
def remove_project(project_id: str) -> None:
    try:
        store.delete_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
