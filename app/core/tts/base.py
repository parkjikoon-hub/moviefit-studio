"""나레이션 엔진이 지켜야 할 약속(인터페이스).

새 엔진을 붙일 때 이 파일의 TTSEngine을 상속해서 세 가지만 구현하면 된다:
  - list_voices()  어떤 목소리를 쓸 수 있는가
  - synthesize()   글자를 소리로 바꾼다
  - is_available() 지금 쓸 수 있는 상태인가
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class TTSError(Exception):
    """나레이션 생성 실패. 메시지는 사용자에게 그대로 보여줄 한국어여야 한다."""


@dataclass
class Voice:
    """목소리 하나."""

    id: str  # 엔진에 넘길 실제 이름 (예: ko-KR-SunHiNeural)
    label: str  # 화면에 보여줄 이름 (예: 선희 · 여성 · 밝은 톤)
    locale: str  # ko-KR, en-US ...
    gender: str  # "female" | "male" | "unknown"
    engine: str  # "edge" | "clone" ...
    multilingual: bool = False  # 한국어 외 언어도 자연스럽게 읽는가
    speaks_korean: bool = False  # 한국어 나레이션에 쓸 수 있는가
    tags: list[str] = field(default_factory=list)  # 밝은, 차분한 등

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "locale": self.locale,
            "gender": self.gender,
            "engine": self.engine,
            "multilingual": self.multilingual,
            "speaks_korean": self.speaks_korean,
            "tags": self.tags,
        }


@dataclass
class Synthesis:
    """생성된 음성 한 덩어리."""

    audio: bytes
    fmt: str  # "mp3" | "wav"
    duration: float  # 초. 실측값이어야 한다 (추정 금지 — TECH_SPEC 8절)


class TTSEngine:
    """모든 나레이션 엔진의 부모."""

    name: str = "base"
    label: str = "기본 엔진"
    audio_format: str = "mp3"

    def is_available(self) -> tuple[bool, str]:
        """(쓸 수 있는가, 못 쓰면 그 이유를 한국어로)."""
        raise NotImplementedError

    async def list_voices(self) -> list[Voice]:
        raise NotImplementedError

    async def synthesize(
        self, text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz", volume: str = "+0%"
    ) -> Synthesis:
        """글자 → 소리. 실패하면 TTSError를 한국어 메시지와 함께 던진다."""
        raise NotImplementedError
