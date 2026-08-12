"""자막 자동 생성(STT)과 내보내기(렌더링) API.

둘 다 몇 분씩 걸릴 수 있으므로 즉시 작업 번호(job_id)를 돌려주고,
화면이 /api/jobs/{job_id} 를 1초마다 물어보며 진행률을 표시한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import ffmpeg, jobs, stt, style_map, subtitles
from app.core import projects as store

router = APIRouter(prefix="/api/projects", tags=["render"])


def _load(project_id: str) -> dict[str, Any]:
    try:
        return store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


def _require_media(data: dict[str, Any]) -> Path:
    path = data.get("video_path")
    if not path:
        raise HTTPException(400, "이 프로젝트에는 영상이나 음성 파일이 없습니다.")
    media = Path(path)
    if not media.is_file():
        raise HTTPException(400, f"파일을 찾을 수 없습니다. 옮기거나 지우셨나요?\n{path}")
    return media


# ── 자막 자동 생성 (F-10) ─────────────────────────────────
class STTRequest(BaseModel):
    language: str = "ko"
    model: str = "small"
    max_chars: int = 20
    max_lines: int = 2


@router.post("/{project_id}/stt")
def start_stt(project_id: str, req: STTRequest) -> dict[str, Any]:
    data = _load(project_id)
    media = _require_media(data)

    # 사전 규칙을 함께 넘겨 인식 직후 자동 교정되게 한다 (F-12)
    corrections = data.get("dictionary") or []

    language = None if req.language == "auto" else req.language

    job_id = jobs.submit(
        "stt",
        "자막을 만들고 있습니다",
        stt.transcribe,
        media_path=str(media),
        language=language,
        model_size=req.model,
        max_chars=req.max_chars,
        max_lines=req.max_lines,
        corrections=corrections,
    )
    return {"job_id": job_id}


# ── 내보내기 (F-03, F-50, F-54) ──────────────────────────
class RenderRequest(BaseModel):
    kind: str  # "srt" | "vtt" | "burn" | "preview"
    preview_seconds: int = 10


def _safe_name(data: dict[str, Any]) -> str:
    """출력 파일 이름. 프로젝트 이름을 쓰되 파일명에 못 쓰는 문자는 뺀다."""
    import re

    name = re.sub(r'[\\/:*?"<>|,;\[\]\']+', "", data.get("name", "출력")).strip()
    return name[:40] or "출력"


def _export_subtitle_file(report, *, project_id: str, kind: str) -> dict[str, Any]:
    """SRT/VTT 파일을 만든다. 금방 끝나지만 흐름을 하나로 맞추려고 작업으로 돌린다."""
    report(0.1, "자막을 정리하고 있습니다…")
    data = store.load_project(project_id)
    segments = data.get("segments") or []
    if not segments:
        raise RuntimeError("내보낼 자막이 없습니다. 먼저 자막을 만들어 주세요.")

    style = style_map.normalize(data.get("style"))
    out_dir = store.project_dir(project_id) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_safe_name(data)}.{kind}"
    target = out_dir / filename

    report(0.5, "파일로 저장하고 있습니다…")
    writer = subtitles.save_srt if kind == "srt" else subtitles.save_vtt
    writer(segments, target, max_chars=style["max_chars"], max_lines=style["max_lines"])

    report(1.0, "완료되었습니다.")
    return {
        "path": str(target),
        "name": filename,
        "count": len(segments),
    }


def _export_video(report, *, project_id: str, preview: bool, seconds: int) -> dict[str, Any]:
    """자막을 영상에 새긴다. 미리보기면 앞부분만 만든다."""
    data = store.load_project(project_id)
    segments = data.get("segments") or []
    if not segments:
        raise RuntimeError("내보낼 자막이 없습니다. 먼저 자막을 만들어 주세요.")

    video_path = data.get("video_path")
    if not video_path or not Path(video_path).is_file():
        raise RuntimeError("원본 영상 파일을 찾을 수 없습니다. 옮기거나 지우셨나요?")

    style = style_map.normalize(data.get("style"))
    out_dir = store.project_dir(project_id) / "out"
    base = _safe_name(data)
    out_name = f"{base}_미리보기.mp4" if preview else f"{base}_자막.mp4"

    if preview:
        return ffmpeg.render_preview(
            report,
            video_path=video_path,
            segments=segments,
            style=style,
            out_dir=out_dir,
            out_name=out_name,
            seconds=seconds,
        )
    return ffmpeg.burn_subtitles(
        report,
        video_path=video_path,
        segments=segments,
        style=style,
        out_dir=out_dir,
        out_name=out_name,
    )


@router.post("/{project_id}/render")
def start_render(project_id: str, req: RenderRequest) -> dict[str, Any]:
    data = _load(project_id)

    if not (data.get("segments") or []):
        raise HTTPException(400, "내보낼 자막이 없습니다. 먼저 자막을 만들어 주세요.")

    if req.kind in ("srt", "vtt"):
        job_id = jobs.submit(
            "render",
            f"{req.kind.upper()} 자막 파일을 만들고 있습니다",
            _export_subtitle_file,
            project_id=project_id,
            kind=req.kind,
        )
        return {"job_id": job_id}

    if req.kind in ("burn", "preview"):
        _require_media(data)
        preview = req.kind == "preview"
        job_id = jobs.submit(
            "render",
            "10초 미리보기를 만들고 있습니다" if preview else "자막을 새긴 영상을 만들고 있습니다",
            _export_video,
            project_id=project_id,
            preview=preview,
            seconds=req.preview_seconds,
        )
        return {"job_id": job_id}

    raise HTTPException(400, "내보내기 종류는 srt, vtt, burn, preview 중 하나여야 합니다.")


# ── 자막 파일 가져오기 (F-04) ─────────────────────────────
class ImportRequest(BaseModel):
    path: str


@router.post("/{project_id}/subtitles/import")
def import_subtitles(project_id: str, req: ImportRequest) -> dict[str, Any]:
    """SRT/VTT 파일을 읽어 프로젝트 자막으로 넣는다 (기존 자막은 덮어쓴다)."""
    data = _load(project_id)

    path = Path(req.path)
    if not path.is_file():
        raise HTTPException(400, f"파일을 찾을 수 없습니다: {req.path}")

    try:
        segments = subtitles.load_subtitle_file(path)
    except subtitles.SubtitleImportError as exc:
        raise HTTPException(400, str(exc)) from exc

    data["segments"] = segments
    store.save_project(project_id, data)
    return {"count": len(segments), "segments": segments}
