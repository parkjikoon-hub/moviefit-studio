"""Edge TTS 엔진 — 마이크로소프트 엣지의 무료 신경망 음성을 쓴다.

주의(TECH_SPEC R1): 공식 API가 아니라 엣지 브라우저가 쓰는 경로를 빌리는 방식이다.
언제든 막힐 수 있으므로 실패는 반드시 한국어 안내로 감싸서 올린다.

한국어 음성 사정(2026-08 확인): 한국어 전용 음성은 3개뿐이다.
다만 이름에 'Multilingual'이 붙은 음성들은 다른 나라 목소리로 한국어를 읽어 주므로,
한국어 나레이션에 쓸 수 있는 선택지로 함께 노출한다.
"""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any

from app.core.tts.base import (
    LANGUAGE_NAMES,
    Synthesis,
    TTSEngine,
    TTSError,
    Voice,
    has_hangul,
    language_name,
    language_of,
)
from app.core.tts.base import speaks_korean as _speaks_korean

# 화면에 보기 좋은 한국어 이름
_KOREAN_LABELS = {
    "ko-KR-SunHiNeural": "선희 · 여성 · 밝고 친근함",
    "ko-KR-InJoonNeural": "인준 · 남성 · 차분한 뉴스톤",
    "ko-KR-HyunsuMultilingualNeural": "현수 · 남성 · 부드럽고 다국어 가능",
}

# 언어 이름표는 base.py 한 곳에서만 관리한다 (두 벌로 갈라지면 한쪽만 늘어난다)
_LOCALE_NAMES = LANGUAGE_NAMES

# 서버가 "잠시 이용할 수 없음"(500번대)을 돌려주면 이만큼 쉬었다가 다시 묻는다.
# 2026-11-04 점검 중 503 이 이따금 왔고 바로 다음 요청은 성공했다. 나레이션은 문장마다
# 따로 물으므로, 한 번에 포기하면 긴 대본일수록 끝까지 가기 어렵다.
RETRY_DELAYS = (1.0, 2.0)


def _server_status(exc: Exception | None) -> int | None:
    """서버가 돌려준 거절 번호(403·503 등). 서버에 닿지도 못했으면 None.
    aiohttp 의 WSServerHandshakeError 가 status 를 들고 온다."""
    status = getattr(exc, "status", None)
    return status if isinstance(status, int) else None


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

    # ── 실패 원인 설명 ───────────────────────────────────
    @staticmethod
    def _explain_failure(exc: Exception | None, text: str, voice: str) -> str:
        """실패를 사용자가 고칠 수 있는 말로 바꾼다.

        가장 흔한 원인은 인터넷이 아니라 **언어 불일치**다. 프랑스어 목소리에게
        한국어 글을 주면 마이크로소프트 서버가 소리를 하나도 돌려주지 않는다
        (NoAudioReceived). 전에는 이것까지 "인터넷 연결을 확인하세요"로 안내해서,
        인터넷이 멀쩡한 사람이 될 때까지 다시 누르게 만들었다.
        """
        status = _server_status(exc)
        detail = f"(상세: {type(exc).__name__})" if exc is not None else "(상세: 소리가 비어 있음)"
        if status is not None:
            detail = f"(상세: {type(exc).__name__} {status})"

        # 서버가 대답은 했다 = 인터넷은 멀쩡하다. 여기서 인터넷을 탓하면 사용자는 계속 다시 누른다.
        if status == 403:
            return (
                "마이크로소프트 음성 서버가 접속을 거절했습니다. 프로그램에 든 음성 부품이 낡으면 "
                "이렇게 됩니다. 소개 사이트에서 새 판을 받아 설치해 주세요. "
                "(컴퓨터 시계가 크게 틀려도 이럴 수 있습니다)\n"
                f"{detail}"
            )
        if status is not None and status >= 500:
            return (
                "마이크로소프트 음성 서버가 지금 응답하지 않습니다. 세 번 시도했지만 되지 않았습니다. "
                "몇 분 뒤 다시 눌러 주세요.\n"
                f"{detail}"
            )

        if has_hangul(text) and not _speaks_korean(voice):
            lang = language_name(language_of(voice))
            return (
                f"이 목소리는 {lang} 전용이라 한국어를 읽지 못합니다.\n"
                "목소리 목록에서 위쪽의 '한국어 가능' 목소리를 골라 주세요. "
                "(이름에 Multilingual 이 붙은 목소리는 한국어를 읽습니다)\n"
                f"{detail}"
            )

        return (
            "나레이션을 만들지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요. "
            "계속 실패하면 목소리를 다른 것으로 바꿔 보세요.\n"
            f"{detail}"
        )

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

        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                communicate = edge_tts.Communicate(
                    text, voice, rate=rate, pitch=pitch, volume=volume
                )
                buffer = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buffer.write(chunk["data"])
                break
            except Exception as exc:
                status = _server_status(exc)
                if status is not None and status >= 500 and attempt < len(RETRY_DELAYS):
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                raise TTSError(self._explain_failure(exc, text, voice)) from exc

        audio = buffer.getvalue()
        if not audio:
            # 예외 없이 조용히 빈 소리가 오는 경우도 있다. 원인은 위와 같으므로 같은 설명을 쓴다.
            raise TTSError(self._explain_failure(None, text, voice))

        # 길이는 반드시 실측한다 (D1 동기화 정확도가 여기서 나온다)
        from app.core.ffprobe import measure_duration_bytes

        duration = measure_duration_bytes(audio, suffix=".mp3")
        return Synthesis(audio=audio, fmt="mp3", duration=duration)
