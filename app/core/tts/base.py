"""나레이션 엔진이 지켜야 할 약속(인터페이스).

새 엔진을 붙일 때 이 파일의 TTSEngine을 상속해서 세 가지만 구현하면 된다:
  - list_voices()  어떤 목소리를 쓸 수 있는가
  - synthesize()   글자를 소리로 바꾼다
  - is_available() 지금 쓸 수 있는 상태인가
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 언어 코드 → 한국어 이름. 목소리 이름표와 오류 안내가 함께 쓴다.
LANGUAGE_NAMES: dict[str, str] = {
    "ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "es": "스페인어",
    "fr": "프랑스어", "de": "독일어", "it": "이탈리아어", "pt": "포르투갈어",
    "ru": "러시아어", "vi": "베트남어", "th": "태국어", "id": "인도네시아어",
    "hi": "힌디어", "ar": "아랍어", "tr": "터키어", "nl": "네덜란드어",
    "pl": "폴란드어", "sv": "스웨덴어", "uk": "우크라이나어",
}

# 미리듣기 견본 문장 — **반드시 그 목소리의 언어로** 준다.
#
# 언어가 안 맞는 문장을 보내면 마이크로소프트 서버가 소리를 하나도 돌려주지 않는다
# (edge-tts 가 NoAudioReceived 를 던진다). 실제로 한국어 문장을 고정으로 보내던 때에는
# 322개 목소리 중 307개가 실패했다. 목록에 보이는 목소리는 모두 들을 수 있어야 하므로
# 언어별 견본을 둔다. 없는 언어는 영어로 대신한다 (모든 목소리가 영어는 읽어 준다).
SAMPLE_TEXTS: dict[str, str] = {
    "ko": "안녕하세요. 이 목소리로 나레이션을 만들어 드립니다.",
    "en": "Hello. This is how your narration will sound with this voice.",
    "ja": "こんにちは。この声でナレーションをお作りします。",
    "zh": "您好。这就是用这个声音配音的效果。",
    "es": "Hola. Así sonará tu narración con esta voz.",
    "fr": "Bonjour. Voici le son de votre narration avec cette voix.",
    "de": "Hallo. So klingt Ihre Erzählung mit dieser Stimme.",
    "it": "Ciao. Ecco come suonerà la tua narrazione con questa voce.",
    "pt": "Olá. É assim que a sua narração vai soar com esta voz.",
    "ru": "Здравствуйте. Так будет звучать озвучивание этим голосом.",
    "ar": "مرحبا. هكذا سيبدو التعليق الصوتي بهذا الصوت.",
    "hi": "नमस्ते। इस आवाज़ के साथ आपका वर्णन ऐसा सुनाई देगा।",
    "vi": "Xin chào. Đây là giọng đọc cho phần lời dẫn của bạn.",
    "th": "สวัสดีค่ะ นี่คือเสียงบรรยายด้วยเสียงนี้",
    "id": "Halo. Beginilah suara narasi Anda dengan suara ini.",
    "tr": "Merhaba. Anlatımınız bu sesle böyle duyulacak.",
    "nl": "Hallo. Zo klinkt uw voice-over met deze stem.",
    "pl": "Dzień dobry. Tak zabrzmi narracja tym głosem.",
    "sv": "Hej. Så här låter din berättarröst med den här rösten.",
    "uk": "Вітаю. Так звучатиме озвучення цим голосом.",
}


def language_of(voice_id: str) -> str:
    """목소리 이름에서 언어 코드를 뽑는다. 'fr-FR-DeniseNeural' → 'fr'."""
    return (voice_id or "").split("-")[0].lower()


def language_name(code: str) -> str:
    """언어 코드를 한국어 이름으로. 모르는 코드는 코드를 그대로 돌려준다."""
    return LANGUAGE_NAMES.get(code, code or "알 수 없는 언어")


def sample_text_for(voice_id: str) -> str:
    """이 목소리로 미리들을 견본 문장. 그 목소리의 언어로 골라 준다."""
    return SAMPLE_TEXTS.get(language_of(voice_id), SAMPLE_TEXTS["en"])


def has_hangul(text: str) -> bool:
    """글에 한글이 섞여 있는가. 언어 불일치를 짚어 내는 데 쓴다."""
    return any("가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" for ch in text or "")


def speaks_korean(voice_id: str) -> bool:
    """이 목소리가 한국어를 읽을 수 있는가 — 한국어 전용이거나 다국어여야 한다."""
    return language_of(voice_id) == "ko" or "Multilingual" in (voice_id or "")


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
