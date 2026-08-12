"""로컬 음성인식(STT) 래퍼 — faster-whisper로 영상에서 자막을 뽑아낸다 (F-10).

왜 로컬인가: 클라우드 음성인식은 돈이 들고 영상 원본을 남의 서버에 올려야 한다.
faster-whisper는 내 컴퓨터 안에서만 돌기 때문에 공짜이고 파일이 밖으로 나가지 않는다.

알아 둘 점 (TECH_SPEC 3절 R2·R3, 8절):
- 처음 한 번은 인식 모델을 인터넷에서 내려받는다(small 약 0.5GB, medium 약 1.5GB).
  몇 분 걸릴 수 있으므로 "지금 내려받는 중"이라고 반드시 알려 준다.
- 모델을 메모리에 올리는 데도 수 초가 걸리므로 한 번 올린 모델은 캐시에 두고 재사용한다.
- CPU에서는 느리다. 그래서 항상 백그라운드 작업(jobs.py)으로 돌리고 진행률을 보고한다.

쓰는 법:

    job_id = jobs.submit("stt", "자막 생성", stt.transcribe,
                         media_path="C:/영상/원본.mp4", language="ko", model_size="small")
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from . import subtitles

# 화면에서 고를 수 있는 모델 크기 (PRD F-10)
MODEL_SIZES = ("small", "medium")


class STTError(Exception):
    """음성인식 실패. 메시지는 그대로 사용자에게 보여 줄 한국어 문장이다."""


# ── 모델 캐시 ──────────────────────────────────────────────
# (모델크기, 장치, 연산정밀도) -> 로드된 모델
_models: dict[tuple[str, str, str], Any] = {}
_load_lock = threading.Lock()


def pick_device() -> tuple[str, str]:
    """쓸 수 있는 계산 장치를 고른다. 그래픽카드(CUDA)가 있으면 쓰고, 없으면 CPU.

    CPU에서는 int8(8비트 정수 연산)이 속도와 정확도의 균형이 가장 좋다.
    """
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        # 그래픽카드 확인 자체가 실패해도 문제 없다. 그냥 CPU로 간다.
        pass
    return "cpu", "int8"


def load_model(model_size: str = "small", report: Callable[..., None] | None = None) -> tuple[Any, str]:
    """인식 모델을 준비한다. 이미 올려 둔 모델이 있으면 그대로 재사용한다.

    돌려주는 값: (모델, 장치이름)
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise STTError(
            "음성인식 도구(faster-whisper)가 설치되어 있지 않습니다. "
            "명령창에서 python -m pip install -r requirements.txt 를 실행해 주세요."
        ) from exc

    device, compute_type = pick_device()
    key = (model_size, device, compute_type)

    with _load_lock:
        model = _models.get(key)
        if model is None:
            if report:
                report(
                    0.03,
                    f"음성인식 모델({model_size})을 준비하고 있습니다. "
                    "처음 한 번은 내려받느라 몇 분 걸릴 수 있습니다.",
                )
            try:
                model = WhisperModel(model_size, device=device, compute_type=compute_type)
            except Exception as exc:
                raise STTError(
                    f"음성인식 모델({model_size})을 준비하지 못했습니다. "
                    "처음 실행할 때는 인터넷에서 모델을 내려받아야 합니다. "
                    f"인터넷 연결을 확인한 뒤 다시 시도해 주세요. (원인: {type(exc).__name__}: {exc})"
                ) from exc
            _models[key] = model

    return model, device


def unload_models() -> None:
    """올려 둔 모델을 모두 내려 메모리를 비운다."""
    with _load_lock:
        _models.clear()


# ── 진행률 표시용 시간 표기 ────────────────────────────────
def _fmt(seconds: float, with_minutes: bool) -> str:
    total = max(0, int(seconds))
    if with_minutes:
        return f"{total // 60}분 {total % 60}초"
    return f"{total}초"


# ── 본 작업 ────────────────────────────────────────────────
def transcribe(
    report: Callable[..., None],
    media_path: str | Path,
    language: str | None = "ko",
    model_size: str = "small",
    max_chars: int = 20,
    max_lines: int = 2,
    corrections: list[dict[str, str]] | None = None,
    wav_path: str | Path | None = None,
) -> dict[str, Any]:
    """영상·음성 파일에서 자막 세그먼트를 만들어 낸다 (F-10 + F-11 + F-12).

    첫 번째 인자 report는 jobs.submit이 넣어 주는 진행률 보고 함수다.
    report를 부를 때마다 취소 여부도 함께 확인된다(취소되면 JobCancelled가 올라간다).

    language: "ko" | "en" | None(자동 감지)
    wav_path: 미리 뽑아 둔 wav가 있으면 그 경로. 없으면 원본 파일을 그대로 넘긴다.
              (같은 mp4를 반복해서 푸는 낭비를 줄이기 위한 선택 항목이다.)

    돌려주는 값:
        {"segments": [...], "language": "ko", "duration": 12.3,
         "model": "small", "device": "cpu"}
    """
    source = Path(wav_path) if wav_path else Path(media_path)
    if not source.is_file():
        raise STTError(f"파일을 찾을 수 없습니다: {source}")

    report(0.01, "음성인식을 준비하고 있습니다.")
    model, device = load_model(model_size, report)
    report(0.08, "모델 준비가 끝났습니다. 음성을 읽기 시작합니다.")

    # word_timestamps=True: 단어 하나하나의 시각을 받아 온다. 자막을 문장 단위로
    # 정확히 끊으려면(F-11) 세그먼트 시각만으로는 부족하고 단어 시각이 필요하다.
    # vad_filter=True: 말소리가 없는 구간을 건너뛴다. 무음에서 헛것을 받아쓰는 것을 막고 속도도 빨라진다.
    try:
        segment_iter, info = model.transcribe(
            str(source),
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
        )
    except Exception as exc:
        raise STTError(
            f"음성을 읽지 못했습니다. 파일이 손상되었거나 소리가 없는 형식일 수 있습니다. "
            f"(원인: {type(exc).__name__}: {exc})"
        ) from exc

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    with_minutes = duration >= 60
    total_label = _fmt(duration, with_minutes)

    # transcribe()는 결과를 한꺼번에 주지 않고 하나씩 흘려 준다(제너레이터).
    # 그래서 하나 받을 때마다 "어디까지 왔는지"를 알 수 있다.
    words: list[dict[str, Any]] = []
    for segment in segment_iter:
        for word in segment.words or []:
            words.append(
                {"word": word.word, "start": float(word.start), "end": float(word.end)}
            )
        done = (float(segment.end) / duration) if duration > 0 else 0.0
        # 0.10 ~ 0.95 구간을 인식 진행률에 할당한다 (앞은 모델 준비, 뒤는 문장 나누기)
        report(
            0.10 + 0.85 * min(1.0, max(0.0, done)),
            f"음성을 인식하고 있습니다 ({_fmt(segment.end, with_minutes)} / {total_label})",
        )

    report(0.96, "인식한 말을 자막 문장으로 나누고 있습니다.")
    segments = subtitles.split_into_segments(words, max_chars=max_chars, max_lines=max_lines)
    subtitles.apply_corrections(segments, corrections)

    report(1.0, f"자막 {len(segments)}개를 만들었습니다.")
    return {
        "segments": segments,
        "language": getattr(info, "language", None),
        "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
        "duration": round(duration, 2),
        "model": model_size,
        "device": device,
    }
