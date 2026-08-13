"""사진 여러 장을 영상으로 만든다 (Phase 6).

## 왜 두 단계인가 — 이 파일에서 가장 중요한 것

사진을 그냥 이어붙이면 **오류 없이 틀린 영상**이 나온다. 조사(docs/RESEARCH 2.1절)에서
실제로 확인한 것:

  · 1920×1080 빨강 3초 → 800×1200 초록 2초 → 640×480 파랑 4초 를 이어붙였더니
    길이 8초짜리 영상이 나왔고, 1초·4초·7초 지점의 색이 **셋 다 파랑**이었다.
    빨강과 초록은 한 프레임도 들어가지 않았다. **종료 코드는 0, 경고도 없었다.**
  · jpg 와 png 를 섞으면 첫 파일로 고른 해독기가 나머지를 못 읽는다. 역시 종료 코드 0.

그래서 반드시 **① 사진마다 크기를 똑같이 맞춘 뒤 ② 이어붙인다.**
정규화가 형식 차이(jpg·png·webp)까지 흡수하므로 섞임 문제도 함께 사라진다.

사진마다 입력을 여는 방법(-loop 1 + concat 필터)은 3장이면 완벽하지만 60장에서
메모리 부족으로 죽는다(조사 2.2절 실측). 그래서 처음부터 이 방법으로 간다.

## 정규화한 사진은 어디에 두는가

프로젝트 폴더 안 `cache/` 에 남긴다. 원본 사진과 화면비 설정이 그대로면 다시 만들지
않으므로 두 번째 내보내기가 빨라진다. 프로젝트를 지울 때 함께 지워진다.
"""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.core import framing, style_map
from app.core.ffmpeg import (
    RenderError,
    Reporter,
    _noop,
    _require,
    _run_with_progress,
    _unique_out_path,
    burn_subtitles,
)

CACHE_DIR = "cache"

# 사진 영상의 프레임률. 사진은 움직이지 않으므로 높일 이유가 없고,
# 30이면 어떤 재생기에서도 문제가 없다.
FPS = 30


def _round3(value: float) -> float:
    """0.5를 항상 위로 올리는 소수 셋째 자리 반올림.

    화면(app.js)이 이 계산을 그대로 갖고 있다. 미리보기에 보이는 사진과 내보낸
    영상의 사진이 어긋나면 안 되므로 규칙을 하나로 못 박는다. 파이썬 기본 round()
    는 0.5를 짝수 쪽으로 보내고 자바스크립트 Math.round 는 언제나 위로 올린다
    (framing._round 와 같은 이유).
    """
    return math.floor(value * 1000 + 0.5) / 1000


def cache_dir(project_dir: Path) -> Path:
    path = Path(project_dir) / CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def canvas_of(data: dict[str, Any]) -> dict[str, int]:
    """이 프로젝트의 사진들이 들어갈 화면 크기.

    화면비를 바꾸면 캔버스도 따라 바뀌어야 한다. 저장된 값을 그대로 믿지 않고
    **지금 고른 화면비에서 다시 계산한다.** 그래야 화면비를 바꾼 뒤 내보낸
    영상이 미리보기와 어긋나지 않는다.
    """
    conf = framing.normalize(data.get("output"))
    aspect = conf["aspect"]
    if aspect == "source":
        # 사진 프로젝트에서 "원본 그대로"는 뜻이 없다(원본이 여럿이다).
        # 저장해 둔 캔버스가 있으면 그것을 쓰고, 없으면 기본 화면비로 받는다.
        saved = data.get("canvas") or {}
        if int(saved.get("width") or 0) > 0 and int(saved.get("height") or 0) > 0:
            return {"width": int(saved["width"]), "height": int(saved["height"])}
        aspect = framing.DEFAULT_CANVAS_ASPECT
    width, height = framing.canvas_size(aspect)
    return {"width": width, "height": height}


def resolve_durations(data: dict[str, Any]) -> list[dict[str, Any]]:
    """사진 목록을 "몇 초씩 보인다"로 확정한다.

    사진은 두 가지 방식으로 시간이 정해진다.
      · seg_id 가 없으면 → 저장된 duration 초 동안 보인다
      · seg_id 가 있으면 → 짝지어진 자막(가사)이 시작할 때 나타나 다음 사진이
        나올 때까지 보인다

    여기서 seg_id 를 duration 으로 **바꿔 놓기 때문에** 영상을 만드는 쪽
    (build_slideshow)은 seg_id 를 전혀 몰라도 된다. 사진 영상과 음원 영상이
    같은 코드로 만들어지는 것이 이 함수 덕분이다.

    첫 가사가 3초에 시작하면 0~3초에 보일 것이 없다. 그럴 때는 **첫 사진을
    0초부터** 보이게 한다 (가장 덜 놀랍다).
    """
    images = data.get("images") or []
    if not images:
        return []

    segments = data.get("segments") or []
    starts = {str(seg.get("id")): float(seg.get("start") or 0.0) for seg in segments}
    if not any(str(img.get("seg_id") or "") in starts for img in images):
        # 짝지은 것이 하나도 없으면 저장된 시간 그대로 쓴다 (그냥 사진 영상).
        return [dict(img) for img in images]

    last_end = max((float(seg.get("end") or 0.0) for seg in segments), default=0.0)

    # ① 사진마다 "언제 나타나는가"를 정한다.
    #    짝지은 사진은 그 자막의 시작 시각, 짝 없는 사진은 앞 사진이 끝나는 시각.
    timed: list[tuple[float, int, dict[str, Any]]] = []
    clock = 0.0
    for index, image in enumerate(images):
        item = dict(image)
        seg_id = str(item.get("seg_id") or "")
        if seg_id in starts:
            clock = starts[seg_id]
        timed.append((clock, index, item))
        clock += max(0.05, float(item.get("duration") or 0.05))

    # ② 시각 순으로 줄 세운다. 화면에서 짝을 거꾸로 지어도 영상은 시간 순으로 나온다.
    #    (그냥 두면 표시 시간이 음수가 되어 사진이 한 번 번쩍이고 만다 — 조용한 실패다)
    timed.sort(key=lambda row: (row[0], row[1]))

    # ③ 이웃한 사진 사이의 간격이 곧 표시 시간이다.
    resolved: list[dict[str, Any]] = []
    for order, (start, _index, item) in enumerate(timed):
        if order + 1 < len(timed):
            next_start = timed[order + 1][0]
        else:
            # 마지막 사진은 마지막 자막이 끝날 때까지 (음원이 있으면 -shortest 가 잘라 준다)
            next_start = max(last_end, start + max(0.05, float(item.get("duration") or 0.05)))
        item["duration"] = max(0.05, _round3(next_start - start))
        resolved.append(item)

    # ④ 첫 가사가 0초가 아니면 그 앞이 비어 버린다. 첫 사진을 0초부터 보이게 한다.
    if resolved and timed[0][0] > 0.001:
        resolved[0]["duration"] = _round3(float(resolved[0]["duration"]) + timed[0][0])

    return resolved


def _fingerprint(src: Path, canvas_w: int, canvas_h: int, output: dict[str, Any]) -> str:
    """이 사진을 이 설정으로 이미 정규화해 두었는지 알아보는 지문.

    원본이 바뀌면(수정 시각·크기) 다시 만들어야 하고, 화면비나 잘라낼 자리를 바꿔도
    다시 만들어야 한다. 둘 다 지문에 넣는다.
    """
    try:
        stat = src.stat()
        stamp = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        stamp = "0:0"
    key = "|".join(
        [
            str(src).lower(), stamp, str(canvas_w), str(canvas_h),
            output["fit"], f"{output['focus_x']:.2f}", f"{output['focus_y']:.2f}",
            "blur" if output["pad_blur"] else "black",
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_images(
    report: Reporter,
    *,
    images: list[dict[str, Any]],
    canvas_w: int,
    canvas_h: int,
    output: dict[str, Any],
    work_dir: Path,
    base: float = 0.0,
    span: float = 0.2,
) -> list[Path]:
    """사진들을 전부 같은 크기의 jpg 로 다시 저장하고 그 경로들을 돌려준다.

    파일 이름은 `norm_0001_<지문>.jpg` 처럼 **순번을 앞에 둔다.** 이어붙이기 목록을
    사람이 열어 봤을 때 순서가 눈에 보여야 하기 때문이다.
    """
    _require("ffmpeg")
    vfilter = framing.fit_filter(canvas_w, canvas_h, output)
    made: list[Path] = []

    for index, image in enumerate(images):
        src = Path(image["path"])
        if not src.is_file():
            raise RenderError(
                f"사진 파일을 찾을 수 없습니다: {src.name}\n"
                "옮기거나 지우셨나요? 사진 목록에서 빼고 다시 시도해 주세요."
            )

        target = work_dir / f"norm_{index + 1:04d}_{_fingerprint(src, canvas_w, canvas_h, output)}.jpg"
        if not target.is_file():
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(src),
                "-vf", vfilter,
                "-frames:v", "1",
                "-q:v", "2",          # jpg 품질 (2가 거의 무손실, 31이 최저)
                str(target),
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
            )
            if result.returncode != 0 or not target.is_file():
                detail = (result.stderr or "").strip().splitlines()
                tail = " / ".join(detail[-2:])[:200] if detail else f"오류 코드 {result.returncode}"
                raise RenderError(f"사진을 준비하지 못했습니다 ({src.name}): {tail}")

        made.append(target)
        report(
            base + span * (index + 1) / max(1, len(images)),
            f"사진을 준비하고 있습니다 ({index + 1} / {len(images)}장)",
        )

    # 이번에 쓰지 않은 옛 정규화 파일은 지운다. 화면비를 여러 번 바꾸면 계속 쌓인다.
    keep = {p.name for p in made}
    for old in work_dir.glob("norm_*.jpg"):
        if old.name not in keep:
            old.unlink(missing_ok=True)

    return made


def write_concat_list(paths: list[Path], durations: list[float], list_path: Path) -> float:
    """이어붙이기 목록 파일을 쓰고 의도한 전체 길이(초)를 돌려준다.

    두 가지 함정이 있다.

    1. concat 데먹서는 **마지막 항목의 duration 을 무시한다.** 그래서 마지막 파일을
       한 번 더 적어 주는 것이 관행인데, 그러면 이번에는 결과가 한 장 길이만큼
       **길어진다** (조사 2.4절 실측: 기대 120초 / 실제 122초).
       → 마지막 줄을 되풀이해 적되, 부르는 쪽에서 `-t` 로 전체 길이를 못 박는다.
    2. 목록 안의 경로에 작은따옴표나 쉼표가 들어가면 깨진다.
       → 파일 이름만 적고 FFmpeg 을 이 폴더에서 실행한다(cwd). 이름은 우리가 지었다.
    """
    lines: list[str] = []
    total = 0.0
    for path, seconds in zip(paths, durations):
        lines.append(f"file '{path.name}'")
        lines.append(f"duration {max(0.05, float(seconds)):.3f}")
        total += max(0.05, float(seconds))
    if paths:
        lines.append(f"file '{paths[-1].name}'")  # 마지막 장이 제 시간만큼 보이도록

    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return round(total, 3)


def build_slideshow(
    report: Reporter | None = None,
    *,
    project_dir: str | Path,
    images: list[dict[str, Any]],
    canvas: dict[str, Any],
    output: dict[str, Any] | None = None,
    out_dir: str | Path,
    out_name: str = "사진영상.mp4",
    segments: list[dict[str, Any]] | None = None,
    style: dict[str, Any] | None = None,
    audio_path: str | Path | None = None,
    seconds: float | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    """사진 목록으로 mp4 를 만든다. 자막과 음원은 있으면 함께 넣는다.

    인자:
        images   [{"path":..., "duration":...}, ...] — 순서가 곧 나오는 순서
        canvas   {"width":1080, "height":1920} — 사진들이 들어갈 화면 크기
        output   화면비 설정 (framing 형식). 잘라내기/여백 채우기와 잘라낼 자리를 정한다
        segments 자막 (없으면 자막 없는 영상)
        audio_path 음원 (있으면 소리를 넣고 음원 길이에 맞춘다)
        seconds  앞부분 몇 초만 만들지 (미리보기용)

    돌려주는 값은 burn_subtitles() 와 같은 모양이라 화면 코드가 갈래를 안 나눠도 된다.
    """
    report = report or _noop
    _require("ffmpeg")

    if not images:
        raise RenderError("사진이 한 장도 없습니다. 먼저 사진을 넣어 주세요.")

    canvas_w = int((canvas or {}).get("width") or 0)
    canvas_h = int((canvas or {}).get("height") or 0)
    if canvas_w <= 0 or canvas_h <= 0:
        raise RenderError("사진이 들어갈 화면 크기가 정해지지 않았습니다.")

    conf = framing.normalize(output)
    work = cache_dir(Path(project_dir))
    out_folder = Path(out_dir)
    final_path = _unique_out_path(out_folder, out_name)

    report(0.01, "사진을 확인하고 있습니다…")
    normalized = normalize_images(
        report,
        images=images,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        output=conf,
        work_dir=work,
        base=0.02,
        span=0.18,
    )

    durations = [max(0.05, float(img.get("duration") or 0)) for img in images]

    audio = Path(audio_path) if audio_path else None
    if audio and not audio.is_file():
        raise RenderError(f"음원 파일을 찾을 수 없습니다: {audio.name}")

    target_duration = round(sum(durations), 3)
    if audio:
        from app.core.ffprobe import ProbeError, measure_duration

        try:
            song = measure_duration(audio)
        except ProbeError as exc:
            raise RenderError(str(exc)) from exc
        # 영상 길이는 **음원 길이에 맞춘다.** 사진이 모자라면 마지막 장이 그만큼 더
        # 보이고, 남으면 뒤가 잘린다. 어느 쪽인지는 내보내기 전에 화면에서 알려 준다.
        if sum(durations) < song:
            durations[-1] += song - sum(durations)
        target_duration = round(song, 3)

    list_path = work / "concat_list.txt"
    write_concat_list(normalized, durations, list_path)

    if seconds:
        target_duration = min(target_duration, float(seconds))

    started = time.monotonic()

    # ── 자막이 없으면 한 번에 끝난다 ───────────────────────────
    if not segments:
        tmp_path = out_folder / f".{final_path.stem}.tmp{final_path.suffix}"
        tmp_path.unlink(missing_ok=True)
        try:
            _encode_concat(
                report, work=work, list_name=list_path.name, audio=audio,
                target_duration=target_duration, fast=fast, out_path=tmp_path,
                base=0.25, span=0.72,
            )
            os.replace(tmp_path, final_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        report(1.0, f"완성했습니다: {final_path.name}")
        return {
            "path": str(final_path),
            "filename": final_path.name,
            "duration": _round3(target_duration),
            "elapsed": round(time.monotonic() - started, 2),
            "width": canvas_w, "height": canvas_h,
            "source_width": canvas_w, "source_height": canvas_h,
            "image_count": len(images),
            "ass": None,
            "framing": {"aspect": conf["aspect"], "fit": conf["fit"], "changed": True},
        }

    # ── 자막이 있으면 **두 번에 나눠** 만든다 ──────────────────
    #
    # 왜 한 번에 못 하는가 (실험으로 확인한 것):
    #   사진 한 장은 프레임이 하나뿐이라, 필터그래프가 보는 순간이 0초·3초·6초… 뿐이다.
    #   그 사이에 걸린 자막은 **그려질 기회가 아예 없어** 자막이 한 글자도 안 들어간다.
    #   그렇다고 `fps` 필터로 프레임을 촘촘히 만들면 이번에는 **사진 순서가 망가진다**
    #   (t=1초·4초·7초가 전부 3번째 사진이 되었다. start_time=0 을 줘도 마찬가지였다).
    #   둘 다 오류 없이 조용히 틀린다.
    #
    # 그래서 ① 사진만으로 30프레임짜리 영상을 먼저 만들고
    #        ② 그 영상에 **이미 검증된 자막 번인 코드**를 그대로 쓴다.
    # 한 번 더 인코딩하는 값을 치르지만, 자막 위치·글꼴·경로 처리를 다시 만들지 않는다.
    stage = work / "slides_stage.mp4"
    stage.unlink(missing_ok=True)
    try:
        _encode_concat(
            report, work=work, list_name=list_path.name, audio=audio,
            target_duration=target_duration, fast=fast, out_path=stage,
            base=0.22, span=0.38,
        )

        def _later(fraction: float, message: str) -> None:
            """두 번째 단계의 진행률을 뒤쪽 구간(0.60~1.00)에 옮겨 놓는다."""
            report(0.60 + 0.40 * max(0.0, min(1.0, fraction)), message)

        result = burn_subtitles(
            _later,
            video_path=stage,
            segments=segments,
            style=style_map.normalize(style),
            out_dir=out_folder,
            out_name=out_name,
            fast=fast,
            output=None,   # 이미 캔버스 크기다. 여기서 또 자르면 두 번 잘린다.
        )
    finally:
        stage.unlink(missing_ok=True)

    result["elapsed"] = round(time.monotonic() - started, 2)
    result["image_count"] = len(images)
    result["framing"] = {"aspect": conf["aspect"], "fit": conf["fit"], "changed": True}
    report(1.0, f"완성했습니다: {result['filename']}")
    return result


def _encode_concat(
    report: Reporter,
    *,
    work: Path,
    list_name: str,
    audio: Path | None,
    target_duration: float,
    fast: bool,
    out_path: Path,
    base: float,
    span: float,
) -> None:
    """이어붙이기 목록으로 영상 하나를 만든다 (자막 없음).

    프레임률은 **필터가 아니라 출력 옵션 `-r` 로** 정한다. `fps` 필터를 쓰면
    사진 순서가 망가진다 (memory/fps-filter-eats-the-first-images.md).
    길이는 `-t` 로 못 박는다 — 이어붙이기 목록은 마지막 장이 제 시간만큼 보이도록
    마지막 줄을 되풀이해 적는데, 그러면 결과가 한 장 길이만큼 길어지기 때문이다.
    """
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "concat", "-safe", "0", "-i", list_name,
    ]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-vf", "format=yuv420p"]
    if audio:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-t", f"{target_duration:.3f}",
        "-r", str(FPS),
        "-fps_mode", "cfr",
        "-c:v", "libx264",
        "-crf", "23" if fast else "20",
        "-preset", "veryfast" if fast else "medium",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(out_path),
    ]

    def _scaled(fraction: float, message: str) -> None:
        report(base + span * max(0.0, min(1.0, fraction)), message)

    _run_with_progress(
        cmd, target_duration, _scaled, "사진을 이어 붙이고 있습니다", base=0.0, cwd=str(work)
    )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RenderError("영상이 만들어지지 않았습니다. 사진 파일을 확인해 주세요.")
