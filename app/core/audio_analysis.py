"""오디오 분석 — 자막 타이밍을 '눈으로' 잡기 위한 두 가지 도구.

1) 파형(waveform): 소리의 크기를 구간별로 요약한 숫자 목록. 타임라인 뒤에 깔아 두면
   말이 시작되고 끝나는 지점이 그림으로 보인다.
2) 무음 구간 감지(silencedetect): 문장 사이의 조용한 틈을 찾아, 그 반대인 '말하는 구간'을
   돌려준다. 자막을 손으로 자르지 않고 자연스러운 지점에서 나눌 수 있다.

두 기능 모두 FFmpeg을 subprocess로 호출한다. 인자는 반드시 리스트로 넘긴다 —
한글·공백이 들어간 윈도우 경로에서 셸 문자열 조립은 깨진다 (TECH_SPEC R6).
"""

from __future__ import annotations

import array
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.ffprobe import ProbeError, measure_duration


class AudioAnalysisError(Exception):
    """오디오 분석 실패 (FFmpeg 없음, 소리 없는 파일 등)."""


# 파형용 디코딩 설정 — 그림을 그리는 용도라 8kHz면 충분하다 (파일이 커도 초당 16KB)
SAMPLE_RATE = 8000
MAX_BUCKETS = 8000  # 화면에 그릴 수 있는 한계이자 과도한 요청 방어선
DEFAULT_BUCKETS = 1200
_TIMEOUT = 600  # 긴 영상도 끝까지 훑어야 하므로 넉넉히 (초)


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioAnalysisError(
            "ffmpeg(영상·소리 처리 도구)을 찾을 수 없습니다. "
            "FFmpeg을 설치해 주세요. PowerShell에서: winget install Gyan.FFmpeg"
        )


def _decode_stderr(raw: bytes | None) -> str:
    """FFmpeg의 오류 메시지를 안전하게 문자열로 바꾼다.

    윈도우 콘솔 인코딩(cp949)과 UTF-8이 섞여 나올 수 있어서 깨지는 글자는 버린다.
    """
    return (raw or b"").decode("utf-8", errors="replace")


def _no_audio_hint(stderr: str) -> bool:
    """FFmpeg 오류 메시지가 '오디오 트랙이 없다'는 뜻인지 판별한다."""
    lowered = stderr.lower()
    return (
        "does not contain any stream" in lowered
        or "matches no streams" in lowered
        or "output file is empty" in lowered
    )


def _decode_pcm(path: Path) -> array.array:
    """오디오를 8kHz 모노 16비트 원시 데이터로 디코딩해서 표준출력으로 받는다."""
    _require_ffmpeg()

    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(path),
        "-vn",                       # 영상은 버린다
        "-ac", "1",                  # 모노
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",               # 16비트 정수, 리틀엔디언
        "-",                         # 파일 대신 표준출력으로
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)

    if result.returncode != 0:
        stderr = _decode_stderr(result.stderr).strip()
        if _no_audio_hint(stderr):
            raise AudioAnalysisError(f"이 파일에는 소리(오디오)가 들어 있지 않습니다: {path.name}")
        raise AudioAnalysisError(f"소리를 읽지 못했습니다: {stderr[:200]}")

    raw = result.stdout or b""
    if len(raw) < 2:
        raise AudioAnalysisError(f"이 파일에는 소리(오디오)가 들어 있지 않습니다: {path.name}")

    samples = array.array("h")  # 'h' = 16비트 부호 있는 정수
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])  # 홀수 바이트가 남으면 잘라낸다
    if sys.byteorder == "big":
        samples.byteswap()  # s16le는 리틀엔디언 고정
    return samples


def compute_peaks(media_path: str | Path, buckets: int = DEFAULT_BUCKETS) -> list[float]:
    """파형 값 계산. 구간마다 가장 큰 소리 크기를 0.0~1.0으로 정규화해서 돌려준다."""
    if not isinstance(buckets, int) or buckets < 1 or buckets > MAX_BUCKETS:
        raise AudioAnalysisError(f"파형 구간 수는 1 ~ {MAX_BUCKETS} 사이여야 합니다: {buckets}")

    path = Path(media_path)
    if not path.is_file():
        raise AudioAnalysisError(f"파일이 없습니다: {path}")

    samples = _decode_pcm(path)
    total = len(samples)

    # 구간별 최대 진폭 — 슬라이스 후 max/min을 쓰면 파이썬 반복문 없이 빠르게 계산된다
    raw_peaks: list[int] = []
    for i in range(buckets):
        start = i * total // buckets
        end = (i + 1) * total // buckets
        if end <= start:
            raw_peaks.append(0)  # 샘플보다 구간이 많으면 빈 구간이 생긴다
            continue
        chunk = samples[start:end]
        raw_peaks.append(max(max(chunk), -min(chunk)))

    loudest = max(raw_peaks) if raw_peaks else 0
    if loudest <= 0:
        return [0.0] * buckets  # 완전 무음 파일 — 0으로 나누지 않는다

    return [round(p / loudest, 4) for p in raw_peaks]


def _cache_file(cache_dir: Path, buckets: int) -> Path:
    return Path(cache_dir) / f"waveform_{buckets}.json"


def _read_cache(cache_path: Path, source: Path, buckets: int) -> dict[str, Any] | None:
    """원본 파일의 수정 시각·크기가 그대로면 저장해 둔 파형을 재사용한다."""
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    stat = source.stat()
    if (
        data.get("buckets") != buckets
        or int(data.get("source_size", -1)) != stat.st_size
        or abs(float(data.get("source_mtime", -1)) - stat.st_mtime) > 0.001
        or not isinstance(data.get("peaks"), list)
    ):
        return None
    return data


def waveform(
    media_path: str | Path,
    buckets: int = DEFAULT_BUCKETS,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """파형 데이터를 돌려준다. cache_dir를 주면 JSON으로 저장해 두고 다음부터는 즉시 응답한다.

    반환: {"duration": 초, "buckets": 개수, "peaks": [0.0~1.0 ...], "cached": True/False}
    """
    if not isinstance(buckets, int) or buckets < 1 or buckets > MAX_BUCKETS:
        raise AudioAnalysisError(f"파형 구간 수는 1 ~ {MAX_BUCKETS} 사이여야 합니다: {buckets}")

    path = Path(media_path)
    if not path.is_file():
        raise AudioAnalysisError(f"파일이 없습니다: {path}")

    cache_path = _cache_file(Path(cache_dir), buckets) if cache_dir else None
    if cache_path is not None:
        cached = _read_cache(cache_path, path, buckets)
        if cached is not None:
            return {
                "duration": float(cached["duration"]),
                "buckets": buckets,
                "peaks": cached["peaks"],
                "cached": True,
            }

    peaks = compute_peaks(path, buckets)
    duration = measure_duration(path)  # 길이는 항상 실측한다 (ffprobe.py 재사용)

    if cache_path is not None:
        stat = path.stat()
        payload = {
            "buckets": buckets,
            "duration": duration,
            "source_size": stat.st_size,
            "source_mtime": stat.st_mtime,
            "peaks": peaks,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(cache_path)  # 쓰다가 죽어도 반쯤 쓴 캐시가 남지 않도록 교체 방식

    return {"duration": duration, "buckets": buckets, "peaks": peaks, "cached": False}


# silencedetect는 결과를 표준출력이 아니라 표준오류로 찍는다 (FFmpeg 로그의 일부이기 때문)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def _detect_silences(path: Path, noise_db: float, min_silence: float) -> list[tuple[float, float]]:
    """무음 구간 목록 [(시작초, 끝초), ...]. 끝을 못 찾은 무음은 -1로 표시해 둔다."""
    _require_ffmpeg()

    cmd = [
        "ffmpeg", "-v", "info",
        "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",           # 결과 파일은 만들지 않고 분석만 한다
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    stderr = _decode_stderr(result.stderr)

    if result.returncode != 0:
        if _no_audio_hint(stderr):
            raise AudioAnalysisError(f"이 파일에는 소리(오디오)가 들어 있지 않습니다: {path.name}")
        raise AudioAnalysisError(f"무음 구간을 찾지 못했습니다: {stderr.strip()[-200:]}")

    silences: list[tuple[float, float]] = []
    pending: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            pending = max(0.0, float(start_match.group(1)))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and pending is not None:
            silences.append((pending, float(end_match.group(1))))
            pending = None
    if pending is not None:
        silences.append((pending, -1.0))  # 파일 끝까지 조용한 경우
    return silences


def detect_speech_regions(
    media_path: str | Path,
    noise_db: float = -35.0,
    min_silence: float = 0.35,
    min_speech: float = 0.3,
) -> list[dict[str, float]]:
    """말하는 구간 목록 [{"start": 초, "end": 초}, ...].

    무음 구간을 찾아 그 '반대'를 계산한다. min_speech보다 짧은 조각은 잡음으로 보고 버린다.
    """
    path = Path(media_path)
    if not path.is_file():
        raise AudioAnalysisError(f"파일이 없습니다: {path}")

    duration = measure_duration(path)  # 전체 길이 (ffprobe.py 재사용)
    silences = _detect_silences(path, noise_db, min_silence)

    regions: list[dict[str, float]] = []
    cursor = 0.0
    for sil_start, sil_end in silences:
        sil_start = min(sil_start, duration)
        if sil_start > cursor:
            regions.append({"start": round(cursor, 3), "end": round(sil_start, 3)})
        if sil_end < 0:
            cursor = duration  # 파일 끝까지 무음
            break
        cursor = max(cursor, min(sil_end, duration))
    if cursor < duration:
        regions.append({"start": round(cursor, 3), "end": round(duration, 3)})

    return [r for r in regions if r["end"] - r["start"] >= min_speech]


__all__ = [
    "AudioAnalysisError",
    "ProbeError",
    "MAX_BUCKETS",
    "DEFAULT_BUCKETS",
    "compute_peaks",
    "waveform",
    "detect_speech_regions",
]
