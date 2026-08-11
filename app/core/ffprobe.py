"""ffprobe로 미디어 길이를 '실측'한다.

왜 중요한가: 이 프로그램의 킬러 기능(D1)은 나레이션 문장의 실제 길이로 자막 타이밍을
계산하는 것이다. 길이를 추정하면 자막이 밀린다. 그래서 항상 파일을 실제로 재어 본다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class ProbeError(Exception):
    """길이 측정 실패."""


def _run_ffprobe(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        raise ProbeError(
            "ffprobe(길이 측정 도구)를 찾을 수 없습니다. "
            "FFmpeg을 설치해 주세요. PowerShell에서: winget install Gyan.FFmpeg"
        )

    # 인자는 반드시 리스트로 넘긴다 — 한글·공백 경로에서 셸 문자열 조립은 깨진다 (TECH_SPEC R6)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise ProbeError(f"길이를 재지 못했습니다: {(result.stderr or '').strip()[:200]}")

    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ProbeError("길이 정보를 읽지 못했습니다.") from exc

    return round(duration, 3)


def measure_duration(path: str | Path) -> float:
    """파일의 재생 길이(초)."""
    p = Path(path)
    if not p.is_file():
        raise ProbeError(f"파일이 없습니다: {p}")
    return _run_ffprobe(p)


def measure_duration_bytes(data: bytes, suffix: str = ".mp3") -> float:
    """메모리에 있는 오디오의 길이(초). 임시 파일로 잠깐 떨궈서 잰다."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    try:
        return _run_ffprobe(tmp)
    finally:
        tmp.unlink(missing_ok=True)
