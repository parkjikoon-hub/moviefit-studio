"""오디오 분석 API — 타임라인 파형과 무음 구간 감지.

실제 계산은 전부 app/core/audio_analysis.py가 한다. 여기서는 프로젝트에 등록된
영상 경로를 찾아 넘기고, 실패를 한국어 메시지로 바꿔 주는 일만 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core import audio_analysis
from app.core import projects as store
from app.core.ffprobe import ProbeError

router = APIRouter(prefix="/api/audio", tags=["audio"])


def _project_media(project_id: str) -> tuple[Path, Path]:
    """프로젝트에 등록된 미디어 파일 경로와 캐시 폴더 경로를 돌려준다."""
    try:
        data = store.load_project(project_id)
        pdir = store.project_dir(project_id)
    except store.ProjectNotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    video_path = data.get("video_path")
    if not video_path:
        raise HTTPException(404, "이 프로젝트에는 등록된 영상이 없습니다. 먼저 영상을 불러와 주세요.")

    path = Path(video_path)
    if not path.is_file():
        raise HTTPException(404, f"영상 파일을 찾을 수 없습니다: {path}")

    return path, pdir / "cache"


@router.get("/waveform/{project_id}")
def get_waveform(project_id: str, buckets: int = audio_analysis.DEFAULT_BUCKETS) -> dict[str, Any]:
    """타임라인 배경에 그릴 파형 값 (0.0~1.0). 한 번 계산하면 프로젝트 폴더에 캐시된다."""
    if buckets < 1 or buckets > audio_analysis.MAX_BUCKETS:
        raise HTTPException(
            400, f"파형 구간 수는 1 ~ {audio_analysis.MAX_BUCKETS} 사이여야 합니다: {buckets}"
        )

    path, cache_dir = _project_media(project_id)
    try:
        result = audio_analysis.waveform(path, buckets=buckets, cache_dir=cache_dir)
    except (audio_analysis.AudioAnalysisError, ProbeError) as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "duration": result["duration"],
        "buckets": result["buckets"],
        "peaks": result["peaks"],
    }


@router.get("/silence/{project_id}")
def get_silence(
    project_id: str,
    noise_db: float = -35.0,
    min_silence: float = 0.35,
    min_speech: float = 0.3,
) -> dict[str, Any]:
    """문장 사이의 조용한 틈을 찾아, 그 반대인 '말하는 구간' 목록을 돌려준다."""
    path, _ = _project_media(project_id)
    try:
        regions = audio_analysis.detect_speech_regions(
            path, noise_db=noise_db, min_silence=min_silence, min_speech=min_speech
        )
    except (audio_analysis.AudioAnalysisError, ProbeError) as exc:
        raise HTTPException(400, str(exc)) from exc

    return {"regions": regions, "count": len(regions)}
