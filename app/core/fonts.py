"""자막에 쓸 수 있는 글꼴 목록.

번들 폰트(assets/fonts/)를 먼저 보여주고, 그다음 윈도우에 설치된 한글 글꼴을 보여준다.
번들 폰트를 앞세우는 이유: 영상에 자막을 새겨 넣을 때 FFmpeg이 확실히 찾을 수 있어
글자가 네모(□)로 깨지지 않기 때문이다 (TECH_SPEC R4).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import FONTS_DIR

# 윈도우에 기본으로 있거나 널리 깔려 있는 한글 글꼴.
# (설치 여부는 아래에서 실제 파일 존재로 확인한다)
KNOWN_KOREAN_FONTS: list[tuple[str, str]] = [
    ("Malgun Gothic", "malgun.ttf"),
    ("Malgun Gothic Bold", "malgunbd.ttf"),
    ("NanumGothic", "NanumGothic.ttf"),
    ("NanumBarunGothic", "NanumBarunGothic.ttf"),
    ("NanumMyeongjo", "NanumMyeongjo.ttf"),
    ("NanumSquare", "NanumSquareR.ttf"),
    ("Gulim", "gulim.ttc"),
    ("Batang", "batang.ttc"),
    ("Dotum", "dotum.ttc"),
    ("Gungsuh", "batang.ttc"),
    ("HY헤드라인M", "H2HDRM.TTF"),
]


def _windows_font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        import os

        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:  # 사용자가 자기 계정에만 설치한 폰트
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def list_fonts() -> list[dict[str, Any]]:
    """화면의 글꼴 선택 목록에 뿌릴 자료."""
    fonts: list[dict[str, Any]] = []

    # 1) 번들 폰트 — 번인이 가장 확실하다
    if FONTS_DIR.is_dir():
        for path in sorted(FONTS_DIR.glob("*.[ot]tf")):
            # "Pretendard-Regular.otf" → "Pretendard"
            family = path.stem.split("-")[0]
            if any(f["name"] == family for f in fonts):
                continue
            fonts.append(
                {
                    "name": family,
                    "label": f"{family} (함께 제공)",
                    "bundled": True,
                    "safe_for_burn": True,
                }
            )

    # 2) 시스템에 설치된 한글 글꼴
    system_dirs = _windows_font_dirs()
    installed: set[str] = set()
    for directory in system_dirs:
        try:
            installed |= {p.name.lower() for p in directory.iterdir()}
        except OSError:
            continue

    for family, filename in KNOWN_KOREAN_FONTS:
        if filename.lower() in installed and not any(f["name"] == family for f in fonts):
            fonts.append(
                {
                    "name": family,
                    "label": family,
                    "bundled": False,
                    "safe_for_burn": True,  # 시스템 폰트도 libass가 이름으로 찾는다
                }
            )

    if not fonts:  # 아무것도 못 찾은 극단적 경우의 대비
        fonts.append(
            {"name": "Malgun Gothic", "label": "맑은 고딕", "bundled": False, "safe_for_burn": True}
        )

    return fonts


def fonts_dir_for_ffmpeg() -> str:
    """FFmpeg의 ass 필터에 넘길 fontsdir 경로."""
    return str(FONTS_DIR)
