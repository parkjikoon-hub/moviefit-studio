"""FFmpeg 명령 조립 — 오디오 추출, ASS 자막 만들기, 자막 번인, 미리보기 렌더.

기준 명령은 docs/TECH_SPEC.md 7절이다. 이 파일 밖에서는 ffmpeg을 직접 부르지 않는다.

이 모듈이 신경 쓰는 세 가지 위험:

- R6 (윈도우 경로): 인자는 항상 리스트로 넘긴다. 셸 문자열을 조립하면 한글·공백 경로가 깨진다.
  필터에 들어가는 경로는 추가로 _escape_filter_path()를 반드시 거쳐야 한다.
- R4 (한글 폰트): 번인할 때 fontsdir로 번들 폰트 폴더를 알려 준다. 안 그러면 글자가 네모(□)가 된다.
- N-05 (출력 안전): 원본 파일에 절대 덮어쓰지 않는다. out/ 폴더에 임시 이름으로 쓰고
  성공했을 때만 최종 이름으로 바꾼다. 실패·취소하면 반쪽짜리 파일이 남지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from app.core import effects, framing, style_map
from app.core.fonts import fonts_dir_for_ffmpeg
from app.core.jobs import JobCancelled

# 진행률을 보고하는 함수의 모양: report(0.0~1.0, "한국어 설명")
Reporter = Callable[[float, str], None]


class RenderError(Exception):
    """렌더링(영상 만들기) 실패. 메시지는 사용자에게 그대로 보여줄 한국어 문장이다."""


# ── 공통 도우미 ────────────────────────────────────────────
def _require(tool: str) -> None:
    """ffmpeg/ffprobe가 설치돼 있는지 먼저 확인한다."""
    if shutil.which(tool) is None:
        raise RenderError(
            f"{tool}(영상 처리 도구)을 찾을 수 없습니다. "
            "FFmpeg을 설치해 주세요. PowerShell에서: winget install Gyan.FFmpeg"
        )


def _noop(progress: float, message: str) -> None:
    """진행률 보고가 필요 없을 때 쓰는 빈 함수."""


def _fmt_time(seconds: float) -> str:
    """12.4 → '12초', 72 → '1분 12초'. 사용자에게 보여줄 시간 표기."""
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}분 {secs}초" if minutes else f"{secs}초"


# 필터 인자 안에서 특별한 뜻을 갖는 글자들.
# ':'는 옵션 구분, ','와 ';'는 필터 구분, '[]'는 연결 이름, '\'는 이스케이프 문자다.
_FILTER_SPECIALS = ":'\\,;[]"


def _escape_filter_path(path: str | Path) -> str:
    r"""윈도우 경로를 FFmpeg '필터' 안에 넣을 수 있는 형태로 바꾼다.

    왜 필요한가 (R6):
        -vf "ass=C:\projects\자막.ass" 는 반드시 실패한다. 필터 문법에서 ':'는 옵션
        구분자라 FFmpeg은 이걸 "ass 필터에 'C'라는 파일과 '/projects/자막.ass'라는
        두 번째 옵션"으로 읽는다. 그래서 실제로 튀어나오는 오류는
        `Unable to parse "original_size" option value ... as image size` 같은
        완전히 엉뚱한 문장이다. 경로 문제라는 걸 알아채기가 아주 어려우니 주의.

    바꾸는 방법 (실측으로 확인한 형태):
        1) 역슬래시(\)를 슬래시(/)로 — 윈도우 FFmpeg은 슬래시 경로를 그대로 받아들인다.
        2) 남은 특수문자 앞에 역슬래시를 '두 개' 붙인다.

        C:\Users\INTEL\한글 폴더\자막.ass  →  C\\:/Users/INTEL/한글 폴더/자막.ass

        역슬래시가 두 개인 이유: 이 문자열은 껍질이 두 겹이라 두 번 벗겨진다.
        먼저 필터그래프 해석기가 한 겹(\\ → \)을 벗기고, 그다음 필터의 옵션 해석기가
        나머지 한 겹(\: → :)을 벗긴다. 한 개만 붙이면 첫 단계에서 다 사라져서
        옵션 해석기가 다시 ':'를 구분자로 잘라 버린다. (실측 확인함)

    한글과 공백은 손대지 않는다. 인자를 리스트로 넘기므로 공백은 문제가 되지 않는다.

    한계: 폴더 이름에 쉼표나 작은따옴표가 들어 있으면 이 방식으로도 필터그래프 해석이
    깨진다. 그래서 아래 _filter_paths()에서 아예 상대 경로를 쓰도록 해 두었다.
    """
    text = str(path).replace("\\", "/")
    return "".join("\\\\" + ch if ch in _FILTER_SPECIALS else ch for ch in text)


def _filter_paths(ass_path: Path) -> tuple[str, str, str]:
    r"""ass 필터에 넣을 (작업 폴더, 자막 파일 인자, fontsdir 인자)를 만든다.

    절대 경로를 그대로 넣으면 드라이브 문자의 ':' 때문에 늘 이스케이프가 필요하고,
    폴더 이름에 쉼표(예: "홍보영상, 최종")가 들어가면 이스케이프로도 못 막는다.
    그래서 FFmpeg의 작업 폴더를 자막 파일이 있는 폴더로 지정하고, 필터에는
    파일 이름과 상대 경로만 넣는다. 이러면 필터 문자열에 ':'가 아예 없어진다.
    (폰트 폴더가 다른 드라이브에 있는 예외적인 경우에만 절대 경로로 되돌아간다.)
    """
    workdir = ass_path.parent
    fonts_dir = Path(fonts_dir_for_ffmpeg())
    try:
        fonts_arg = os.path.relpath(fonts_dir, workdir)
    except ValueError:  # 드라이브가 다르면 상대 경로를 만들 수 없다
        fonts_arg = str(fonts_dir)
    return str(workdir), _escape_filter_path(ass_path.name), _escape_filter_path(fonts_arg)


def video_dimensions(path: str | Path) -> tuple[int, int]:
    """영상의 실제 가로·세로 픽셀 크기.

    자막 크기와 위치는 해상도에 비례해서 계산되므로 추정하면 안 되고 실측해야 한다.
    (app/core/ffprobe.py 는 길이만 재기 때문에 크기 측정은 여기에 둔다.)
    """
    _require("ffprobe")
    src = Path(path)
    if not src.is_file():
        raise RenderError(f"영상 파일이 없습니다: {src}")

    # 인자는 반드시 리스트로 — 한글·공백 경로에서 셸 문자열 조립은 깨진다 (R6)
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60)
    if result.returncode != 0:
        raise RenderError(f"영상 크기를 재지 못했습니다: {(result.stderr or '').strip()[:200]}")

    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        raise RenderError("영상에서 화면 크기 정보를 찾지 못했습니다.") from exc

    if width <= 0 or height <= 0:
        raise RenderError("영상 화면 크기가 올바르지 않습니다.")
    return width, height


def video_fps(path: str | Path, fallback: float = 30.0) -> float:
    """영상의 초당 프레임 수.

    화면 효과(zoompan)가 이 값을 **반드시** 알아야 한다. 안 알려 주면 FFmpeg 이 기본값
    25 를 써서 **10초짜리 영상이 12초로 늘어난다** (실측). 소리와 어긋나는 조용한 사고다.

    잴 수 없으면 fallback 을 돌려준다 — 효과를 못 걸게 막는 것보다 낫고, 대부분의
    영상이 30fps 다.
    """
    _require("ffprobe")
    src = Path(path)
    if not src.is_file():
        raise RenderError(f"영상 파일이 없습니다: {src}")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate",
        "-of", "json",
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60)
    if result.returncode != 0:
        return fallback

    try:
        stream = json.loads(result.stdout)["streams"][0]
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return fallback

    # "30000/1001" 처럼 분수로 온다. avg 가 0/0 인 파일이 있어 r_frame_rate 를 먼저 본다.
    for key in ("r_frame_rate", "avg_frame_rate"):
        text = str(stream.get(key) or "")
        if "/" not in text:
            continue
        top, _, bottom = text.partition("/")
        try:
            value = float(top) / float(bottom)
        except (ValueError, ZeroDivisionError):
            continue
        if 1.0 <= value <= 240.0:
            return round(value, 3)
    return fallback


# ── 1) 오디오 추출 (TECH_SPEC 7절 1번) ─────────────────────
def extract_audio(src: str | Path, dst: str | Path) -> Path:
    """음성인식(STT)에 넣을 16kHz 모노 wav를 뽑아낸다.

    16kHz 모노인 이유: Whisper 계열 음성인식이 그 형식을 쓰기 때문에
    미리 맞춰 주면 인식기가 다시 변환하지 않아도 된다.
    """
    _require("ffmpeg")
    source = Path(src)
    if not source.is_file():
        raise RenderError(f"파일이 없습니다: {source}")

    target = Path(dst)
    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source),
        "-vn",              # 영상 트랙 버림
        "-ac", "1",         # 모노
        "-ar", "16000",     # 16kHz
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=1800)
    if result.returncode != 0 or not target.is_file():
        raise RenderError(f"소리를 뽑아내지 못했습니다: {(result.stderr or '').strip()[:300]}")
    return target


# ── 2) ASS 자막 파일 만들기 ────────────────────────────────
_ASS_FORMAT_FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
    "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)


def _ass_time(seconds: float) -> str:
    """1.2 → '0:00:01.20'. ASS는 1/100초 단위까지 쓴다."""
    total = max(0.0, float(seconds))
    hours, rest = divmod(int(total), 3600)
    minutes, secs = divmod(rest, 60)
    centis = int(round((total - int(total)) * 100))
    if centis == 100:  # 반올림이 100이 되면 1초로 올린다
        centis = 0
        secs += 1
        if secs == 60:
            secs = 0
            minutes += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_text(text: str) -> str:
    r"""자막 한 줄의 글자를 ASS가 오해하지 않도록 다듬는다.

    - 중괄호 { } : ASS에서는 서식 명령의 시작·끝이라 그냥 두면 그 부분이 사라진다. \{ \} 로 피한다.
    - 줄바꿈     : ASS는 파일 안에서 실제 줄바꿈을 쓸 수 없고 \N 이라고 적어야 한다.
    """
    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("{", r"\{").replace("}", r"\}")
    return cleaned.replace("\n", r"\N")


def build_ass(
    segments: list[dict[str, Any]],
    style: dict[str, Any],
    video_width: int,
    video_height: int,
) -> str:
    """세그먼트 목록 + 스타일 → 완성된 .ass 파일 내용(문자열).

    자막 생김새는 style_map.to_ass_style()이 유일한 출처다. 여기서 따로 꾸미지 않는다.
    """
    style_line, pos_tag = style_map.to_ass_style(style, video_width, video_height)

    lines = [
        "[Script Info]",
        "; MovieFit Studio 가 자동으로 만든 자막 파일입니다.",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "",
        "[V4+ Styles]",
        f"Format: {_ASS_FORMAT_FIELDS}",
        style_line,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    prefix = pos_tag or ""  # 자유 배치일 때만 {\pos(x,y)} 가 붙는다

    # 줄바꿈은 화면 미리보기·SRT 내보내기와 똑같은 규칙을 쓴다.
    # 세 곳이 제각각이면 "미리보기에서 두 줄이던 자막이 영상에서는 한 줄"이 되어
    # 사용자가 결과를 예측할 수 없다.
    from app.core.subtitles import wrap_text

    max_chars = int(style.get("max_chars") or 20)
    max_lines = int(style.get("max_lines") or 2)

    for seg in segments:
        raw = str(seg.get("text") or "").strip()
        if not raw:
            continue  # 빈 자막은 건너뛴다
        text = "\n".join(wrap_text(raw, max_chars, max_lines))
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or 0.0)
        if end <= start:
            continue  # 길이가 없는 자막은 화면에 나올 수 없다
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
            f"{prefix}{_ass_text(text)}"
        )

    return "\n".join(lines) + "\n"


def write_ass_file(
    path: str | Path,
    segments: list[dict[str, Any]],
    style: dict[str, Any],
    video_width: int,
    video_height: int,
) -> Path:
    """ASS 자막 파일을 UTF-8로 기록한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_ass(segments, style, video_width, video_height), encoding="utf-8"
    )
    return target


# ── 3) 진행률을 읽으며 FFmpeg 실행 ─────────────────────────
_PROGRESS_LINE = re.compile(r"^([a-z_]+)=(.*)$")


def _run_with_progress(
    cmd: list[str],
    total_seconds: float,
    report: Reporter,
    verb: str,
    base: float = 0.0,
    cwd: str | None = None,
) -> None:
    r"""FFmpeg을 돌리면서 실제 진척도를 읽어 report()로 넘긴다.

    -progress pipe:1 을 주면 FFmpeg이 표준출력으로 'out_time_us=1234567' 같은 줄을
    주기적으로 뿜는다. 이걸 전체 길이로 나누면 진짜 진행률이 나온다 (타이머로 흉내내지 않는다).

    취소되면 report()가 JobCancelled를 던지는데, 그때 FFmpeg 프로세스를 확실히 죽인다.
    안 그러면 화면상으론 취소됐는데 CPU는 계속 돌아간다.
    """
    total = max(0.1, float(total_seconds))

    # stderr는 파일로 받는다. 파이프로 받아 놓고 안 읽으면 버퍼가 차서 FFmpeg이 멈춰 버린다.
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=err_file,
                stdin=subprocess.DEVNULL,
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise RenderError(f"영상 처리 도구를 실행하지 못했습니다: {exc}") from exc

        # 준비 단계에서 이미 base 만큼 진행했으므로, 여기서는 base~1.0 구간만 채운다.
        # (그냥 0부터 다시 세면 화면의 진행 막대가 뒤로 물러나 보인다)
        span = max(0.0, 1.0 - base)
        report(base, f"{verb} (0초 / {_fmt_time(total)})")
        use_us = False  # out_time_us 가 있으면 그걸 쓰고, 없으면 out_time_ms 를 쓴다

        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                matched = _PROGRESS_LINE.match(raw.strip())
                if matched is None:
                    continue
                key, value = matched.group(1), matched.group(2).strip()

                if key == "out_time_us":
                    use_us = True
                elif key != "out_time_ms" or use_us:
                    continue

                # 주의: FFmpeg의 out_time_ms 는 이름과 달리 실제로는 마이크로초 값이다.
                try:
                    done = int(value) / 1_000_000.0
                except ValueError:
                    continue  # 'N/A' 인 경우가 있다
                if done < 0:
                    continue

                fraction = min(done / total, 1.0)
                report(
                    base + span * fraction,
                    f"{verb} ({_fmt_time(min(done, total))} / {_fmt_time(total)})",
                )

            returncode = proc.wait(timeout=60)
        except JobCancelled:
            proc.kill()
            proc.wait(timeout=15)
            raise
        except BaseException:
            proc.kill()
            proc.wait(timeout=15)
            raise
        finally:
            if proc.stdout is not None:
                proc.stdout.close()

        if returncode != 0:
            err_file.seek(0)
            detail = err_file.read().strip().splitlines()
            tail = " / ".join(detail[-3:])[:300] if detail else f"오류 코드 {returncode}"
            raise RenderError(f"영상을 만들지 못했습니다: {tail}")
    finally:
        err_file.close()


# ── 4) 자막 번인 (F-50) / 미리보기 렌더 (F-54) ─────────────
def _unique_out_path(out_dir: Path, filename: str) -> Path:
    """out/ 폴더 안에서 겹치지 않는 파일 이름을 고른다. 기존 결과물을 지우지 않는다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate = out_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for n in range(2, 1000):
        candidate = out_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
    raise RenderError("결과 파일 이름을 정하지 못했습니다. out 폴더를 정리해 주세요.")


def burn_subtitles(
    report: Reporter | None = None,
    *,
    video_path: str | Path,
    segments: list[dict[str, Any]],
    style: dict[str, Any],
    out_dir: str | Path,
    out_name: str = "자막영상.mp4",
    seconds: float | None = None,
    fast: bool = False,
    output: dict[str, Any] | None = None,
    effects_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """영상에 자막을 새겨 넣어 새 mp4를 만든다 (TECH_SPEC 7절 2번, F-50).

    인자:
        report   : jobs가 넘겨주는 진행률 보고 함수 (없으면 그냥 무시)
        segments : 자막 목록 [{"start":1.2, "end":3.8, "text":"..."}, ...]
        style    : 자막 스타일 사전 (style_map 형식)
        out_dir  : 프로젝트의 out/ 폴더
        seconds  : 앞부분 몇 초만 만들지 (미리보기용, None이면 전체)
        fast     : True면 화질을 조금 낮추고 빠르게 (미리보기용)
        output   : 출력 화면비 설정 (framing 형식). None이면 원본 크기 그대로

    돌려주는 값: {"path", "filename", "duration", "elapsed", "width", "height", "ass", "framing"}
    """
    report = report or _noop
    _require("ffmpeg")

    source = Path(video_path)
    if not source.is_file():
        raise RenderError(f"영상 파일이 없습니다: {source}")

    # N-05: 결과는 항상 '아직 없는' 새 파일에만 쓴다. 그래서 원본은 물론이고
    # 이전에 내보낸 결과물도 절대 덮어쓰이지 않는다.
    out_folder = Path(out_dir)
    final_path = _unique_out_path(out_folder, out_name)

    report(0.01, "영상 정보를 확인하고 있습니다…")

    from app.core.ffprobe import ProbeError, measure_duration  # 순환 import 방지용 지연 import

    src_width, src_height = video_dimensions(source)
    try:
        full_duration = measure_duration(source)
    except ProbeError as exc:
        raise RenderError(str(exc)) from exc

    target_duration = min(full_duration, float(seconds)) if seconds else full_duration

    # 화면비를 바꾸는 경우, 자막은 **잘라낸 뒤의 크기**를 기준으로 만들어야 한다.
    # 원본 크기로 만들면 글자 크기와 위치가 전부 어긋난다 (framing.py 첫 부분 설명 참고).
    frame = framing.resolve(src_width, src_height, output)
    width, height = frame["width"], frame["height"]

    report(0.02, "자막 파일을 만들고 있습니다…")
    # 자막 파일 이름에서 필터 특수문자를 걸러 낸다 (이 이름은 필터 인자로 들어간다)
    ass_stem = "".join("_" if ch in _FILTER_SPECIALS else ch for ch in final_path.stem)
    ass_path = write_ass_file(out_folder / (ass_stem + ".ass"), segments, style, width, height)

    # 임시 이름으로 먼저 쓴다 — 실패하거나 취소되면 완성된 척하는 반쪽 파일이 남지 않는다 (N-05)
    tmp_path = out_folder / f".{final_path.stem}.tmp{final_path.suffix}"
    tmp_path.unlink(missing_ok=True)

    # 자막 필터를 쓰면 화면을 다시 그려야 하므로 영상 재인코딩이 필수다 (-c:v copy 불가).
    # 소리는 그대로 두므로 복사해서 시간을 아낀다.
    # fontsdir로 번들 폰트 폴더를 알려 주지 않으면 한글이 네모(□)로 나온다 (R4).
    workdir, ass_arg, fonts_arg = _filter_paths(ass_path)
    subtitle_filter = f"ass={ass_arg}:fontsdir={fonts_arg}"

    # 화면 효과는 **잘라내기 뒤, 자막 앞**에 온다.
    #   · 잘라내기 뒤인 이유: 효과를 출력 크기(더 작다)에만 걸면 되어 빠르다.
    #   · 자막 앞인 이유: 효과가 자막 위에 오면 글자가 가려 읽기 어려워진다.
    effect_filter = effects.build_filter(
        effects.normalize(effects_list, duration=target_duration),
        width, height, video_fps(source),
    )

    # 자르기가 먼저, 자막이 나중이다. 순서가 반대면 방금 새긴 자막이 잘려 나간다.
    video_filter = framing.chain(frame["filter"], effect_filter, subtitle_filter)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source)]
    if seconds:
        cmd += ["-t", f"{target_duration:.3f}"]
    cmd += [
        "-vf", video_filter,
        "-c:v", "libx264",
        "-crf", "23" if fast else "20",
        "-preset", "veryfast" if fast else "medium",
        "-pix_fmt", "yuv420p",   # 어떤 재생기에서도 열리는 표준 색 형식
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(tmp_path),
    ]

    started = time.monotonic()
    try:
        _run_with_progress(
            cmd, target_duration, report, "영상을 만들고 있습니다", base=0.05, cwd=workdir
        )
        if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            raise RenderError("영상이 만들어지지 않았습니다. 원본 파일을 확인해 주세요.")
        os.replace(tmp_path, final_path)  # 성공했을 때만 최종 이름으로 바꾼다
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    elapsed = time.monotonic() - started
    report(1.0, f"완성했습니다: {final_path.name}")

    return {
        "path": str(final_path),
        "filename": final_path.name,
        "duration": round(target_duration, 3),
        "elapsed": round(elapsed, 2),
        "width": width,
        "height": height,
        "source_width": src_width,
        "source_height": src_height,
        "ass": str(ass_path),
        "framing": {"aspect": frame["aspect"], "fit": frame["fit"], "changed": frame["changed"]},
    }


def render_preview(
    report: Reporter | None = None,
    *,
    video_path: str | Path,
    segments: list[dict[str, Any]],
    style: dict[str, Any],
    out_dir: str | Path,
    seconds: float = 10.0,
    out_name: str = "미리보기.mp4",
    output: dict[str, Any] | None = None,
    effects_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """앞부분 몇 초만 자막을 넣어 빠르게 만들어 본다 (F-54).

    몇 분짜리 영상을 다 만들고 나서야 자막이 마음에 안 든다는 걸 알면 시간이 아깝다.
    그래서 앞 10초만 낮은 화질·빠른 설정으로 먼저 확인하게 한다.
    화면비도 실제 내보내기와 똑같이 적용된다 — 그래야 미리보기의 뜻이 있다.
    """
    return burn_subtitles(
        report,
        video_path=video_path,
        segments=segments,
        style=style,
        out_dir=out_dir,
        out_name=out_name,
        seconds=seconds,
        fast=True,
        output=output,
        effects_list=effects_list,
    )
