"""Edge TTS 엔진 — 마이크로소프트 엣지의 무료 신경망 음성을 쓴다.

주의(TECH_SPEC R1): 공식 API가 아니라 엣지 브라우저가 쓰는 경로를 빌리는 방식이다.
언제든 막힐 수 있으므로 실패는 반드시 한국어 안내로 감싸서 올린다.

한국어 음성 사정(2026-08 확인): 한국어 전용 음성은 3개뿐이다.
다만 이름에 'Multilingual'이 붙은 음성들은 다른 나라 목소리로 한국어를 읽어 주므로,
한국어 나레이션에 쓸 수 있는 선택지로 함께 노출한다.
"""

from __future__ import annotations

import io
import re
from typing import Any

from app.core.tts.base import Synthesis, TTSEngine, TTSError, Voice

# 화면에 보기 좋은 한국어 이름
_KOREAN_LABELS = {
    "ko-KR-SunHiNeural": "선희 · 여성 · 밝고 친근함",
    "ko-KR-InJoonNeural": "인준 · 남성 · 차분한 뉴스톤",
    "ko-KR-HyunsuMultilingualNeural": "현수 · 남성 · 부드럽고 다국어 가능",
}

_LOCALE_NAMES = {
    "ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "es": "스페인어",
    "fr": "프랑스어", "de": "독일어", "it": "이탈리아어", "pt": "포르투갈어",
    "ru": "러시아어", "vi": "베트남어", "th": "태국어", "id": "인도네시아어",
    "hi": "힌디어", "ar": "아랍어",
}


def _pretty_name(short_name: str) -> str:
    """'en-US-AvaMultilingualNeural' → 'Ava'."""
    parts = short_name.split("-")
    raw = parts[-1] if parts else short_name
    raw = re.sub(r"(Multilingual)?Neural\d*$", "", raw)
    return raw or short_name


class EdgeTTSEngine(TTSEngine):
    name = "edge"
    label = "Edge 신경망 음성 (무료·인터넷 필요)"
    audio_format = "mp3"

    def __init__(self) -> None:
        self._voices: list[Voice] | None = None

    # ── 사용 가능 여부 ────────────────────────────────────
    def is_available(self) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, (
                "나레이션 기능에 필요한 부품(edge-tts)이 없습니다. "
                "명령창에서 python -m pip install edge-tts 를 실행해 주세요."
            )
        return True, ""

    # ── 목소리 목록 ──────────────────────────────────────
    async def list_voices(self) -> list[Voice]:
        if self._voices is not None:
            return self._voices

        ok, reason = self.is_available()
        if not ok:
            raise TTSError(reason)

        import edge_tts

        try:
            raw: list[dict[str, Any]] = await edge_tts.list_voices()
        except Exception as exc:  # 네트워크 문제, 경로 차단 등
            raise TTSError(
                "목소리 목록을 가져오지 못했습니다. 인터넷 연결을 확인해 주세요. "
                "(나레이션 기능은 인터넷이 필요합니다)"
            ) from exc

        voices: list[Voice] = []
        for item in raw:
            short = item["ShortName"]
            locale = item.get("Locale", "")
            lang = locale.split("-")[0]
            multilingual = "Multilingual" in short
            is_korean_native = lang == "ko"

            gender = (item.get("Gender") or "").lower()
            gender = gender if gender in ("male", "female") else "unknown"

            tags: list[str] = []
            voice_tag = item.get("VoiceTag") or {}
            tags += list(voice_tag.get("VoicePersonalities") or [])

            if is_korean_native:
                label = _KOREAN_LABELS.get(short, _pretty_name(short))
            else:
                lang_name = _LOCALE_NAMES.get(lang, locale)
                sex = {"female": "여성", "male": "남성"}.get(gender, "")
                suffix = " · 한국어 가능" if multilingual else ""
                label = f"{_pretty_name(short)} · {lang_name} · {sex}{suffix}"

            voices.append(
                Voice(
                    id=short,
                    label=label,
                    locale=locale,
                    gender=gender,
                    engine=self.name,
                    multilingual=multilingual,
                    speaks_korean=is_korean_native or multilingual,
                    tags=tags,
                )
            )

        # 한국어 전용 → 한국어 가능(다국어) → 나머지 순으로 정렬
        def sort_key(v: Voice) -> tuple[int, str]:
            if v.locale.startswith("ko"):
                return (0, v.id)
            if v.speaks_korean:
                return (1, v.locale + v.id)
            return (2, v.locale + v.id)

        voices.sort(key=sort_key)
        self._voices = voices
        return voices

    # ── 음성 생성 ────────────────────────────────────────
    async def synthesize(
        self, text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz", volume: str = "+0%"
    ) -> Synthesis:
        text = (text or "").strip()
        if not text:
            raise TTSError("읽을 내용이 비어 있습니다.")

        ok, reason = self.is_available()
        if not ok:
            raise TTSError(reason)

        import edge_tts

        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, pitch=pitch, volume=volume
            )
            buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer.write(chunk["data"])
        except Exception as exc:
            raise TTSError(
                "나레이션을 만들지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요. "
                "계속 실패하면 목소리를 다른 것으로 바꿔 보세요.\n"
                f"(상세: {type(exc).__name__})"
            ) from exc

        audio = buffer.getvalue()
        if not audio:
            raise TTSError("나레이션 결과가 비어 있습니다. 목소리를 바꿔서 다시 시도해 주세요.")

        # 길이는 반드시 실측한다 (D1 동기화 정확도가 여기서 나온다)
        from app.core.ffprobe import measure_duration_bytes

        duration = measure_duration_bytes(audio, suffix=".mp3")
        return Synthesis(audio=audio, fmt="mp3", duration=duration)
