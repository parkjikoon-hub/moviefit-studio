"""프로젝트 전역 경로와 설정값. 경로가 필요한 모든 모듈은 여기를 통해서만 접근한다."""

from pathlib import Path

# 이 파일 기준으로 저장소 최상위 폴더를 찾는다 (app/config.py → app/ → 최상위)
ROOT_DIR = Path(__file__).resolve().parent.parent

STATIC_DIR = ROOT_DIR / "app" / "static"
PROJECTS_DIR = ROOT_DIR / "projects"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
SAMPLE_DIR = ROOT_DIR / "tests" / "sample"

# 서버 기본 주소
HOST = "127.0.0.1"
PORT = 8765

# 가져오기 허용 확장자 (F-01)
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


def ensure_dirs() -> None:
    """서버가 쓰는 폴더들이 없으면 만든다."""
    for d in (PROJECTS_DIR, FONTS_DIR, SAMPLE_DIR):
        d.mkdir(parents=True, exist_ok=True)
