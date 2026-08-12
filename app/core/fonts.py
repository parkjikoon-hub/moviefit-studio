"""자막에 쓸 수 있는 글꼴 목록.

번들 폰트(assets/fonts/)를 먼저 보여주고, 그다음 **윈도우에 실제로 설치된 글꼴 중
한글을 그릴 수 있는 것을 전부** 보여준다.

예전에는 글꼴 이름을 열한 개쯤 손으로 적어 두고 그중 있는 것만 보여줬는데,
보통의 윈도우에는 한글 글꼴이 수십 개 깔려 있어서 대부분이 목록에 나오지 않았다.
그래서 이름을 미리 적어 두는 방식을 버리고, 설치된 글꼴을 직접 훑어 판별한다.

판별 방법: 글꼴 파일 안의 문자표(cmap)에서 한글 '가'(U+AC00)를 그릴 수 있는지 본다.
이름만 보고 짐작하면 'Yu Gothic'(일본어)처럼 이름은 비슷한데 한글이 네모로 나오는
글꼴이 섞여 들어온다. 실제로 그릴 수 있는지를 파일에서 확인하는 편이 확실하다.
"""

from __future__ import annotations

import struct
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

from app.config import FONTS_DIR

HANGUL_SAMPLE = 0xAC00  # '가' — 이 글자를 그릴 수 있으면 한글 글꼴로 본다


# ── 글꼴 파일 뜯어보기 ────────────────────────────────────
def _read_table_dir(f: BinaryIO, offset: int = 0) -> dict[bytes, tuple[int, int]]:
    """글꼴 파일 안의 '표 목록'을 읽는다. .ttc(여러 글꼴 묶음)면 첫 글꼴을 본다."""
    f.seek(offset)
    if f.read(4) == b"ttcf":
        f.seek(offset + 12)
        first = struct.unpack(">I", f.read(4))[0]
        return _read_table_dir(f, first)

    f.seek(offset + 4)
    (num_tables,) = struct.unpack(">H", f.read(2))
    f.seek(offset + 12)

    tables: dict[bytes, tuple[int, int]] = {}
    for _ in range(min(num_tables, 64)):
        record = f.read(16)
        if len(record) < 16:
            break
        tag, _checksum, off, length = struct.unpack(">4sIII", record)
        tables[tag] = (off, length)
    return tables


def _cmap_covers(f: BinaryIO, cmap_offset: int, code: int) -> bool:
    """문자표에 해당 글자가 들어 있는지 본다 (형식 4와 12만 다룬다)."""
    f.seek(cmap_offset)
    _version, count = struct.unpack(">HH", f.read(4))

    subtables: list[int] = []
    for _ in range(min(count, 32)):
        record = f.read(8)
        if len(record) < 8:
            break
        platform, encoding, off = struct.unpack(">HHI", record)
        # 유니코드를 쓰는 표만 본다 (윈도우 유니코드 3-1/3-10, 또는 플랫폼 0)
        if platform == 0 or (platform == 3 and encoding in (1, 10)):
            subtables.append(cmap_offset + off)

    for off in subtables:
        f.seek(off)
        (fmt,) = struct.unpack(">H", f.read(2))

        if fmt == 4:
            _length, _lang, seg_x2 = struct.unpack(">HHH", f.read(6))
            segments = seg_x2 // 2
            if segments == 0:
                continue
            f.read(6)  # searchRange, entrySelector, rangeShift — 쓰지 않는다
            ends = struct.unpack(f">{segments}H", f.read(segments * 2))
            f.read(2)  # reservedPad
            starts = struct.unpack(f">{segments}H", f.read(segments * 2))
            for i in range(segments):
                if starts[i] <= code <= ends[i]:
                    return True

        elif fmt == 12:
            f.read(10)  # reserved, length, language
            (groups,) = struct.unpack(">I", f.read(4))
            for _ in range(min(groups, 20000)):
                record = f.read(12)
                if len(record) < 12:
                    break
                start, end, _glyph = struct.unpack(">III", record)
                if start <= code <= end:
                    return True
                if start > code:
                    break

    return False


def _supports_hangul(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            tables = _read_table_dir(f)
            cmap = tables.get(b"cmap")
            if not cmap:
                return False
            return _cmap_covers(f, cmap[0], HANGUL_SAMPLE)
    except (OSError, struct.error, ValueError):
        return False


# ── 설치된 글꼴 찾기 ──────────────────────────────────────
def _registry_fonts() -> list[tuple[str, str]]:
    """윈도우가 기억하는 (글꼴 이름, 파일명) 목록. 등록된 이름을 그대로 쓰므로
    사용자가 다른 프로그램에서 보던 이름과 같게 나온다."""
    if sys.platform != "win32":
        return []

    import winreg

    found: list[tuple[str, str]] = []
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as key:
                count = winreg.QueryInfoKey(key)[1]
                for i in range(count):
                    try:
                        raw_name, filename, _type = winreg.EnumValue(key, i)
                    except OSError:
                        continue
                    if not isinstance(filename, str):
                        continue
                    # "맑은 고딕 & 맑은 고딕 Semilight (TrueType)" 같은 형태를 정리한다
                    name = raw_name
                    for suffix in (" (TrueType)", " (OpenType)", " (All res)"):
                        name = name.replace(suffix, "")
                    for part in name.split("&"):
                        part = part.strip()
                        if part:
                            found.append((part, filename))
        except OSError:
            continue
    return found


def _font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        import os

        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:  # 사용자 계정에만 설치한 글꼴
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


def _resolve(filename: str, dirs: list[Path]) -> Path | None:
    candidate = Path(filename)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    for d in dirs:
        p = d / candidate.name
        if p.is_file():
            return p
    return None


@lru_cache(maxsize=1)
def list_fonts() -> list[dict[str, Any]]:
    """화면의 글꼴 선택 목록에 뿌릴 자료.

    글꼴 파일을 하나씩 열어 보므로 처음 한 번은 1~2초쯤 걸린다. 그 뒤로는 기억해 둔다.
    """
    fonts: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) 함께 넣어 둔 글꼴 — 영상에 새길 때 가장 확실하다
    if FONTS_DIR.is_dir():
        for path in sorted(FONTS_DIR.glob("*.[ot]tf")):
            family = path.stem.split("-")[0]
            if family in seen:
                continue
            seen.add(family)
            fonts.append(
                {
                    "name": family,
                    "label": f"{family} (함께 제공)",
                    "bundled": True,
                    "safe_for_burn": True,
                }
            )

    # 2) 설치된 글꼴 가운데 한글을 그릴 수 있는 것 전부
    dirs = _font_dirs()
    checked: dict[str, bool] = {}   # 같은 파일을 두 번 뜯어보지 않는다

    system: list[dict[str, Any]] = []
    for name, filename in _registry_fonts():
        if name in seen:
            continue
        path = _resolve(filename, dirs)
        if path is None:
            continue

        key = str(path).lower()
        if key not in checked:
            checked[key] = _supports_hangul(path)
        if not checked[key]:
            continue

        seen.add(name)
        system.append(
            {
                "name": name,
                "label": name,
                "bundled": False,
                "safe_for_burn": True,  # 설치된 글꼴은 libass가 이름으로 찾아 쓴다
            }
        )

    system.sort(key=lambda f: f["name"].lower())
    fonts.extend(system)

    if not fonts:  # 아무것도 못 찾은 극단적 경우의 대비
        fonts.append(
            {"name": "Malgun Gothic", "label": "맑은 고딕", "bundled": False, "safe_for_burn": True}
        )

    return fonts


def fonts_dir_for_ffmpeg() -> str:
    """FFmpeg의 ass 필터에 넘길 fontsdir 경로."""
    return str(FONTS_DIR)
