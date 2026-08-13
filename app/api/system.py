"""프로그램 자체와 관련된 API — 파일 선택 창, 폴더 열기, 환경 정보."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import __version__
from app.config import MEDIA_EXTS
from app.core import filedialog, framing
from app.core import projects as store

router = APIRouter(prefix="/api/system", tags=["system"])


SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".ssa"}


@router.post("/pick-file")
def pick_file(kind: str = "media") -> dict[str, Any]:
    """윈도우 기본 파일 선택 창을 띄워 파일 경로를 받아온다.

    kind="media"면 영상·오디오, kind="subtitle"이면 자막 파일을 고르게 한다.
    """
    if kind not in ("media", "subtitle"):
        raise HTTPException(400, "kind는 media 또는 subtitle이어야 합니다.")

    try:
        path = filedialog.ask_media_file(kind=kind)
    except filedialog.FileDialogUnavailable as exc:
        raise HTTPException(500, str(exc)) from exc

    if not path:
        return {"path": None, "cancelled": True}

    p = Path(path)
    allowed_exts = SUBTITLE_EXTS if kind == "subtitle" else MEDIA_EXTS
    if p.suffix.lower() not in allowed_exts:
        allowed = ", ".join(sorted(allowed_exts))
        raise HTTPException(400, f"지원하지 않는 형식입니다. 가능한 확장자: {allowed}")

    return {"path": str(p), "name": p.name, "size": p.stat().st_size, "cancelled": False}


class OpenFolderRequest(BaseModel):
    project_id: str
    subdir: str = "out"


@router.post("/open-folder")
def open_folder(req: OpenFolderRequest) -> dict[str, Any]:
    """내보내기 완료 후 결과물 폴더를 탐색기로 연다 (F-53)."""
    try:
        pdir = store.project_dir(req.project_id).resolve()
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    target = (pdir / req.subdir).resolve()
    if not target.is_relative_to(pdir):
        raise HTTPException(403, "허용되지 않은 경로입니다.")
    target.mkdir(parents=True, exist_ok=True)

    if sys.platform != "win32":
        raise HTTPException(400, "폴더 열기는 윈도우에서만 지원합니다.")
    subprocess.Popen(["explorer", str(target)])
    return {"opened": str(target)}


@router.get("/framing")
def framing_preview(
    w: int, h: int, aspect: str = "source", fit: str = "crop",
    focus_x: float = 50.0, focus_y: float = 50.0, pad_blur: bool = True,
) -> dict[str, Any]:
    """원본 크기와 설정을 주면 최종 출력 크기·자르는 영역을 돌려준다 (F-C).

    화면(app.js)은 미리보기 틀을 즉시 그려야 해서 같은 계산을 자바스크립트로도 갖고 있다.
    이 API는 **그 둘이 같은 답을 내는지 점검 스크립트가 대조하기 위한 것**이다.
    실제 내보내기는 언제나 파이썬 쪽(framing.py) 계산을 쓴다.
    """
    if w <= 0 or h <= 0:
        raise HTTPException(400, "영상 크기는 0보다 커야 합니다.")
    try:
        return framing.resolve(w, h, {
            "aspect": aspect, "fit": fit,
            "focus_x": focus_x, "focus_y": focus_y, "pad_blur": pad_blur,
        })
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/info")
def info() -> dict[str, Any]:
    """화면 하단에 표시할 프로그램 정보."""
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }
