"""윈도우 기본 '파일 선택' 창을 띄워 영상 파일의 실제 경로를 받아온다.

왜 필요한가: 브라우저는 보안 때문에 웹페이지에 파일의 전체 경로를 알려주지 않는다.
하지만 이 프로그램은 내 컴퓨터에서만 도는 도구이므로, 서버 쪽에서 윈도우 기본
파일 선택 창을 열면 경로를 그대로 얻을 수 있다. 영상을 복사할 필요가 없어 훨씬 빠르다.

구현 주의: tkinter 창은 웹서버와 같은 스레드에서 열면 충돌하므로,
별도의 파이썬 프로세스를 잠깐 띄워서 경로만 받아온다.
"""

from __future__ import annotations

import subprocess
import sys

# 별도 프로세스에서 실행될 코드. 고른 경로를 **한 줄에 하나씩** 표준출력으로 내보낸다.
# 한 개짜리 선택도 같은 규칙을 쓴다 — 부르는 쪽이 갈래를 하나만 다루면 되기 때문이다.
_PICKER_CODE = r"""
import sys, tkinter as tk
from tkinter import filedialog

# multi=True 면 여러 개를 한 번에 고를 수 있다 (사진은 수십 장을 고른다).
KINDS = {
    "media": ("영상 또는 오디오 파일 선택", False,
              [("영상/오디오 파일", "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a"),
               ("모든 파일", "*.*")]),
    "subtitle": ("자막 파일 선택", False,
                 [("자막 파일", "*.srt *.vtt *.ass *.ssa"), ("모든 파일", "*.*")]),
    "audio": ("음원 파일 선택", False,
              [("음원 파일", "*.mp3 *.wav *.m4a"), ("모든 파일", "*.*")]),
    "images": ("사진 선택 (여러 장을 한 번에 고를 수 있습니다)", True,
               [("사진 파일", "*.jpg *.jpeg *.png *.webp"), ("모든 파일", "*.*")]),
}
kind = sys.argv[1] if len(sys.argv) > 1 else "media"
title, multi, filetypes = KINDS.get(kind, KINDS["media"])

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)   # 브라우저 뒤에 숨지 않게 맨 앞으로
if multi:
    picked = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    paths = list(picked or ())
else:
    one = filedialog.askopenfilename(title=title, filetypes=filetypes)
    paths = [one] if one else []
root.destroy()
sys.stdout.write("\n".join(paths))
"""


class FileDialogUnavailable(Exception):
    """파일 선택 창을 띄울 수 없는 환경 (예: 화면 없는 서버)."""


def ask_files(timeout: float = 300.0, kind: str = "media") -> list[str]:
    """파일 선택 창을 띄우고 고른 경로들을 돌려준다. 취소하면 빈 목록.

    kind 는 "media"(영상·오디오) · "subtitle"(자막) · "audio"(음원) ·
    "images"(사진 여러 장) 중 하나다. "images" 만 여러 개를 고를 수 있다.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PICKER_CODE, kind],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # 파이썬 실행 파일을 못 찾는 극단적 경우
        raise FileDialogUnavailable("파이썬 실행 파일을 찾을 수 없습니다.") from exc
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0:
        raise FileDialogUnavailable(
            "파일 선택 창을 열지 못했습니다. 아래 칸에 파일 경로를 직접 붙여넣어 주세요.\n"
            + (result.stderr or "").strip()
        )

    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def ask_media_file(timeout: float = 300.0, kind: str = "media") -> str | None:
    """파일 한 개를 고르게 하고 그 경로를 돌려준다. 취소하면 None."""
    picked = ask_files(timeout=timeout, kind=kind)
    return picked[0] if picked else None
