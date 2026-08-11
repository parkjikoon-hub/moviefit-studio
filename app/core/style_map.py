"""자막 스타일의 단일 출처 (TECH_SPEC 3절 R5).

브라우저 미리보기(CSS)와 영상에 새겨 넣는 결과(ASS)가 어긋나지 않으려면
스타일 해석이 한 곳에만 있어야 한다. 그 한 곳이 이 파일이다.

- DEFAULT_STYLE : 스타일의 기본값이자 사실상의 스키마
- PRESETS       : 프리셋 5종 (F-31)
- to_css()      : 브라우저 오버레이용 CSS 속성
- to_ass_style(): FFmpeg 번인용 ASS 스타일 한 줄
"""

from __future__ import annotations

import copy
from typing import Any

# ── 기본 스타일 ────────────────────────────────────────────
# position.mode 가 "preset"이면 상/중/하 규칙을 따르고,
# "custom"이면 사용자가 마우스로 끌어 둔 x,y(화면 대비 %)를 그대로 쓴다.
DEFAULT_STYLE: dict[str, Any] = {
    "preset": "basic",
    "font": "Pretendard",
    "size": 42,
    "bold": True,
    "italic": False,
    "color": "#FFFFFF",
    "outline": {"color": "#000000", "width": 2.0},
    "shadow": {"enabled": True, "depth": 1.5},
    "bg": {"enabled": False, "color": "#000000", "opacity": 0.55},
    "align": "center",  # left | center | right
    "position": {"mode": "preset", "preset": "bottom", "x": 50.0, "y": 88.0},
    "letter_spacing": 0.0,
    "line_height": 1.3,
    "max_chars": 20,  # 한 줄 최대 글자수 (F-11)
    "max_lines": 2,
}

# 위치 프리셋 → 화면 세로 위치(%) . x는 정렬에 따라 결정된다.
POSITION_PRESET_Y = {"top": 12.0, "middle": 50.0, "bottom": 88.0}


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """중첩 사전을 깊게 합친다 (patch가 이긴다)."""
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ── 프리셋 5종 (F-31) ──────────────────────────────────────
PRESETS: dict[str, dict[str, Any]] = {
    "basic": {
        "label": "기본",
        "desc": "흰 글자에 검은 외곽선. 어떤 영상에도 무난합니다.",
        "style": {},  # DEFAULT_STYLE 그대로
    },
    "variety": {
        "label": "예능",
        "desc": "굵고 큰 노란 글자. 유튜브 예능 자막 느낌입니다.",
        "style": {
            "font": "Pretendard",
            "size": 54,
            "bold": True,
            "color": "#FFE23D",
            "outline": {"color": "#1A1A1A", "width": 4.0},
            "shadow": {"enabled": True, "depth": 2.5},
        },
    },
    "news": {
        "label": "뉴스",
        "desc": "화면 아래 반투명 검은 띠 위에 흰 글자.",
        "style": {
            "size": 38,
            "bold": False,
            "color": "#FFFFFF",
            "outline": {"color": "#000000", "width": 0.0},
            "shadow": {"enabled": False, "depth": 0.0},
            "bg": {"enabled": True, "color": "#000000", "opacity": 0.72},
            "position": {"mode": "preset", "preset": "bottom", "y": 90.0},
        },
    },
    "minimal": {
        "label": "미니멀",
        "desc": "얇고 담백한 흰 글자. 다큐멘터리·인터뷰용.",
        "style": {
            "size": 36,
            "bold": False,
            "color": "#F2F2F2",
            "outline": {"color": "#000000", "width": 1.0},
            "shadow": {"enabled": False, "depth": 0.0},
        },
    },
    "accent": {
        "label": "강조",
        "desc": "큼직한 흰 글자에 두꺼운 외곽선. 핵심 문장 강조용.",
        "style": {
            "size": 60,
            "bold": True,
            "color": "#FFFFFF",
            "outline": {"color": "#0F766E", "width": 5.0},
            "shadow": {"enabled": True, "depth": 3.0},
            "position": {"mode": "preset", "preset": "middle", "y": 50.0},
        },
    },
}


def preset_list() -> list[dict[str, Any]]:
    """화면의 프리셋 카드에 뿌릴 목록."""
    return [
        {"key": key, "label": item["label"], "desc": item["desc"], "style": apply_preset(key)}
        for key, item in PRESETS.items()
    ]


def apply_preset(key: str) -> dict[str, Any]:
    """프리셋 이름을 완전한 스타일 사전으로 펼친다."""
    item = PRESETS.get(key)
    if item is None:
        return copy.deepcopy(DEFAULT_STYLE)
    style = _merge(DEFAULT_STYLE, item["style"])
    style["preset"] = key
    return style


def normalize(style: dict[str, Any] | None) -> dict[str, Any]:
    """빠진 항목을 기본값으로 채운다. 저장된 옛 프로젝트를 열 때도 안전해진다."""
    return _merge(DEFAULT_STYLE, style or {})


def resolved_position(style: dict[str, Any]) -> tuple[float, float]:
    """자막 상자의 중심 위치를 화면 대비 %로 돌려준다 (x, y)."""
    pos = style.get("position", {})
    if pos.get("mode") == "custom":
        return float(pos.get("x", 50.0)), float(pos.get("y", 88.0))

    preset = pos.get("preset", "bottom")
    y = POSITION_PRESET_Y.get(preset, 88.0)
    align = style.get("align", "center")
    x = {"left": 20.0, "center": 50.0, "right": 80.0}.get(align, 50.0)
    return x, y


# ── 브라우저 미리보기용 ────────────────────────────────────
def to_css(style: dict[str, Any], video_height_px: int = 720) -> dict[str, str]:
    """오버레이 div에 그대로 넣을 CSS 속성들.

    글자 크기는 '영상 세로 픽셀 기준'으로 정의되어 있으므로,
    실제 화면에 표시되는 영상 높이에 맞춰 비례 축소한다.
    그래야 미리보기와 번인 결과의 글자 비율이 같아진다.
    """
    style = normalize(style)
    scale = video_height_px / 720.0
    size_px = style["size"] * scale

    outline = style["outline"]
    shadow = style["shadow"]

    # 외곽선은 text-shadow를 여덟 방향으로 깔아 흉내 낸다 (브라우저 공통 동작)
    shadows: list[str] = []
    width = outline["width"] * scale
    if width > 0:
        steps = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
        shadows += [f"{dx * width:.2f}px {dy * width:.2f}px 0 {outline['color']}" for dx, dy in steps]
    if shadow["enabled"]:
        depth = shadow["depth"] * scale
        shadows.append(f"{depth:.2f}px {depth:.2f}px {depth * 1.6:.2f}px rgba(0,0,0,.85)")

    css: dict[str, str] = {
        "font-family": f'"{style["font"]}", "Malgun Gothic", sans-serif',
        "font-size": f"{size_px:.1f}px",
        "font-weight": "700" if style["bold"] else "400",
        "font-style": "italic" if style["italic"] else "normal",
        "color": style["color"],
        "text-align": style["align"],
        "letter-spacing": f"{style['letter_spacing'] * scale:.2f}px",
        "line-height": str(style["line_height"]),
        "text-shadow": ", ".join(shadows) if shadows else "none",
    }

    if style["bg"]["enabled"]:
        css["background-color"] = _hex_to_rgba(style["bg"]["color"], style["bg"]["opacity"])
        css["padding"] = f"{0.18 * size_px:.1f}px {0.5 * size_px:.1f}px"
        css["border-radius"] = f"{0.12 * size_px:.1f}px"
    else:
        css["background-color"] = "transparent"
        css["padding"] = "0"

    return css


def _hex_to_rgba(hex_color: str, opacity: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{opacity:.3f})"


# ── FFmpeg 번인용 (ASS) ────────────────────────────────────
def _hex_to_ass(hex_color: str, alpha: float = 0.0) -> str:
    """#RRGGBB → ASS의 &HAABBGGRR 형식. ASS는 색 순서가 거꾸로다.

    alpha는 0(불투명)~1(투명). ASS도 00이 불투명, FF가 투명이다.
    """
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = f"{int(round(alpha * 255)):02X}"
    return f"&H{a}{b}{g}{r}".upper()


# ASS 정렬 번호 (numpad 배치): 1~3 아래, 4~6 가운데, 7~9 위
_ASS_ALIGN = {
    ("bottom", "left"): 1, ("bottom", "center"): 2, ("bottom", "right"): 3,
    ("middle", "left"): 4, ("middle", "center"): 5, ("middle", "right"): 6,
    ("top", "left"): 7,    ("top", "center"): 8,    ("top", "right"): 9,
}


def to_ass_style(
    style: dict[str, Any], video_width: int, video_height: int
) -> tuple[str, str | None]:
    """ASS 스타일 정의 한 줄과, 자유 배치일 때 각 자막 앞에 붙일 위치 태그를 만든다.

    돌려주는 값:
        (Style 줄, pos_tag)
        pos_tag 예: "{\\pos(960,634)}" — 자유 배치가 아니면 None
    """
    style = normalize(style)

    # 글자 크기는 720p 기준으로 정의되어 있으므로 실제 해상도에 비례시킨다
    scale = video_height / 720.0
    size = round(style["size"] * scale)
    outline_w = round(style["outline"]["width"] * scale, 1)
    shadow_d = round(style["shadow"]["depth"] * scale, 1) if style["shadow"]["enabled"] else 0

    primary = _hex_to_ass(style["color"])
    outline_c = _hex_to_ass(style["outline"]["color"])

    if style["bg"]["enabled"]:
        back = _hex_to_ass(style["bg"]["color"], 1.0 - style["bg"]["opacity"])
        border_style = 3  # 3 = 글자 뒤에 불투명 박스
    else:
        back = _hex_to_ass("#000000", 0.0)
        border_style = 1  # 1 = 외곽선 + 그림자

    pos = style["position"]
    align_h = style["align"]
    pos_tag: str | None = None

    if pos.get("mode") == "custom":
        # 자유 배치: 정렬 기준점을 '가운데'로 두고 \pos로 좌표를 직접 준다
        alignment = 5
        x_px = round(video_width * float(pos.get("x", 50.0)) / 100.0)
        y_px = round(video_height * float(pos.get("y", 88.0)) / 100.0)
        pos_tag = f"{{\\pos({x_px},{y_px})}}"
        margin_v = 0
    else:
        preset = pos.get("preset", "bottom")
        alignment = _ASS_ALIGN.get((preset, align_h), 2)
        # 화면 가장자리에서 띄울 여백 (아래/위 프리셋일 때만 의미가 있다)
        y_percent = POSITION_PRESET_Y.get(preset, 88.0)
        if preset == "bottom":
            margin_v = round(video_height * (100.0 - y_percent) / 100.0)
        elif preset == "top":
            margin_v = round(video_height * y_percent / 100.0)
        else:
            margin_v = 0

    margin_h = round(video_width * 0.04)
    spacing = round(style["letter_spacing"] * scale, 1)

    fields = [
        "Default",                      # Name
        style["font"],                  # Fontname
        str(size),                      # Fontsize
        primary,                        # PrimaryColour
        primary,                        # SecondaryColour
        outline_c,                      # OutlineColour
        back,                           # BackColour
        "-1" if style["bold"] else "0",     # Bold  (ASS는 -1이 참)
        "-1" if style["italic"] else "0",   # Italic
        "0", "0",                       # Underline, StrikeOut
        "100", "100",                   # ScaleX, ScaleY
        str(spacing),                   # Spacing
        "0",                            # Angle
        str(border_style),              # BorderStyle
        str(outline_w),                 # Outline
        str(shadow_d),                  # Shadow
        str(alignment),                 # Alignment
        str(margin_h), str(margin_h), str(margin_v),  # MarginL, MarginR, MarginV
        "1",                            # Encoding
    ]
    return "Style: " + ",".join(fields), pos_tag
