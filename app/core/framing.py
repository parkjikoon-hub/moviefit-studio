"""출력 화면비(가로 16:9 / 세로 9:16 / 정사각 1:1) 계산 — 롱폼·숏폼의 단일 출처.

브라우저 미리보기 틀과 실제로 내보내는 영상이 어긋나면 안 된다. 그래서 "원본을
어떤 크기로 잘라 낼 것인가"를 이 파일에서만 계산하고, 화면(app.js)과 렌더링
(ffmpeg.py·audio_mix.py)이 모두 이 결과를 따른다.

두 가지 방식이 있다.

- crop (잘라내기) : 목표 화면비에 맞게 가장자리를 잘라 낸다. 여백이 없어 깔끔하지만
                    화면 밖으로 나가는 내용은 사라진다. 어디를 남길지는 focus_x/focus_y로 정한다.
- pad  (여백 채우기): 원본 전체를 목표 틀 안에 넣고 남는 곳을 채운다. 아무것도 잘리지
                    않지만 가운데 영상이 작아진다. 채우는 색은 흐린 원본(기본) 또는 검정.

주의: 자막을 새길 때 이 필터가 자막 필터보다 **먼저** 와야 하고, 자막 파일(ASS)은
반드시 여기서 나온 **최종 크기**로 만들어야 한다. 원본 크기로 만들면 잘라낸 뒤
글자 크기와 위치가 전부 어긋난다.
"""

from __future__ import annotations

import math
from typing import Any

# 화면비를 바꾸지 않는 기본값. 옛 프로젝트를 열어도 지금까지와 똑같이 동작한다.
DEFAULT_OUTPUT: dict[str, Any] = {
    "aspect": "source",   # "source" | "16:9" | "9:16" | "1:1"
    "fit": "crop",        # "crop"(잘라내기) | "pad"(여백 채우기)
    "focus_x": 50.0,      # 잘라낼 때 남길 가로 중심 (%). 50이면 한가운데
    "focus_y": 50.0,      # 잘라낼 때 남길 세로 중심 (%)
    "pad_blur": True,     # 여백을 흐린 원본으로 채울지 (False면 검정)
}

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
}

ASPECT_LABELS = {
    "source": "원본 그대로",
    "16:9": "가로 16:9",
    "9:16": "세로 9:16",
    "1:1": "정사각 1:1",
}

# 여백을 흐린 원본으로 채울 때의 흐림 정도. 너무 약하면 배경이 눈에 띄어 산만하다.
PAD_BLUR_SIGMA = 22


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round(value: float) -> int:
    """0.5를 항상 위로 올리는 반올림.

    파이썬 기본 round()는 0.5를 짝수 쪽으로 보내는데(607.5→608, 606.5→606) 자바스크립트의
    Math.round는 언제나 위로 올린다(606.5→607). 화면(app.js)이 같은 계산을 갖고 있으므로
    두 곳이 1픽셀이라도 어긋나지 않도록 규칙을 하나로 못 박는다.
    """
    return int(math.floor(value + 0.5))


def _even(value: float) -> int:
    """짝수로 내림. libx264 + yuv420p 는 가로·세로가 홀수면 인코딩을 거부한다."""
    n = _round(value)
    return max(2, n - (n % 2))


def normalize(output: dict[str, Any] | None) -> dict[str, Any]:
    """빠진 값을 기본값으로 채우고 범위를 벗어난 값을 다듬는다.

    사용자가 보내는 값이므로 시스템 경계에서 한 번 걸러 준다.
    """
    src = dict(DEFAULT_OUTPUT)
    src.update(output or {})

    aspect = str(src.get("aspect") or "source")
    if aspect not in ASPECTS and aspect != "source":
        aspect = "source"

    fit = str(src.get("fit") or "crop")
    if fit not in ("crop", "pad"):
        fit = "crop"

    def _pct(key: str) -> float:
        try:
            return round(_clamp(float(src.get(key, 50.0)), 0.0, 100.0), 2)
        except (TypeError, ValueError):
            return 50.0

    return {
        "aspect": aspect,
        "fit": fit,
        "focus_x": _pct("focus_x"),
        "focus_y": _pct("focus_y"),
        "pad_blur": bool(src.get("pad_blur", True)),
    }


def resolve(src_width: int, src_height: int, output: dict[str, Any] | None) -> dict[str, Any]:
    """원본 크기와 설정을 받아 최종 출력 크기와 FFmpeg 필터를 계산한다.

    돌려주는 값:
        width, height : 최종 영상 크기 (짝수)
        filter        : 영상 필터 문자열. 화면비를 바꾸지 않으면 None
        changed       : 화면을 실제로 손대는지 여부
        aspect, fit   : 정리된 설정값 (화면에 되돌려 주기 위해)
        crop          : crop 방식일 때 원본에서 남기는 영역 {x, y, w, h}. 아니면 None
    """
    conf = normalize(output)
    src_w, src_h = int(src_width), int(src_height)
    if src_w <= 0 or src_h <= 0:
        raise ValueError("원본 영상 크기가 올바르지 않습니다.")

    if conf["aspect"] == "source":
        return {
            "width": _even(src_w), "height": _even(src_h),
            "filter": None, "changed": False,
            "aspect": "source", "fit": conf["fit"], "crop": None,
        }

    ratio_w, ratio_h = ASPECTS[conf["aspect"]]
    target_ratio = ratio_w / ratio_h
    source_ratio = src_w / src_h

    if conf["fit"] == "crop":
        # 원본이 목표보다 넓으면 좌우를, 좁으면 위아래를 잘라 낸다.
        if source_ratio > target_ratio:
            crop_h = src_h
            crop_w = src_h * target_ratio
        else:
            crop_w = src_w
            crop_h = src_w / target_ratio

        out_w, out_h = _even(crop_w), _even(crop_h)
        # 남길 자리. focus 가 50이면 한가운데, 0이면 왼쪽/위 끝에 붙는다.
        off_x = _round((src_w - out_w) * conf["focus_x"] / 100.0)
        off_y = _round((src_h - out_h) * conf["focus_y"] / 100.0)
        off_x = int(_clamp(off_x, 0, max(0, src_w - out_w)))
        off_y = int(_clamp(off_y, 0, max(0, src_h - out_h)))

        changed = (out_w, out_h) != (_even(src_w), _even(src_h))
        return {
            "width": out_w, "height": out_h,
            "filter": f"crop={out_w}:{out_h}:{off_x}:{off_y}" if changed else None,
            "changed": changed,
            "aspect": conf["aspect"], "fit": "crop",
            "crop": {"x": off_x, "y": off_y, "w": out_w, "h": out_h},
        }

    # pad — 원본 전체가 들어가도록 틀을 만들고 남는 곳을 채운다 (잘리는 것이 없다).
    #
    # 틀 크기는 **원본의 긴 변**을 새 틀의 긴 변으로 삼아 정한다. 원본을 그대로 두고
    # 틀만 넓히면(1920x1080 → 9:16 이면 1920x3412) 세로가 3천 픽셀이 넘는 괴상한 영상이
    # 나온다. 긴 변을 기준으로 잡으면 1080x1920 — 쇼츠에서 쓰는 바로 그 크기가 된다.
    # 원본은 이 틀 안에 들어가도록 줄어들 뿐이며, 억지로 늘어나는 일은 없다.
    long_side = max(src_w, src_h)
    if target_ratio >= 1.0:
        out_w = _even(long_side)
        out_h = _even(long_side / target_ratio)
    else:
        out_h = _even(long_side)
        out_w = _even(long_side * target_ratio)

    changed = (out_w, out_h) != (_even(src_w), _even(src_h))
    if not changed:
        return {
            "width": out_w, "height": out_h, "filter": None, "changed": False,
            "aspect": conf["aspect"], "fit": "pad", "crop": None,
        }

    if conf["pad_blur"]:
        # 원본을 두 갈래로 나눠, 한쪽은 틀을 꽉 채우도록 키워 흐리게 만들어 배경으로 깔고
        # 다른 한쪽은 잘리지 않게 줄여 그 위에 가운데 정렬로 얹는다.
        filter_str = (
            f"split=2[bg][fg];"
            f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},gblur=sigma={PAD_BLUR_SIGMA}[bgb];"
            f"[fg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        )
    else:
        filter_str = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
        )

    return {
        "width": out_w, "height": out_h, "filter": filter_str, "changed": True,
        "aspect": conf["aspect"], "fit": "pad", "crop": None,
    }


def chain(frame_filter: str | None, *rest: str) -> str:
    """화면비 필터 뒤에 다른 필터(자막 등)를 잇는다. 순서가 중요하다.

    자르기가 먼저, 자막이 나중이어야 한다. 반대로 하면 방금 새긴 자막이 잘려 나간다.
    """
    parts = [p for p in ((frame_filter,) + rest) if p]
    return ",".join(parts)
