"""나레이션 API — 대본으로 음성을 만들고, 영상에 입히고, 오디오로 내보낸다.

(F-40, F-42, F-43, F-51, F-52)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import audio_mix, jobs, narration
from app.core import projects as store

router = APIRouter(prefix="/api/projects", tags=["narration"])


def _load(project_id: str) -> dict[str, Any]:
    try:
        return store.load_project(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


# ── 나레이션 만들기 (F-40, F-42, F-43) ────────────────────
class NarrationRequest(BaseModel):
    script: str | None = None
    segment_id: str | None = None  # 주면 그 문장만 다시 만든다 (F-43)


@router.post("/{project_id}/narration")
def start_narration(project_id: str, req: NarrationRequest) -> dict[str, Any]:
    data = _load(project_id)

    if req.segment_id:
        if not any(s.get("id") == req.segment_id for s in data.get("segments") or []):
            raise HTTPException(400, "다시 만들 문장을 찾을 수 없습니다.")
        label = "이 문장만 다시 만들고 있습니다"
    else:
        text = req.script if req.script is not None else (data.get("script") or "")
        if not text.strip():
            raise HTTPException(400, "대본이 비어 있습니다. 읽을 내용을 입력해 주세요.")
        label = "나레이션을 만들고 있습니다"

    job_id = jobs.submit(
        "tts",
        label,
        narration.build_full_narration,
        project_id=project_id,
        script=req.script,
        only_segment_id=req.segment_id,
    )
    return {"job_id": job_id}


@router.post("/{project_id}/script/split")
def preview_split(project_id: str, req: NarrationRequest) -> dict[str, Any]:
    """대본을 문장으로 나눈 결과를 미리 보여 준다 (음성은 만들지 않는다)."""
    data = _load(project_id)
    text = req.script if req.script is not None else (data.get("script") or "")
    sentences = narration.split_script(text)
    chars = sum(len(s.replace(" ", "")) for s in sentences)
    return {
        "sentences": sentences,
        "count": len(sentences),
        # 한국어 나레이션은 대략 초당 5글자. 실제 길이는 만들어 봐야 안다.
        "estimated_seconds": round(chars / 5.0 + len(sentences) * float(
            (data.get("narration") or {}).get("gap", 0.3)
        ), 1),
    }


# ── 나레이션 내보내기 (F-51, F-52) ────────────────────────
class NarrationExportRequest(BaseModel):
    kind: str  # "audio" (오디오만) | "video" (영상에 입히기)
    fmt: str = "mp3"  # audio일 때만
    original_volume: int | None = None
    duck: bool | None = None


def _export_audio(report, *, project_id: str, fmt: str) -> dict[str, Any]:
    clips = narration.narration_clips(project_id)
    if not clips:
        raise RuntimeError("내보낼 나레이션이 없습니다. 먼저 나레이션을 만들어 주세요.")

    data = store.load_project(project_id)
    out_dir = store.project_dir(project_id) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    import re

    name = re.sub(r'[\\/:*?"<>|,;\[\]\']+', "", data.get("name", "나레이션")).strip()[:40]
    target = out_dir / f"{name}_나레이션.{fmt}"

    result = audio_mix.export_narration_audio(report, clips=clips, out_path=target)
    return {"path": str(target), "name": target.name, "duration": result.get("duration")}


def _export_video(
    report, *, project_id: str, original_volume: int, duck: bool
) -> dict[str, Any]:
    data = store.load_project(project_id)
    pdir = store.project_dir(project_id)

    rel = (data.get("narration") or {}).get("audio")
    narration_path = pdir / rel if rel else None
    if not narration_path or not narration_path.is_file():
        raise RuntimeError("나레이션 음성이 없습니다. 먼저 나레이션을 만들어 주세요.")

    video_path = data.get("video_path")
    if not video_path or not Path(video_path).is_file():
        raise RuntimeError("원본 영상 파일을 찾을 수 없습니다. 옮기거나 지우셨나요?")

    import re

    name = re.sub(r'[\\/:*?"<>|,;\[\]\']+', "", data.get("name", "출력")).strip()[:40]

    # 출력 화면비 (F-C). 자막 영상과 같은 설정을 써야 두 결과물의 화면비가 어긋나지 않는다.
    from app.core import framing

    output = framing.normalize(data.get("output"))
    tag = "" if output["aspect"] == "source" else f"_{output['aspect'].replace(':', '-')}"

    return audio_mix.mix_narration_into_video(
        report,
        video_path=video_path,
        narration_path=narration_path,
        out_dir=pdir / "out",
        out_name=f"{name}{tag}_나레이션영상.mp4",
        original_volume=original_volume,
        duck=duck,
        output=output,
    )


@router.post("/{project_id}/narration/export")
def export_narration(project_id: str, req: NarrationExportRequest) -> dict[str, Any]:
    data = _load(project_id)
    narration_settings = data.get("narration") or {}

    if req.kind == "audio":
        if req.fmt not in ("mp3", "wav"):
            raise HTTPException(400, "오디오 형식은 mp3 또는 wav만 가능합니다.")
        job_id = jobs.submit(
            "render",
            "나레이션 오디오를 만들고 있습니다",
            _export_audio,
            project_id=project_id,
            fmt=req.fmt,
        )
        return {"job_id": job_id}

    if req.kind == "video":
        if not data.get("video_path"):
            raise HTTPException(400, "영상이 있어야 나레이션을 입힐 수 있습니다.")

        volume = req.original_volume
        if volume is None:
            volume = int(narration_settings.get("original_audio_volume", 30))
        duck = req.duck if req.duck is not None else bool(narration_settings.get("ducking"))

        job_id = jobs.submit(
            "render",
            "나레이션을 영상에 입히고 있습니다",
            _export_video,
            project_id=project_id,
            original_volume=volume,
            duck=duck,
        )
        return {"job_id": job_id}

    raise HTTPException(400, "내보내기 종류는 audio 또는 video여야 합니다.")


@router.get("/{project_id}/narration/status")
def narration_status(project_id: str) -> dict[str, Any]:
    """나레이션이 얼마나 준비되었는지. 화면의 안내 문구에 쓴다."""
    data = _load(project_id)
    segments = data.get("segments") or []
    voiced = [s for s in segments if (s.get("tts") or {}).get("duration")]
    settings = data.get("narration") or {}

    narration_seconds = settings.get("audio_duration")
    video_seconds = None
    video_path = data.get("video_path")
    if video_path and Path(video_path).is_file():
        from app.core.ffprobe import ProbeError, measure_duration

        try:
            video_seconds = measure_duration(video_path)
        except ProbeError:
            video_seconds = None

    # 나레이션이 영상보다 길면 뒤가 잘린다. 미리 알려 줘야 한다.
    warning = None
    if narration_seconds and video_seconds and narration_seconds > video_seconds + 0.05:
        over = narration_seconds - video_seconds
        warning = (
            f"나레이션이 영상보다 {over:.1f}초 깁니다. "
            f"영상에 입히면 뒷부분 {over:.1f}초가 잘립니다. "
            "문장을 줄이거나 말하기 속도를 올려 보세요."
        )

    return {
        "segments": len(segments),
        "voiced": len(voiced),
        "ready": bool(settings.get("audio")),
        "narration_seconds": narration_seconds,
        "video_seconds": video_seconds,
        "warning": warning,
    }
