"""나레이션(TTS) API — 목소리 목록과 미리듣기."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.core import tts as tts_mod
from app.core.tts.base import TTSError

router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.get("/voices")
async def get_voices(korean_only: bool = False) -> dict[str, Any]:
    """쓸 수 있는 목소리 목록.

    korean_only=true 로 부르면 한국어를 읽을 수 있는 목소리만 돌려준다
    (한국어 전용 3개 + 다국어 음성들).
    """
    engine = tts_mod.get_engine("edge")
    try:
        voices = await engine.list_voices()
    except TTSError as exc:
        raise HTTPException(503, str(exc)) from exc

    if korean_only:
        voices = [v for v in voices if v.speaks_korean]

    native = [v for v in voices if v.locale.startswith("ko")]
    multi = [v for v in voices if v.speaks_korean and not v.locale.startswith("ko")]

    return {
        "engine": engine.name,
        "total": len(voices),
        "korean_native_count": len(native),
        "korean_capable_count": len(native) + len(multi),
        "voices": [v.to_dict() for v in voices],
    }


class PreviewRequest(BaseModel):
    voice: str
    text: str = "안녕하세요. 이 목소리로 나레이션을 만들어 드립니다."
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@router.post("/preview")
async def preview(req: PreviewRequest) -> Response:
    """목소리 미리듣기 — 짧은 문장을 즉시 소리로 만들어 돌려준다 (F-41)."""
    text = req.text.strip()[:200]  # 미리듣기는 짧게 (경계에서만 검증)
    if not text:
        raise HTTPException(400, "미리들을 문장이 비어 있습니다.")

    engine = tts_mod.get_engine("edge")
    try:
        result = await engine.synthesize(
            text, req.voice, rate=req.rate, pitch=req.pitch, volume=req.volume
        )
    except TTSError as exc:
        raise HTTPException(503, str(exc)) from exc

    return Response(
        content=result.audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Audio-Duration": f"{result.duration:.3f}",
        },
    )


@router.get("/engines")
def get_engines() -> dict[str, Any]:
    """설치된 나레이션 엔진과 각각의 사용 가능 여부."""
    engine = tts_mod.get_engine("edge")
    ok, reason = engine.is_available()
    return {
        "engines": [
            {
                "name": engine.name,
                "label": engine.label,
                "available": ok,
                "reason": reason,
            }
        ]
    }
