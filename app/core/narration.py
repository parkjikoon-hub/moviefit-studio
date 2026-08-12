"""대본 → 나레이션 음성 + 완벽히 동기화된 자막 (PRD 차별점 D1, 기능 F-40·F-42·F-43).

이 프로그램이 CapCut보다 나은 지점이 바로 여기다. CapCut은 나레이션 오디오와 자막이
별개 트랙이라 동기화를 손으로 맞춰야 한다. 여기서는 순서를 뒤집는다:

    문장별로 음성을 만든다 → 만들어진 음성의 길이를 '실제로 잰다' → 그 길이로 자막 시각을 계산한다

추정하지 않고 재기 때문에 소리와 자막이 어긋날 수가 없다.

타이밍 계산식 (TECH_SPEC 5절):
    start[0] = 0
    start[i] = start[i-1] + duration[i-1] + gap[i-1]
    end[i]   = start[i] + duration[i]
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

from app.core import tts as tts_module
from app.core.ffprobe import measure_duration
from app.core.tts.base import TTSError

Reporter = Callable[..., None]

# 문장을 끊는 기준. 한국어는 마침표를 빠뜨리는 경우가 많아 줄바꿈도 문장 경계로 본다.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s+|\n+")

# 한 문장이 이보다 길면 TTS가 부자연스러워지고 자막도 너무 길어진다
MAX_SENTENCE_CHARS = 120


class NarrationError(Exception):
    """나레이션 생성 실패. 메시지는 사용자에게 그대로 보여줄 한국어여야 한다."""


# ── 대본 나누기 ────────────────────────────────────────────
def split_script(script: str) -> list[str]:
    """대본을 문장 단위로 나눈다.

    문장부호나 줄바꿈으로 먼저 자르고, 그래도 너무 긴 문장은 쉼표에서 한 번 더 자른다.
    """
    rough = [s.strip() for s in _SENTENCE_END.split(script or "") if s.strip()]

    sentences: list[str] = []
    for piece in rough:
        if len(piece) <= MAX_SENTENCE_CHARS:
            sentences.append(piece)
            continue

        # 너무 긴 문장은 쉼표 기준으로 쪼갠다
        parts = [p.strip() for p in re.split(r"(?<=[,、])\s*", piece) if p.strip()]
        buffer = ""
        for part in parts:
            if not buffer:
                buffer = part
            elif len(buffer) + len(part) + 1 <= MAX_SENTENCE_CHARS:
                buffer += " " + part
            else:
                sentences.append(buffer)
                buffer = part
        if buffer:
            sentences.append(buffer)

    return sentences


def apply_read_dictionary(text: str, rules: list[dict[str, str]] | None) -> str:
    """나레이션 읽기 사전을 적용한다 (F-48). 예: '3D' → '쓰리디'.

    음성 합성기에 넘기기 직전에만 바꾸고, 화면에 보이는 자막 글자는 원문 그대로 둔다.
    """
    for rule in rules or []:
        source = rule.get("from")
        if source:
            text = text.replace(source, rule.get("to", ""))
    return text


# ── 타이밍 계산 (D1의 핵심) ────────────────────────────────
def recalculate_timings(
    segments: list[dict[str, Any]], default_gap: float = 0.3, start_at: float = 0.0
) -> list[dict[str, Any]]:
    """각 문장 음성의 실측 길이를 이어 붙여 자막 시각을 다시 계산한다.

    문장 하나를 고쳐 다시 만들었을 때도 이 함수만 부르면 뒤쪽 타이밍이 전부 밀린다 (F-43).
    길이를 아직 모르는 문장(음성을 안 만든 문장)은 글자 수로 임시 추정한다.
    """
    cursor = start_at
    for segment in segments:
        tts_info = segment.get("tts") or {}
        duration = tts_info.get("duration")

        if not duration or duration <= 0:
            # 아직 음성이 없는 문장 — 한국어는 대략 초당 5글자로 임시 계산한다.
            # 음성을 만들면 실측값으로 바뀐다.
            duration = max(0.6, len((segment.get("text") or "").replace(" ", "")) / 5.0)

        gap = tts_info.get("gap")
        if gap is None:
            gap = default_gap

        segment["start"] = round(cursor, 3)
        segment["end"] = round(cursor + duration, 3)
        cursor = segment["end"] + float(gap)

    return segments


# ── 문장별 음성 만들기 ─────────────────────────────────────
def _synthesize_one(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    volume: str,
    target: Path,
    engine_name: str = "edge",
) -> float:
    """문장 하나를 소리로 만들어 파일로 저장하고, 그 길이(초)를 실측해서 돌려준다."""
    engine = tts_module.get_engine(engine_name)

    try:
        result = asyncio.run(
            engine.synthesize(text, voice, rate=rate, pitch=pitch, volume=volume)
        )
    except TTSError:
        raise
    except Exception as exc:
        raise NarrationError(
            "나레이션을 만드는 중 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.\n"
            f"(상세: {type(exc).__name__})"
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.audio)

    # 앞뒤 무음을 잘라 낸다. edge-tts는 말 앞에 0.2초, 뒤에 0.9초쯤 침묵을 붙여 주는데
    # 그대로 두면 "문장 사이 0.3초" 설정이 실제로는 1.4초가 되고, 말이 끝난 뒤에도
    # 자막이 한참 더 떠 있게 된다. 자르고 나면 잰 길이가 곧 '말하는 시간'이 된다.
    from app.core import audio_mix

    audio_mix.trim_silence(target)

    # 엔진이 알려 준 길이를 믿지 않고 파일에서 다시 잰다.
    # 이 값이 자막 타이밍의 근거이므로 가장 확실한 방법을 쓴다.
    return measure_duration(target)


def _voice_settings(
    segment: dict[str, Any], narration: dict[str, Any]
) -> tuple[str, str, str, str]:
    """문장별 설정이 있으면 그것을, 없으면 전체 설정을 쓴다."""
    tts_info = segment.get("tts") or {}
    voice = tts_info.get("voice") or narration.get("voice") or "ko-KR-SunHiNeural"
    rate = tts_info.get("rate") or narration.get("global_rate") or "+0%"
    pitch = narration.get("global_pitch") or "+0Hz"
    volume = narration.get("global_volume") or "+0%"
    return voice, rate, pitch, volume


# ── 전체 나레이션 생성 (F-40, F-42) ────────────────────────
def generate_narration(
    report: Reporter,
    *,
    project_id: str,
    script: str | None = None,
    only_segment_id: str | None = None,
) -> dict[str, Any]:
    """대본으로 문장별 음성을 만들고 자막 타이밍을 산출한다.

    only_segment_id를 주면 그 문장만 다시 만들고 이후 타이밍을 재계산한다 (F-43).
    """
    from app.core import projects as store

    data = store.load_project(project_id)
    narration = data.get("narration") or {}
    default_gap = float(narration.get("gap", 0.3))
    read_rules = data.get("read_dictionary") or []

    narr_dir = store.project_dir(project_id) / "narr"
    narr_dir.mkdir(parents=True, exist_ok=True)

    # ── 어떤 문장들을 만들 것인가 ──
    if only_segment_id:
        segments = data.get("segments") or []
        targets = [s for s in segments if s.get("id") == only_segment_id]
        if not targets:
            raise NarrationError("다시 만들 문장을 찾을 수 없습니다.")
    else:
        text = script if script is not None else (data.get("script") or "")
        sentences = split_script(text)
        if not sentences:
            raise NarrationError("대본이 비어 있습니다. 읽을 내용을 입력해 주세요.")

        # 기존 문장별 설정(목소리·속도·쉼)은 순서가 같으면 이어받는다
        previous = data.get("segments") or []
        segments = []
        for index, sentence in enumerate(sentences):
            carried = (previous[index].get("tts") or {}) if index < len(previous) else {}
            segments.append(
                {
                    "id": f"s{index + 1:03d}",
                    "start": 0.0,
                    "end": 0.0,
                    "text": sentence,
                    "tts": {
                        "voice": carried.get("voice"),
                        "rate": carried.get("rate"),
                        "gap": carried.get("gap"),
                    },
                }
            )
        data["segments"] = segments
        targets = segments

    # ── 문장별로 소리 만들기 ──
    total = len(targets)
    for index, segment in enumerate(targets):
        spoken = apply_read_dictionary(segment.get("text") or "", read_rules)
        if not spoken.strip():
            continue

        voice, rate, pitch, volume = _voice_settings(segment, narration)
        target = narr_dir / f"{segment['id']}.mp3"

        report(
            0.05 + 0.85 * index / max(1, total),
            f"나레이션을 만들고 있습니다 ({index + 1}/{total}번째 문장)",
        )

        duration = _synthesize_one(spoken, voice, rate, pitch, volume, target)

        tts_info = segment.setdefault("tts", {})
        tts_info["voice"] = voice
        tts_info["rate"] = rate
        tts_info["audio"] = f"narr/{target.name}"
        tts_info["duration"] = duration

    # ── 실측 길이로 자막 시각 계산 ──
    report(0.93, "음성 길이에 맞춰 자막 시각을 계산하고 있습니다…")
    recalculate_timings(data["segments"], default_gap=default_gap)

    report(0.97, "저장하고 있습니다…")
    store.save_project(project_id, data)

    made = sum(1 for s in data["segments"] if (s.get("tts") or {}).get("duration"))
    spoken_time = sum((s.get("tts") or {}).get("duration", 0.0) for s in data["segments"])

    report(1.0, "완료되었습니다.")
    return {
        "segments": data["segments"],
        "count": len(data["segments"]),
        "voiced": made,
        "total_seconds": round(spoken_time, 2),
        "end_seconds": round(data["segments"][-1]["end"], 2) if data["segments"] else 0.0,
    }


def build_full_narration(
    report: Reporter,
    *,
    project_id: str,
    script: str | None = None,
    only_segment_id: str | None = None,
) -> dict[str, Any]:
    """문장별 음성을 만들고 → 하나로 이어 붙이고 → 자막 시각을 확정한다.

    타이밍을 두 번 계산하지 않는다. 이어 붙인 결과 파일에서 각 문장이 실제로 몇 초에
    시작하는지를 받아 그대로 자막 시각으로 쓴다. 계산값이 아니라 결과물 기준이므로
    소리와 자막이 어긋날 여지가 없다.
    """
    from app.core import audio_mix
    from app.core import projects as store

    # 1) 문장별 음성 만들기 (여기서 진행률의 앞 80%를 쓴다)
    def stage_one(progress: float, message: str | None = None) -> None:
        report(progress * 0.8, message)

    generate_narration(
        stage_one, project_id=project_id, script=script, only_segment_id=only_segment_id
    )

    # 2) 하나로 이어 붙이기
    report(0.82, "문장들을 하나의 나레이션으로 이어 붙이고 있습니다…")
    clips = narration_clips(project_id)
    if not clips:
        raise NarrationError("만들어진 나레이션 음성이 없습니다.")

    pdir = store.project_dir(project_id)
    out_path = pdir / "narr" / "나레이션_전체.mp3"

    def stage_two(progress: float, message: str | None = None) -> None:
        report(0.82 + progress * 0.15, message)

    joined = audio_mix.concat_narration(stage_two, clips=clips, out_path=out_path)

    # 3) 이어 붙인 파일에서 각 문장의 실제 위치를 받아 자막 시각으로 확정한다
    report(0.98, "자막 시각을 확정하고 있습니다…")
    data = store.load_project(project_id)
    by_id = {part_id: part for part_id, part in zip(
        [c["id"] for c in clips], joined.get("parts", [])
    )}

    for segment in data.get("segments") or []:
        part = by_id.get(segment.get("id"))
        if part:
            segment["start"] = round(float(part["start"]), 3)
            segment["end"] = round(float(part["end"]), 3)

    data.setdefault("narration", {})["audio"] = f"narr/{out_path.name}"
    data["narration"]["audio_duration"] = joined.get("duration")
    store.save_project(project_id, data)

    report(1.0, "완료되었습니다.")
    return {
        "segments": data.get("segments", []),
        "count": len(data.get("segments", [])),
        "audio": f"narr/{out_path.name}",
        "duration": joined.get("duration"),
        "error_ms": joined.get("error_ms"),
    }


def narration_clips(project_id: str) -> list[dict[str, Any]]:
    """이어 붙이기용 목록 — 만들어진 문장 음성 파일과 각 문장 뒤의 쉼."""
    from app.core import projects as store

    data = store.load_project(project_id)
    narration = data.get("narration") or {}
    default_gap = float(narration.get("gap", 0.3))
    pdir = store.project_dir(project_id)

    clips: list[dict[str, Any]] = []
    for segment in data.get("segments") or []:
        tts_info = segment.get("tts") or {}
        rel = tts_info.get("audio")
        if not rel:
            continue
        path = pdir / rel
        if not path.is_file():
            continue
        gap = tts_info.get("gap")
        clips.append(
            {
                "path": str(path),
                "gap_after": float(default_gap if gap is None else gap),
                "id": segment["id"],
            }
        )
    return clips
