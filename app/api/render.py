"""자막 자동 생성(STT)과 내보내기(렌더링) API.

둘 다 몇 분씩 걸릴 수 있으므로 즉시 작업 번호(job_id)를 돌려주고,
화면이 /api/jobs/{job_id} 를 1초마다 물어보며 진행률을 표시한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import align, audio_mix, ffmpeg, framing, jobs, slideshow, stt, style_map, subtitles
from app.core import projects as store

router = APIRouter(prefix="/api/projects", tags=["render"])


def _load(project_id: str) -> dict[str, Any]:
    try:
        return store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


def _require_media(data: dict[str, Any]) -> Path:
    path = data.get("video_path") or data.get("audio_path")
    if not path:
        raise HTTPException(400, "이 프로젝트에는 영상이나 음성 파일이 없습니다.")
    media = Path(path)
    if not media.is_file():
        raise HTTPException(400, f"파일을 찾을 수 없습니다. 옮기거나 지우셨나요?\n{path}")
    return media


def _images_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    """사진 목록. 옛 프로젝트에는 이 칸이 없으므로 없으면 빈 목록으로 받는다."""
    return data.get("images") or []


def _require_frame_source(data: dict[str, Any]) -> None:
    """영상을 만들려면 '그림이 될 것'이 있어야 한다 — 원본 영상이거나 사진들이거나.

    음원만 있는 프로젝트는 소리는 있지만 화면이 없다. 그대로 내보내려 하면
    FFmpeg 이 "화면 크기 정보를 찾지 못했습니다"라는 알아듣기 어려운 말을 한다.
    """
    if _images_of(data):
        return
    if data.get("video_path"):
        _require_media(data)
        return
    if data.get("audio_path"):
        raise HTTPException(
            400,
            "음원만 있어서 화면에 보일 것이 없습니다. 왼쪽 [사진] 칸에서 사진을 넣어 주세요.",
        )
    raise HTTPException(400, "이 프로젝트에는 영상이나 사진이 없습니다.")


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


# ── 내 대본에 시간 붙이기 (강제정렬) ──────────────────────
class AlignRequest(BaseModel):
    script: str
    language: str = "ko"
    model: str = "small"
    max_chars: int = 20
    max_lines: int = 2


def _align_script(
    report, *, project_id: str, script: str, language: str | None,
    model_size: str, max_chars: int, max_lines: int,
) -> dict[str, Any]:
    """음성인식으로 '언제 말했는지'만 얻고, 글자는 사용자 대본을 쓴다."""
    data = store.load_project(project_id)
    media = data.get("video_path") or data.get("audio_path")
    if not media or not Path(media).is_file():
        raise RuntimeError("원본 파일을 찾을 수 없습니다. 옮기거나 지우셨나요?")

    def _stt_report(fraction: float, message: str) -> None:
        report(0.92 * max(0.0, min(1.0, fraction)), message)

    heard = stt.transcribe(
        _stt_report,
        media_path=str(media),
        language=language,
        model_size=model_size,
        max_chars=max_chars,
        max_lines=max_lines,
        corrections=[],
    )

    report(0.94, "대본과 말소리를 맞춰 보고 있습니다…")
    try:
        aligned = align.align_script(
            script, heard.get("words") or [], duration=heard.get("duration")
        )
    except align.AlignError as exc:
        raise RuntimeError(str(exc)) from exc

    report(0.97, "자막 문장으로 나누고 있습니다…")
    segments = subtitles.split_into_segments(aligned, max_chars=max_chars, max_lines=max_lines)
    subtitles.apply_corrections(segments, data.get("dictionary") or [])
    align.mark_guessed_segments(segments, aligned)

    guessed = sum(1 for s in segments if s.get("guessed"))
    report(1.0, f"자막 {len(segments)}개를 만들었습니다 (짐작한 줄 {guessed}개).")
    return {
        "segments": segments,
        "guessed": guessed,
        "total": len(segments),
        "duration": heard.get("duration"),
    }


@router.post("/{project_id}/align")
def start_align(project_id: str, req: AlignRequest) -> dict[str, Any]:
    """이미 말소리가 든 영상에 **내가 가진 대본**의 시간을 자동으로 붙인다."""
    data = _load(project_id)
    _require_media(data)

    if not (req.script or "").strip():
        raise HTTPException(400, "대본이 비어 있습니다. 영상에서 말하는 내용을 붙여넣어 주세요.")

    job_id = jobs.submit(
        "align",
        "대본에 시간을 붙이고 있습니다",
        _align_script,
        project_id=project_id,
        script=req.script,
        language=None if req.language == "auto" else req.language,
        model_size=req.model,
        max_chars=req.max_chars,
        max_lines=req.max_lines,
    )
    return {"job_id": job_id}


# ── 내보내기 (F-03, F-50, F-54) ──────────────────────────
class RenderRequest(BaseModel):
    kind: str  # "srt" | "vtt" | "burn" | "preview" | "slideshow"
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


def _export_video(
    report, *, project_id: str, preview: bool, seconds: int, with_subtitles: bool = True
) -> dict[str, Any]:
    """자막을 영상에 새긴다. 미리보기면 앞부분만 만든다.

    사진 프로젝트면 원본 영상 대신 사진들을 이어붙여 만든다. with_subtitles 가
    False 면 자막 없이 사진만으로 만든다 (사진을 넣자마자 결과를 볼 수 있게).
    """
    data = store.load_project(project_id)
    segments = (data.get("segments") or []) if with_subtitles else []
    images = data.get("images") or []

    if with_subtitles and not segments:
        raise RuntimeError("내보낼 자막이 없습니다. 먼저 자막을 만들어 주세요.")

    if images:
        return _export_slideshow(
            report, data=data, project_id=project_id,
            segments=segments, preview=preview, seconds=seconds,
        )

    video_path = data.get("video_path")
    if not video_path or not Path(video_path).is_file():
        raise RuntimeError("원본 영상 파일을 찾을 수 없습니다. 옮기거나 지우셨나요?")

    style = style_map.normalize(data.get("style"))
    # 출력 화면비 (F-C). 파일 이름에도 남겨서 가로본과 세로본을 눈으로 구별할 수 있게 한다.
    output = framing.normalize(data.get("output"))
    tag = "" if output["aspect"] == "source" else f"_{output['aspect'].replace(':', '-')}"
    # 화면 효과 막대. 비어 있으면 지금까지와 똑같은 경로로 간다 (느려지지도 않는다).
    effects_list = data.get("effects") or []

    out_dir = store.project_dir(project_id) / "out"
    base = _safe_name(data)
    out_name = f"{base}{tag}_미리보기.mp4" if preview else f"{base}{tag}_자막.mp4"

    if preview:
        return ffmpeg.render_preview(
            report,
            video_path=video_path,
            segments=segments,
            style=style,
            out_dir=out_dir,
            out_name=out_name,
            seconds=seconds,
            output=output,
            effects_list=effects_list,
        )
    result = ffmpeg.burn_subtitles(
        report,
        video_path=video_path,
        segments=segments,
        style=style,
        out_dir=out_dir,
        out_name=out_name,
        output=output,
        effects_list=effects_list,
    )
    return _with_background_music(report, data=data, result=result)


def _with_background_music(report, *, data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """배경음악이 지정되어 있으면 만들어진 영상 위에 깐다 (없으면 그대로 돌려준다).

    자막은 `-vf`(화면 필터)로 새기고 소리 섞기는 `-filter_complex` 가 필요한데
    FFmpeg 은 둘을 함께 쓰는 것을 거부한다. 그래서 두 번에 나눈다.
    이 단계는 화면을 다시 그리지 않으므로(-c:v copy) 거의 시간이 들지 않는다.
    """
    music = data.get("bgm_path")
    if not music:
        return result

    from pathlib import Path as _Path

    if not _Path(music).is_file():
        # 음악 파일이 사라졌다고 해서 이미 만든 영상을 버릴 이유는 없다. 그대로 두고 알린다.
        result["bgm_warning"] = "배경음악 파일을 찾을 수 없어 넣지 않았습니다."
        return result

    made = _Path(result["path"])
    with_music = made.with_name(f"{made.stem}_배경음{made.suffix}")
    mixed = audio_mix.add_background_music(
        report,
        video_path=made,
        music_path=music,
        out_path=with_music,
        volume=int(data.get("bgm_volume", 20)),
    )
    made.unlink(missing_ok=True)  # 음악 없는 중간 결과는 남길 이유가 없다

    result.update({
        "path": mixed["path"],
        "filename": mixed["filename"],
        "bgm": True,
        "bgm_volume": mixed["music_volume"],
    })
    return result


def _export_slideshow(
    report, *, data: dict[str, Any], project_id: str,
    segments: list[dict[str, Any]], preview: bool, seconds: int,
) -> dict[str, Any]:
    """사진들을 이어붙여 영상을 만든다. 자막과 음원은 있으면 함께 들어간다."""
    images = slideshow.resolve_durations(data)
    output = framing.normalize(data.get("output"))
    canvas = slideshow.canvas_of(data)
    style = style_map.normalize(data.get("style"))

    tag = f"_{output['aspect'].replace(':', '-')}" if output["aspect"] != "source" else ""
    base = _safe_name(data)
    if preview:
        out_name = f"{base}{tag}_미리보기.mp4"
    elif segments:
        out_name = f"{base}{tag}_자막.mp4"
    else:
        out_name = f"{base}{tag}_사진영상.mp4"

    return slideshow.build_slideshow(
        report,
        project_dir=store.project_dir(project_id),
        images=images,
        canvas=canvas,
        output=output,
        out_dir=store.project_dir(project_id) / "out",
        out_name=out_name,
        segments=segments,
        style=style,
        audio_path=data.get("audio_path"),
        seconds=float(seconds) if preview else None,
        fast=preview,
    )


@router.post("/{project_id}/render")
def start_render(project_id: str, req: RenderRequest) -> dict[str, Any]:
    data = _load(project_id)

    # 사진 영상은 자막 없이도 만들 수 있다 — 사진을 넣자마자 결과를 볼 수 있어야 한다.
    if req.kind == "slideshow":
        if not _images_of(data):
            raise HTTPException(400, "사진이 한 장도 없습니다. 먼저 사진을 넣어 주세요.")
        job_id = jobs.submit(
            "render",
            "사진으로 영상을 만들고 있습니다",
            _export_video,
            project_id=project_id,
            preview=False,
            seconds=req.preview_seconds,
            with_subtitles=False,
        )
        return {"job_id": job_id}

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
        _require_frame_source(data)
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

    raise HTTPException(
        400, "내보내기 종류는 srt, vtt, burn, preview, slideshow 중 하나여야 합니다."
    )


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
