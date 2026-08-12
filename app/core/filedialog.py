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

# 별도 프로세스에서 실행될 코드. 선택한 경로 한 줄만 표준출력으로 내보낸다.
_PICKER_CODE = r"""
import sys, tkinter as tk
from tkinter import filedialog

KINDS = {
    "media": ("영상 또는 오디오 파일 선택",
              [("영상/오디오 파일", "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a"),
               ("모든 파일", "*.*")]),
    "subtitle": ("자막 파일 선택",
                 [("자막 파일", "*.srt *.vtt *.ass *.ssa"), ("모든 파일", "*.*")]),
}
kind = sys.argv[1] if len(sys.argv) > 1 else "media"
title, filetypes = KINDS.get(kind, KINDS["media"])

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)   # 브라우저 뒤에 숨지 않게 맨 앞으로
path = filedialog.askopenfilename(title=title, filetypes=filetypes)
root.destroy()
sys.stdout.write(path or "")
"""


class FileDialogUnavailable(Exception):
    """파일 선택 창을 띄울 수 없는 환경 (예: 화면 없는 서버)."""


def ask_media_file(timeout: float = 300.0, kind: str = "media") -> str | None:
    """파일 선택 창을 띄우고 선택된 경로를 돌려준다. 취소하면 None.

    kind="media"면 영상·오디오, kind="subtitle"이면 자막 파일만 걸러 보여 준다.
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
        return None

    if result.returncode != 0:
        raise FileDialogUnavailable(
            "파일 선택 창을 열지 못했습니다. 아래 칸에 파일 경로를 직접 붙여넣어 주세요.\n"
            + (result.stderr or "").strip()
        )

    path = (result.stdout or "").strip()
    return path or None
