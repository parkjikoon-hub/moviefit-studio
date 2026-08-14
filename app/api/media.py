"""영상·오디오 스트리밍 (Range 요청 지원).

브라우저의 <video> 태그는 재생 위치를 옮길 때 "파일의 이 구간만 달라"(Range 요청)고
물어본다. 이걸 지원하지 않으면 탐색(시크)이 동작하지 않으므로 직접 처리한다.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core import filmstrip
from app.core import projects as store

router = APIRouter(prefix="/media", tags=["media"])

CHUNK = 1024 * 512  # 512KB씩 흘려보낸다
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            data = fh.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def stream_file(path: Path, range_header: str | None) -> StreamingResponse:
    """파일 하나를 Range 지원과 함께 내보낸다."""
    if not path.is_file():
        raise HTTPException(404, f"파일을 찾을 수 없습니다: {path}")

    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    start, end = 0, size - 1
    status = 200
    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if match:
            raw_start, raw_end = match.groups()
            if raw_start:
                start = int(raw_start)
                if raw_end:
                    end = int(raw_end)
            elif raw_end:  # "bytes=-500" → 마지막 500바이트
                start = max(0, size - int(raw_end))
            if start >= size:
                raise HTTPException(416, "요청한 구간이 파일 크기를 벗어났습니다.")
            end = min(end, size - 1)
            status = 206

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-store",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    return StreamingResponse(
        _iter_file(path, start, end), status_code=status, media_type=media_type, headers=headers
    )


@router.get("/project/{project_id}/video")
def project_video(project_id: str, request: Request, range: str | None = Header(default=None)):
    """프로젝트에 등록된 원본 영상을 재생용으로 내보낸다."""
    try:
        data = store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    video_path = data.get("video_path")
    if not video_path:
        raise HTTPException(404, "이 프로젝트에는 등록된 영상이 없습니다.")
    return stream_file(Path(video_path), range)


@router.get("/project/{project_id}/filmstrip")
def project_filmstrip(project_id: str, request: Request, range: str | None = Header(default=None)):
    """타임라인에 깔 '영상 띠' 그림 한 장 (화면들을 가로로 이어붙인 것).

    처음 한 번만 만들고 프로젝트의 cache/ 에 저장한다. 다음부터는 즉시 나온다.
    화면에서는 <img> 하나로 받아 타임라인 폭에 맞춰 늘려 깐다.
    """
    try:
        data = store.load_project(project_id)
        pdir = store.project_dir(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    video_path = data.get("video_path")
    if not video_path:
        raise HTTPException(404, "이 프로젝트에는 등록된 영상이 없습니다.")

    try:
        info = filmstrip.build(video_path, pdir / "cache")
    except filmstrip.FilmstripError as exc:
        raise HTTPException(400, str(exc)) from exc

    return stream_file(info["path"], range)


@router.get("/project/{project_id}/audio")
def project_audio(project_id: str, request: Request, range: str | None = Header(default=None)):
    """음원 영상 프로젝트의 mp3 를 재생용으로 내보낸다.

    화면은 이 소리를 **시계로도 쓴다.** 재생 위치가 흘러야 자막 오버레이·타임라인·
    두드려 맞추기가 전부 살아난다.
    """
    try:
        data = store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    audio_path = data.get("audio_path")
    if not audio_path:
        raise HTTPException(404, "이 프로젝트에는 등록된 음원이 없습니다.")
    return stream_file(Path(audio_path), range)


@router.get("/project/{project_id}/image/{index}")
def project_image(project_id: str, index: int, request: Request,
                  range: str | None = Header(default=None)):
    """사진 목록의 index 번째 사진을 미리보기용으로 내보낸다 (0부터 센다)."""
    try:
        data = store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    images = data.get("images") or []
    if index < 0 or index >= len(images):
        raise HTTPException(404, "그런 번호의 사진이 없습니다.")

    path = Path(images[index].get("path") or "")
    if not path.is_file():
        raise HTTPException(404, f"사진 파일을 찾을 수 없습니다: {path.name}")
    return stream_file(path, range)


@router.get("/project/{project_id}/file/{rel_path:path}")
def project_file(
    project_id: str, rel_path: str, request: Request, range: str | None = Header(default=None)
):
    """프로젝트 폴더 안의 파일(나레이션 오디오, 내보낸 결과물)을 내보낸다."""
    try:
        pdir = store.project_dir(project_id).resolve()
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    target = (pdir / rel_path).resolve()
    if not target.is_relative_to(pdir):  # 프로젝트 폴더 밖은 접근 금지
        raise HTTPException(403, "허용되지 않은 경로입니다.")
    return stream_file(target, range)
