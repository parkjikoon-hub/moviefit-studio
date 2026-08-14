"""타임라인에 깔 '영상 띠'(필름스트립)를 만든다.

영상에서 일정 간격으로 화면을 뽑아 **가로로 한 줄 이어붙인 그림 한 장**으로 만든다.
파형(`audio_analysis.waveform`)과 똑같은 방식이다 — 한 번 만들면 프로젝트의
`cache/` 에 저장해 두고, 다음에 열 때는 즉시 쓴다.

왜 낱장이 아니라 한 장으로 이어붙이는가:
    낱장으로 하면 200장이면 요청이 200번이고 FFmpeg도 200번 돌려야 한다.
    한 줄짜리 그림 한 장이면 FFmpeg 한 번, 요청 한 번으로 끝난다.
    화면에서는 그 그림을 타임라인 너비에 맞춰 늘려 깔기만 하면 된다.

시간과 자리의 관계:
    띠는 영상 전체를 고르게 나눠 담는다. 그래서 띠를 타임라인 폭에 꽉 채워 깔면
    "띠의 x 자리 = 그 시각의 화면"이 저절로 맞는다. 낱장마다 정확한 시각을
    따로 기억할 필요가 없다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.ffmpeg import _require
from app.core.ffprobe import ProbeError, measure_duration


class FilmstripError(Exception):
    """영상 띠를 만들지 못했다. 메시지는 사용자에게 그대로 보여줄 한국어여야 한다."""


# 한 칸의 높이(px). 타임라인이 얇으므로 크게 뽑을 이유가 없다.
FRAME_HEIGHT = 40
# 몇 칸으로 나눌지 — 대략 2초에 한 칸, 최소 40칸 최대 300칸.
# 위쪽을 막는 이유: 칸이 늘수록 그림이 가로로 길어진다. 300칸이면 대략 2만 픽셀인데,
# 이보다 길어지면 브라우저가 그림을 통째로 못 그리는 일이 생긴다.
MIN_FRAMES, MAX_FRAMES = 40, 300


def frame_count_for(duration: float) -> int:
    """영상 길이에 맞는 칸 수. 짧은 영상은 촘촘하게, 긴 영상은 위 한도까지만."""
    return max(MIN_FRAMES, min(MAX_FRAMES, int(duration / 2) or MIN_FRAMES))


def _cache_paths(cache_dir: Path, count: int, height: int) -> tuple[Path, Path]:
    stem = f"filmstrip_{count}x{height}"
    return cache_dir / f"{stem}.jpg", cache_dir / f"{stem}.json"


def _read_cache(meta_path: Path, image_path: Path, source: Path) -> dict[str, Any] | None:
    """원본 영상의 크기·수정 시각이 그대로면 만들어 둔 띠를 다시 쓴다."""
    if not (meta_path.is_file() and image_path.is_file()):
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    stat = source.stat()
    if (
        int(data.get("source_size", -1)) != stat.st_size
        or abs(float(data.get("source_mtime", -1)) - stat.st_mtime) > 0.001
    ):
        return None
    return data


def build(
    video_path: str | Path,
    cache_dir: str | Path,
    count: int | None = None,
    height: int = FRAME_HEIGHT,
) -> dict[str, Any]:
    """영상 띠를 만들어(또는 캐시에서 꺼내) 그림 경로와 정보를 돌려준다.

    반환: {"path", "count", "height", "duration", "cached"}
    """
    _require("ffmpeg")

    source = Path(video_path)
    if not source.is_file():
        raise FilmstripError(f"영상 파일이 없습니다: {source}")

    try:
        duration = measure_duration(source)
    except ProbeError as exc:
        raise FilmstripError(str(exc)) from exc
    if duration <= 0:
        raise FilmstripError("영상 길이를 읽지 못했습니다. 파일이 손상되었을 수 있습니다.")

    frames = count or frame_count_for(duration)
    cache = Path(cache_dir)
    image_path, meta_path = _cache_paths(cache, frames, height)

    hit = _read_cache(meta_path, image_path, source)
    if hit is not None:
        return {
            "path": image_path,
            "count": int(hit["count"]),
            "height": int(hit["height"]),
            "duration": float(hit["duration"]),
            "cached": True,
        }

    cache.mkdir(parents=True, exist_ok=True)
    # 임시 이름도 **.jpg 로 끝나야 한다.** FFmpeg 은 확장자를 보고 저장 형식을 정하는데,
    # `.jpg.tmp` 처럼 두면 "무슨 형식인지 모르겠다"며 실패한다.
    tmp = image_path.with_name(image_path.stem + ".tmp.jpg")
    tmp.unlink(missing_ok=True)

    # fps 를 '길이 나누기 칸수'로 주면 영상 전체에서 고르게 뽑힌다.
    # 마지막 칸이 모자라 tile 이 못 채우는 일을 막으려고 아주 조금 촘촘하게 뽑는다
    # (넘치는 프레임은 tile 이 알아서 버린다).
    fps = frames / max(0.001, duration * 0.985)

    # scale 의 -2 는 "높이에 맞추되 너비는 짝수로" 라는 뜻이다. 홀수 너비가 나오면
    # 칸마다 너비가 1px 씩 달라져 띠가 미세하게 어긋난다.
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source),
        "-vf", f"fps={fps:.6f},scale=-2:{height},tile={frames}x1",
        "-frames:v", "1",
        "-q:v", "5",
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        message = (result.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise FilmstripError(f"영상 띠를 만들지 못했습니다: {message}")

    tmp.replace(image_path)  # 쓰다가 죽어도 반쯤 쓴 그림이 남지 않도록 교체 방식

    stat = source.stat()
    meta_path.write_text(
        json.dumps({
            "count": frames,
            "height": height,
            "duration": duration,
            "source_size": stat.st_size,
            "source_mtime": stat.st_mtime,
        }),
        encoding="utf-8",
    )

    return {
        "path": image_path,
        "count": frames,
        "height": height,
        "duration": duration,
        "cached": False,
    }
