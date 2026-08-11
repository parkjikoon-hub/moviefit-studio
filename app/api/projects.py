"""프로젝트 만들기·읽기·저장하기 API (F-02)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import MEDIA_EXTS
from app.core import projects as store

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = "새 프로젝트"
    video_path: str | None = None
    mode: str = "video"  # "video" | "script"


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

    name = req.name.strip() or (Path(req.video_path).stem if req.video_path else "새 프로젝트")
    return store.new_project(name=name, video_path=req.video_path, mode=req.mode)


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


@router.delete("/{project_id}", status_code=204)
def remove_project(project_id: str) -> None:
    try:
        store.delete_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
