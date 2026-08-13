"""설치 파일(MovieFitStudio-설치.exe)을 만든다.

왜 필요한가: 지금은 쓰려면 파이썬 설치 → FFmpeg 설치 → ZIP 내려받기 → 압축 풀기의
네 단계를 거쳐야 한다. 프로그램을 처음 접하는 사람에게는 이 자체가 큰 벽이다.
이 스크립트는 그 넷을 모두 담은 설치 파일 하나를 만든다.

방식: 파이썬을 exe로 변환(PyInstaller)하지 않고, **임베디드 파이썬을 통째로 넣는다.**
음성인식 부품(ctranslate2, onnxruntime)은 변환 방식에서 오류가 잦은데,
임베디드 방식은 지금 개발 환경에서 도는 것과 똑같이 동작하기 때문이다.

실행: python tools/build_installer.py
      python tools/build_installer.py --skip-download   (내려받기를 건너뛴다)
      python tools/build_installer.py --payload-only    (설치 파일 컴파일 전까지만)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CACHE = BUILD / "cache"          # 내려받은 원본 (지우지 않으면 다시 받지 않는다)
PAYLOAD = BUILD / "payload"      # 설치 파일에 담길 내용물 전체
DIST = BUILD / "dist"            # 완성된 설치 파일

PY_VERSION = "3.11.9"
PY_EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 프로그램을 돌리는 데 실제로 필요한 것만 담는다 (tests, docs, landing은 제외)
APP_ITEMS = ["app", "tools", "assets", "LICENSE", "NOTICE.md", "README.md", "requirements.txt"]

# 설치 파일에서 빼도 되는 것들 (용량 절감)
PRUNE_PATTERNS = ["__pycache__", "*.pyc", "*.pyo"]


# ── 도우미 ────────────────────────────────────────────────
def step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}")
    print("-" * 60)


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"  [건너뜀] {dest.name} — 이미 받아 두었습니다")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  받는 중… {dest.name}")

    def hook(count: int, block: int, total: int) -> None:
        if total > 0:
            pct = min(100, count * block * 100 // total)
            print(f"\r    {pct}%  ({total / 1024 / 1024:.0f} MB)", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=hook)
    print(f"\r    완료 ({dest.stat().st_size / 1024 / 1024:.1f} MB)      ")
    return dest


def prune(folder: Path) -> None:
    """캐시 파일처럼 설치 파일에 넣을 필요 없는 것을 지운다."""
    for pattern in PRUNE_PATTERNS:
        for path in folder.rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def folder_size_mb(folder: Path) -> float:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1024 / 1024


def app_version() -> str:
    """앱이 쓰는 버전을 그대로 읽어 온다.

    여기에 숫자를 따로 적어 두면 app/__init__.py 와 어긋나서, 설치 화면에는 0.2.0인데
    프로그램 안에서는 0.1.0으로 보이는 일이 생긴다. 출처를 하나로 둔다.
    """
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("  [오류] app/__init__.py 에서 __version__ 을 찾지 못했습니다.")
    return match.group(1)


# ── 1. 내려받기 ───────────────────────────────────────────
def fetch_sources() -> tuple[Path, Path, Path]:
    py_zip = download(PY_EMBED_URL, CACHE / f"python-{PY_VERSION}-embed.zip")
    get_pip = download(GET_PIP_URL, CACHE / "get-pip.py")
    ffmpeg_zip = download(FFMPEG_URL, CACHE / "ffmpeg-essentials.zip")
    return py_zip, get_pip, ffmpeg_zip


# ── 2. 파이썬 심기 ────────────────────────────────────────
def install_python(py_zip: Path) -> Path:
    py_dir = PAYLOAD / "python"
    if py_dir.exists():
        shutil.rmtree(py_dir)
    py_dir.mkdir(parents=True)

    with zipfile.ZipFile(py_zip) as zf:
        zf.extractall(py_dir)

    # 임베디드 파이썬은 ._pth 파일에 적힌 폴더만 읽는다. 기본값에는 Lib가 빠져 있어서
    # 세 줄을 반드시 넣어야 한다:
    #   Lib               → tkinter(파일 선택 창) 등 표준 부품
    #   Lib\site-packages → pip으로 설치한 부품 (fastapi, faster-whisper 등)
    #   import site       → 위 경로들을 실제로 활성화
    # Lib를 빠뜨리면 서버는 뜨지만 [영상 파일 선택하기] 버튼만 조용히 실패한다.
    # 주의: 이 파일에 BOM이 붙으면 첫 줄이 '﻿python311.zip'이 되어 파이썬이 아예
    # 시작하지 못한다("No module named 'encodings'"). write_text(encoding="utf-8")는
    # BOM을 붙이지 않으므로 그대로 두고, 손으로 고칠 때만 조심하면 된다.
    for pth in py_dir.glob("python*._pth"):
        lines = [ln.strip() for ln in pth.read_text(encoding="utf-8").splitlines()]
        kept = [ln for ln in lines if ln and not ln.startswith("#") and ln != "import site"]
        # ".." = 설치 폴더 자신(app 패키지가 있는 곳).
        # 임베디드 파이썬은 격리 모드라 현재 작업 폴더를 자동으로 읽지 않기 때문에
        # 이 줄이 없으면 "No module named app" 으로 서버가 뜨지 않는다.
        for needed in ("..", "Lib", "Lib\\site-packages"):
            if needed not in kept:
                kept.append(needed)
        kept.append("import site")
        pth.write_text("\n".join(kept) + "\n", encoding="utf-8")
        print(f"  [수정] {pth.name} — 읽을 폴더: {', '.join(kept[:-1])}")

    print(f"  파이썬 {PY_VERSION} 준비 완료 ({folder_size_mb(py_dir):.1f} MB)")
    return py_dir


# ── 3. 부품 설치 ──────────────────────────────────────────
def install_packages(py_dir: Path, get_pip: Path) -> None:
    python = py_dir / "python.exe"

    print("  pip(부품 설치 도구)을 넣는 중…")
    subprocess.run([str(python), str(get_pip), "--no-warn-script-location", "-q"], check=True)

    print("  프로그램에 필요한 부품을 설치하는 중… (몇 분 걸립니다)")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"),
         "--no-warn-script-location", "-q"],
        check=True,
    )

    # 설치 도구 자신은 사용자 컴퓨터에서 쓸 일이 없다 (약 14MB 절약)
    for junk in ("pip", "setuptools", "wheel", "pkg_resources"):
        for path in (py_dir / "Lib" / "site-packages").glob(f"{junk}*"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    prune(py_dir)
    print(f"  부품 설치 완료 (파이썬 폴더 전체 {folder_size_mb(py_dir):.1f} MB)")


# ── 4. 파일 선택 창(tkinter) 이식 ─────────────────────────
def install_tkinter(py_dir: Path) -> None:
    """임베디드 파이썬에는 tkinter가 없다. 시스템 파이썬에서 가져온다.

    이게 없으면 [영상 파일 선택하기] 버튼이 동작하지 않는다.
    Tcl/Tk는 BSD 계열 라이선스라 함께 배포해도 된다.
    """
    src_base = Path(sys.base_prefix)
    items = [
        ("DLLs/_tkinter.pyd", "_tkinter.pyd"),
        ("DLLs/tcl86t.dll", "tcl86t.dll"),
        ("DLLs/tk86t.dll", "tk86t.dll"),
        ("Lib/tkinter", "Lib/tkinter"),
        ("tcl", "tcl"),
    ]
    for rel_src, rel_dst in items:
        src = src_base / rel_src
        dst = py_dir / rel_dst
        if not src.exists():
            raise SystemExit(
                f"  [오류] {src} 가 없습니다.\n"
                "  파일 선택 창에 필요한 부품입니다. 시스템 파이썬이 tkinter를 포함해\n"
                "  설치되어 있는지 확인해 주세요."
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        print(f"  [복사] {rel_dst}")


# ── 5. FFmpeg 넣기 ────────────────────────────────────────
def install_ffmpeg(ffmpeg_zip: Path) -> None:
    ff_dir = PAYLOAD / "ffmpeg"
    if ff_dir.exists():
        shutil.rmtree(ff_dir)
    ff_dir.mkdir(parents=True)

    wanted = {"ffmpeg.exe", "ffprobe.exe"}
    found: set[str] = set()
    with zipfile.ZipFile(ffmpeg_zip) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if name in wanted:
                with zf.open(info) as src, (ff_dir / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                found.add(name)
                print(f"  [추출] {name}  ({(ff_dir / name).stat().st_size / 1024 / 1024:.1f} MB)")

    missing = wanted - found
    if missing:
        raise SystemExit(f"  [오류] FFmpeg 압축 파일에서 {missing} 를 찾지 못했습니다.")


# ── 6. 프로그램 파일 복사 ─────────────────────────────────
def copy_app() -> None:
    for item in APP_ITEMS:
        src = ROOT / item
        dst = PAYLOAD / item
        if not src.exists():
            print(f"  [건너뜀] {item} — 없음")
            continue
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        print(f"  [복사] {item}")

    prune(PAYLOAD)

    # 내용물을 손으로 시험 실행하면 서버가 빈 폴더(projects, tests/sample)와 로그를
    # 남긴다. 그대로 두면 설치 파일에 섞여 들어가므로 여기서 지운다.
    # (빈 폴더는 프로그램이 첫 실행 때 알아서 만든다)
    for junk in ("projects", "tests"):
        shutil.rmtree(PAYLOAD / junk, ignore_errors=True)
    for pattern in ("_*.log", "_*.err"):
        for path in PAYLOAD.glob(pattern):
            path.unlink(missing_ok=True)

    # 한글 폰트는 저장소에 없으므로 여기서 받아 넣는다 (설치 후 인터넷 없이도 자막이 제대로 나오게)
    fonts = PAYLOAD / "assets" / "fonts"
    if not any(fonts.glob("*.otf")):
        print("  한글 폰트를 받는 중…")
        subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_font.py")], check=False)
        for name in ("Pretendard-Regular.otf", "Pretendard-Bold.otf"):
            src = ROOT / "assets" / "fonts" / name
            if src.exists():
                shutil.copy2(src, fonts / name)
                print(f"  [복사] assets/fonts/{name}")


# ── 7. 실행 파일 만들기 ───────────────────────────────────
LAUNCHER_BAT = """@echo off
chcp 65001 > nul
title MovieFit Studio
cd /d "%~dp0"
set "PATH=%~dp0ffmpeg;%PATH%"
"%~dp0python\\python.exe" tools\\launch.py
"""


def write_launcher() -> None:
    """실행용 배치 파일. 반드시 CRLF로 저장한다 (LF면 cmd가 각 줄 앞글자를 잘라먹는다)."""
    path = PAYLOAD / "MovieFitStudio.bat"
    raw = LAUNCHER_BAT.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(raw)
    print(f"  [생성] {path.name} (CRLF 확인)")


# ── 8. 설치 파일 컴파일 ───────────────────────────────────
ISS_TEMPLATE = r"""
; MovieFit Studio 설치 스크립트 (Inno Setup)
; 관리자 권한을 요구하지 않는다 — 설치 중 경고창이 뜨지 않고,
; 사용자 폴더에 설치되므로 작업물 저장에도 권한 문제가 없다.

[Setup]
AppName=MovieFit Studio
AppVersion={#AppVersion}
AppPublisher=MovieFit Studio
AppPublisherURL=https://github.com/parkjikoon-hub/moviefit-studio
DefaultDirName={localappdata}\Programs\MovieFit Studio
DefaultGroupName=MovieFit Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
; 파일 이름은 영문으로 둔다. GitHub 내려받기 주소에 한글이 들어가면
; 브라우저·다운로드 도구에 따라 이름이 깨지거나 주소가 어긋난다.
; 설치 화면에 보이는 이름(AppName)은 한글 그대로다.
OutputBaseFilename=MovieFitStudio-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\app\static\icons\favicon.ico
LicenseFile={#LicenseFile}
; 프로그램이 켜져 있는 채로 설치하면 파일이 잠겨 있어 **조용히 실패한다.**
; 오류도 안 나고 옛 버전이 그대로 남아, 사용자는 새 버전을 설치했다고 믿는다.
; 프로그램이 켜질 때 남기는 표시(app/__main__.py 의 RUNNING_MARK)를 여기서 확인해
; 설치를 시작하기 전에 멈추고 안내한다. 이름을 바꾸면 양쪽을 함께 바꿔야 한다.
AppMutex=MovieFitStudioRunning

[Messages]
; 위 AppMutex 에 걸렸을 때 나오는 안내. 기본 문구는 "응용 프로그램"이라고만 해서
; 무엇을 어떻게 닫으라는 것인지 알 수 없다.
SetupAppRunningError=MovieFit Studio 가 지금 실행 중입니다.%n%n먼저 프로그램을 닫아 주세요.%n브라우저 탭만 닫아서는 꺼지지 않습니다. 제목이 "MovieFit Studio" 인 검은 명령 창을 닫아야 완전히 종료됩니다.%n%n닫으신 뒤 [확인]을 누르면 설치를 계속합니다.
UninstallAppRunningError=MovieFit Studio 가 지금 실행 중입니다.%n%n제목이 "MovieFit Studio" 인 검은 명령 창을 닫으신 뒤 [확인]을 눌러 주세요.

[Languages]
Name: "korean"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 아이콘 만들기"; GroupDescription: "추가 아이콘:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MovieFit Studio"; Filename: "{app}\MovieFitStudio.bat"; IconFilename: "{app}\app\static\icons\favicon.ico"; WorkingDir: "{app}"
Name: "{group}\MovieFit Studio 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MovieFit Studio"; Filename: "{app}\MovieFitStudio.bat"; IconFilename: "{app}\app\static\icons\favicon.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MovieFitStudio.bat"; Description: "지금 MovieFit Studio 실행하기"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\__pycache__"
"""


def find_iscc() -> Path:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit(
        "  [오류] Inno Setup(설치 파일 제작 도구)을 찾지 못했습니다.\n"
        "  PowerShell에서  winget install JRSoftware.InnoSetup  을 실행해 주세요."
    )


def compile_installer(version: str) -> Path:
    iscc = find_iscc()
    DIST.mkdir(parents=True, exist_ok=True)

    icon = PAYLOAD / "app" / "static" / "icons" / "favicon.ico"
    if not icon.exists():
        raise SystemExit(f"  [오류] 아이콘 파일이 없습니다: {icon}")

    iss_path = BUILD / "installer.iss"
    header = (
        f'#define AppVersion "{version}"\n'
        f'#define PayloadDir "{PAYLOAD}"\n'
        f'#define OutputDir "{DIST}"\n'
        f'#define IconFile "{icon}"\n'
        f'#define LicenseFile "{PAYLOAD / "LICENSE"}"\n'
    )
    iss_path.write_text(header + ISS_TEMPLATE, encoding="utf-8-sig")

    print(f"  설치 파일을 만드는 중… (압축에 몇 분 걸립니다)")
    result = subprocess.run([str(iscc), str(iss_path)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-2000:])
        raise SystemExit("  [오류] 설치 파일 만들기에 실패했습니다.")

    made = sorted(DIST.glob("*.exe"), key=lambda p: p.stat().st_mtime)[-1]
    return made


# ── 실행 ──────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true", help="내려받기를 건너뛴다")
    parser.add_argument("--payload-only", action="store_true", help="설치 파일 컴파일 전까지만")
    parser.add_argument("--compile-only", action="store_true",
                        help="이미 만든 내용물을 압축만 한다 (내용물 재생성 없음)")
    parser.add_argument("--version", default=None,
                        help="적지 않으면 app/__init__.py 의 버전을 그대로 쓴다")
    args = parser.parse_args()
    version = args.version or app_version()

    print("=" * 60)
    print(f"  MovieFit Studio 설치 파일 만들기 — 버전 {version}")
    print("=" * 60)

    if args.compile_only:
        if not (PAYLOAD / "MovieFitStudio.bat").exists():
            raise SystemExit("  [오류] 내용물이 없습니다. 먼저 --payload-only 로 만들어 주세요.")
        print(f"\n  기존 내용물을 씁니다: {folder_size_mb(PAYLOAD):.1f} MB")
        made = compile_installer(version)
        print()
        print("=" * 60)
        print(f"  완성: {made}")
        print(f"  크기: {made.stat().st_size / 1024 / 1024:.1f} MB")
        print("=" * 60)
        return 0

    total = 7 if args.payload_only else 8
    PAYLOAD.mkdir(parents=True, exist_ok=True)

    step(1, total, "필요한 원본 내려받기 (파이썬 · FFmpeg)")
    py_zip, get_pip, ffmpeg_zip = fetch_sources()

    step(2, total, "파이썬 심기")
    py_dir = install_python(py_zip)

    step(3, total, "프로그램 부품 설치")
    install_packages(py_dir, get_pip)

    step(4, total, "파일 선택 창 부품 넣기")
    install_tkinter(py_dir)

    step(5, total, "FFmpeg 넣기")
    install_ffmpeg(ffmpeg_zip)

    step(6, total, "프로그램 파일 복사")
    copy_app()

    step(7, total, "실행 파일 만들기")
    write_launcher()

    print(f"\n  내용물 전체 크기: {folder_size_mb(PAYLOAD):.1f} MB")

    if args.payload_only:
        print(f"\n  준비 완료: {PAYLOAD}")
        return 0

    step(8, total, "설치 파일로 묶기")
    made = compile_installer(version)

    print()
    print("=" * 60)
    print(f"  완성: {made}")
    print(f"  크기: {made.stat().st_size / 1024 / 1024:.1f} MB")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
