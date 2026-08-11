"""나레이션(TTS) 엔진 모음.

TECH_SPEC 3절 R1: edge-tts는 마이크로소프트의 비공식 경로라 언제든 막힐 수 있다.
그래서 엔진을 갈아 끼울 수 있도록 어댑터 구조로 만든다. 새 엔진을 쓰려면
base.TTSEngine을 구현한 파일 하나만 추가하고 아래 get_engine()에 등록하면 된다.
"""

from __future__ import annotations

from app.core.tts.base import TTSEngine, TTSError, Voice
from app.core.tts.edge import EdgeTTSEngine

_ENGINES: dict[str, TTSEngine] = {}


def get_engine(name: str = "edge") -> TTSEngine:
    """이름으로 엔진을 얻는다. 한 번 만든 엔진은 재사용한다."""
    if name not in _ENGINES:
        if name == "edge":
            _ENGINES[name] = EdgeTTSEngine()
        else:
            raise TTSError(f"알 수 없는 음성 엔진입니다: {name}")
    return _ENGINES[name]


__all__ = ["TTSEngine", "TTSError", "Voice", "EdgeTTSEngine", "get_engine"]
