"""나레이션 오디오 이어 붙이기와 영상에 나레이션 얹기 (F-40 지원 / F-51 / F-52).

기준 명령은 docs/TECH_SPEC.md 7절 3번이다. ffmpeg.py와 마찬가지로 이 파일 밖에서는
ffmpeg을 직접 부르지 않는다.

이 모듈이 신경 쓰는 것:

- D1 (타이밍 정확도): 자막 시간표는 문장별 mp3의 '실측' 길이로 계산된다. 그래서
  이어 붙인 오디오도 그 계산과 밀리초 단위로 맞아야 한다. 어떻게 맞췄는지는
  아래 concat_narration()의 주석에 적어 두었다.
- R6 (윈도우 경로): 인자는 항상 리스트로 넘긴다. 이 모듈의 필터 문자열에는 파일 경로가
  전혀 들어가지 않으므로(오디오 필터는 스트림 이름만 쓴다) memory/ffmpeg-filter-path-escaping.md
  에서 말하는 콜론·쉼표 함정은 여기서는 발생하지 않는다. 앞으로 이 파일에 경로를 받는
  필터(예: amovie)를 추가한다면 그때는 그 메모를 반드시 다시 읽어야 한다.
- N-05 (출력 안전): 임시 이름으로 먼저 쓰고 성공했을 때만 최종 이름으로 바꾼다.

ffmpeg.py의 도우미(_run_with_progress 등)를 그대로 가져다 쓴다. 같은 일을 두 벌
만들면 진행률·취소 처리가 어긋나기 때문에 복사하지 않고 import 한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.core.ffmpeg import (  # 같은 패키지 안의 공용 도우미 재사용
    RenderError,
    Reporter,
    _noop,
    _require,
    _run_with_progress,
    _unique_out_path,
)
from app.core.ffprobe import ProbeError, measure_duration

# 모든 오디오를 이 형식으로 맞춘 뒤에 섞는다.
# amix·sidechaincompress는 입력들의 샘플레이트·채널 배치가 다르면 아예 동작하지 않거나
# 엉뚱한 결과를 낸다. edge-tts 결과물은 보통 24kHz 모노, 영상 소리는 48kHz 스테레오라
# 실제로 자주 어긋난다. 그래서 섞기 직전에 강제로 통일한다.
#
# 알아 둘 점(실측): 모노 → 스테레오로 바꿀 때 FFmpeg은 채널마다 1/√2(-3dB)를 곱한다.
# 두 스피커로 갈라 놓아도 전체 세기가 같게 유지하려는 표준 동작이라, 귀로 듣는 크기는
# 그대로다. 다만 숫자로 재면 원본 모노보다 3dB 낮게 나온다. 나레이션과 원본 소리 모두
# 똑같이 적용되므로 둘 사이의 균형(원본 30% 같은 설정)은 정확히 지켜진다.
_COMMON_FMT = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"


def has_audio_stream(path: str | Path) -> bool:
    """영상(또는 오디오) 파일에 소리 트랙이 들어 있는지 확인한다.

    화면 녹화나 무음 편집본에는 소리 트랙이 아예 없는 경우가 흔하다. 그걸 모르고
    [0:a] 를 쓰는 필터를 돌리면 FFmpeg이 "Invalid file index"처럼 원인을 알 수 없는
    영어 오류만 뱉는다. 그래서 미리 확인해서 다른 명령으로 갈라 준다.
    """
    _require("ffprobe")
    src = Path(path)
    if not src.is_file():
        raise RenderError(f"파일이 없습니다: {src}")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "json",
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60)
    if result.returncode != 0:
        raise RenderError(f"소리 트랙을 확인하지 못했습니다: {(result.stderr or '').strip()[:200]}")
    try:
        return bool(json.loads(result.stdout).get("streams"))
    except json.JSONDecodeError:
        return False


def _audio_output_args(out_path: Path) -> list[str]:
    """확장자를 보고 오디오 인코딩 옵션을 정한다 (.wav면 무손실, 그 외는 mp3)."""
    if out_path.suffix.lower() == ".wav":
        # 무손실. 길이 오차가 0에 가까워 타이밍 검증용·후속 편집용으로 좋다.
        return ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
    return ["-c:a", "libmp3lame", "-q:a", "2", "-ar", "44100", "-ac", "2"]


# ── 0) 문장 음성의 앞뒤 무음 잘라내기 ──────────────────────
# 왜 필요한가 (실측으로 확인된 문제):
# edge-tts가 돌려주는 mp3는 말이 시작되기 전에 0.21초쯤, 말이 끝난 뒤에 0.9초쯤
# 무음을 붙여서 준다. 이걸 그대로 두면
#   ① "문장 사이 간격 0.3초" 설정이 실제로는 1.4초가 되고
#   ② 말이 끝난 뒤에도 자막이 0.9초 더 떠 있어 어색하다.
# 그래서 음성을 만든 직후 앞뒤 무음을 잘라 낸다. 그러면 잰 길이가 곧 '말하는 시간'이 되고
# 사용자가 정한 간격이 화면에서도 그대로 지켜진다.
TRIM_PAD = 0.06  # 말이 뚝 잘린 느낌이 나지 않게 앞뒤로 남겨 두는 여유(초)


def trim_silence(path: str | Path, pad: float = TRIM_PAD) -> dict[str, Any]:
    """오디오 파일의 앞뒤 무음을 잘라 같은 자리에 다시 쓴다.

    돌려주는 값: {"trimmed": bool, "before": 원래길이, "after": 자른뒤길이,
                  "head": 앞에서 자른 초, "tail": 뒤에서 자른 초}
    말소리를 찾지 못하면 원본을 그대로 둔다 (자르는 것보다 두는 편이 안전하다).
    """
    from app.core import audio_analysis

    _require("ffmpeg")
    src = Path(path)
    if not src.is_file():
        raise RenderError(f"파일이 없습니다: {src}")

    before = measure_duration(src)

    try:
        # 나레이션은 문장 하나짜리 짧은 파일이라 기준을 촘촘하게 잡는다
        regions = audio_analysis.detect_speech_regions(
            src, noise_db=-40.0, min_silence=0.12, min_speech=0.08
        )
    except Exception:
        return {"trimmed": False, "before": before, "after": before, "head": 0.0, "tail": 0.0}

    if not regions:
        return {"trimmed": False, "before": before, "after": before, "head": 0.0, "tail": 0.0}

    start = max(0.0, float(regions[0]["start"]) - pad)
    end = min(before, float(regions[-1]["end"]) + pad)
    if end - start < 0.05 or (start < 0.02 and before - end < 0.02):
        # 잘라 낼 것이 거의 없다
        return {"trimmed": False, "before": before, "after": before, "head": 0.0, "tail": 0.0}

    tmp = src.with_name(src.stem + ".trim.tmp" + src.suffix)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(src),
        *_audio_output_args(src),
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120)
    if result.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return {"trimmed": False, "before": before, "after": before, "head": 0.0, "tail": 0.0}

    os.replace(tmp, src)
    after = measure_duration(src)
    return {
        "trimmed": True,
        "before": round(before, 3),
        "after": round(after, 3),
        "head": round(start, 3),
        "tail": round(before - end, 3),
    }


# ── 1) 문장별 나레이션을 하나로 이어 붙이기 (F-40 지원 / F-52) ──
def concat_narration(
    report: Reporter | None = None,
    *,
    clips: list[dict[str, Any]],
    out_path: str | Path,
) -> dict[str, Any]:
    """문장별 mp3들을 지정한 간격으로 이어 붙여 하나의 오디오 파일로 만든다.

    인자:
        report   : jobs가 넘겨주는 진행률 보고 함수 (없으면 무시)
        clips    : [{"path": "...mp3", "gap_after": 0.3}, ...] 순서대로.
                   gap_after는 '그 문장 뒤에 넣을 무음(초)'이다.
                   맨 마지막 문장의 gap_after는 무시한다 (파일 끝에 무음을 달지 않는다).
        out_path : 결과 파일 경로. 확장자가 .wav면 무손실 wav, 아니면 mp3로 만든다.
                   (F-52 '나레이션 오디오만 저장'도 이 함수를 그대로 쓴다.)

    돌려주는 값:
        {"path", "duration", "expected_duration", "error_ms", "elapsed", "parts"}
        parts는 [{"index","path","start","end","duration","gap_after"}, ...] 로,
        자막 타이밍 계산에 그대로 쓸 수 있는 각 문장의 시작·끝 시각이다.

    왜 concat이 아니라 adelay + amix인가 (D1 정확도 때문에 중요):
        방법이 크게 두 가지다.
        (가) concat 데먹서로 mp3를 무음 파일과 함께 그냥 이어 붙이기 —— 빠르지만
             mp3는 파일마다 앞뒤에 인코더가 넣은 여백(encoder delay/padding)이 붙어
             있어서, 문장 수만큼 그 오차가 '누적'된다. 문장이 50개면 수백 밀리초가
             밀릴 수 있다.
        (나) 각 문장을 adelay로 '절대 시각'에 배치하고 amix로 합치기 —— 오차가
             누적되지 않는다. 3번째 문장은 언제나 정확히 (앞 문장 길이 합 + 간격 합)
             지점에서 시작한다.
        이 프로그램은 자막 시간표를 (나)와 똑같은 계산으로 만든다. 그러니 오디오도
        (나)로 배치해야 자막과 소리가 정확히 같은 자리에 온다. 그래서 (나)를 택했다.
        adelay는 밀리초 단위 정수라 문장당 최대 0.5ms의 반올림이 생기지만, 절대 시각
        기준이므로 누적되지 않는다.
    """
    report = report or _noop
    _require("ffmpeg")

    if not clips:
        raise RenderError("이어 붙일 나레이션 파일이 없습니다.")

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # ① 각 문장의 길이를 실측한다 (추정 금지 — D1의 정확도가 여기서 나온다)
    report(0.02, "나레이션 길이를 재고 있습니다…")
    parts: list[dict[str, Any]] = []
    cursor = 0.0
    last = len(clips) - 1
    for i, clip in enumerate(clips):
        src = Path(str(clip.get("path") or ""))
        if not src.is_file():
            raise RenderError(f"나레이션 파일이 없습니다: {src}")
        try:
            duration = measure_duration(src)
        except ProbeError as exc:
            raise RenderError(str(exc)) from exc

        gap = max(0.0, float(clip.get("gap_after") or 0.0))
        parts.append({
            "index": i,
            "path": str(src),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "duration": round(duration, 3),
            "gap_after": round(gap, 3),
        })
        cursor += duration
        if i < last:  # 마지막 문장 뒤의 간격은 파일에 넣지 않는다
            cursor += gap

        report(0.02 + 0.18 * (i + 1) / len(clips), f"나레이션 길이를 재고 있습니다… ({i + 1}/{len(clips)})")

    expected = cursor

    # ② 필터그래프 조립. 여기에는 파일 경로가 들어가지 않는다(스트림 번호만 쓴다).
    chains = []
    labels = []
    for part in parts:
        idx = part["index"]
        delay_ms = int(round(part["start"] * 1000))
        # all=1: 모든 채널에 같은 지연을 준다. 안 붙이면 첫 채널만 밀려서 소리가 어긋난다.
        chains.append(f"[{idx}:a]{_COMMON_FMT},adelay={delay_ms}:all=1[a{idx}]")
        labels.append(f"[a{idx}]")

    if len(parts) == 1:
        filter_complex = chains[0].replace("[a0]", "[mix]")
    else:
        # normalize=0: 켜 두면 amix가 입력 개수만큼 볼륨을 나눠 버려 소리가 확 작아진다.
        # 문장들은 서로 겹치지 않으므로 그냥 더하는 게 맞다.
        filter_complex = (
            ";".join(chains)
            + ";" + "".join(labels)
            + f"amix=inputs={len(parts)}:duration=longest:dropout_transition=0:normalize=0[mix]"
        )

    tmp_path = target.parent / f".{target.stem}.tmp{target.suffix}"
    tmp_path.unlink(missing_ok=True)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin"]
    for part in parts:
        cmd += ["-i", part["path"]]  # 인자는 리스트로 — 한글·공백 경로 안전 (R6)
    cmd += ["-filter_complex", filter_complex, "-map", "[mix]"]
    cmd += _audio_output_args(target)
    cmd += ["-progress", "pipe:1", "-nostats", str(tmp_path)]

    started = time.monotonic()
    try:
        _run_with_progress(cmd, expected, report, "나레이션을 이어 붙이고 있습니다", base=0.2)
        if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            raise RenderError("나레이션 오디오가 만들어지지 않았습니다.")
        os.replace(tmp_path, target)  # 성공했을 때만 최종 이름으로
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    elapsed = time.monotonic() - started

    # ③ 실제로 만들어진 길이를 다시 재서 계산값과 얼마나 어긋났는지 확인한다.
    try:
        actual = measure_duration(target)
    except ProbeError as exc:
        raise RenderError(str(exc)) from exc
    error_ms = round((actual - expected) * 1000.0, 1)

    report(1.0, f"나레이션 오디오를 만들었습니다 ({actual:.2f}초)")

    return {
        "path": str(target),
        "duration": round(actual, 3),
        "expected_duration": round(expected, 3),
        "error_ms": error_ms,
        "elapsed": round(elapsed, 2),
        "parts": parts,
    }


def export_narration_audio(
    report: Reporter | None = None,
    *,
    clips: list[dict[str, Any]],
    out_path: str | Path,
) -> dict[str, Any]:
    """F-52: 영상 없이 나레이션 오디오만 mp3/wav로 내보낸다.

    하는 일은 concat_narration()과 똑같다. 화면의 '나레이션 음성만 저장' 버튼이
    무엇을 부르는지 코드에서 바로 보이도록 이름만 따로 둔 것이다.
    """
    return concat_narration(report, clips=clips, out_path=out_path)


# ── 2) 영상에 나레이션 얹기 (TECH_SPEC 7절 3번, F-51) ──────
def _mix_filter(original_volume: int, duck: bool) -> str:
    """원본 소리와 나레이션을 섞는 필터그래프 문자열을 만든다. (소리 트랙이 있는 영상용)"""
    if duck:
        # P2 자동 덕킹: 나레이션이 말하는 동안에만 원본 소리를 눌러 준다.
        # sidechaincompress는 '본 신호'와 '감지용 신호'의 샘플레이트·채널 배치가
        # 같아야 하므로 양쪽 모두 _COMMON_FMT로 맞춘다.
        # asplit: 나레이션을 두 갈래로 복제해 한 갈래는 감지용, 한 갈래는 실제 소리로 쓴다.
        # apad: 나레이션이 영상보다 짧으면 감지 신호가 먼저 끝나 뒤쪽이 통째로
        #       잘려 나간다. 무음으로 늘려서 영상 끝까지 따라가게 한다.
        return (
            f"[0:a]{_COMMON_FMT}[bg];"
            f"[1:a]{_COMMON_FMT},asplit=2[nar][sckey];"
            "[sckey]apad[sc];"
            "[bg][sc]sidechaincompress="
            "threshold=0.03:ratio=12:attack=15:release=400:makeup=1:level_sc=1[duck];"
            "[duck][nar]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )

    # 기본: 원본 소리를 고정 비율로 낮추고 나레이션을 더한다 (TECH_SPEC 7절 3번).
    # normalize=0을 붙인 이유: 기본값(1)이면 amix가 볼륨을 입력 개수로 나눠서
    # 사용자가 지정한 '원본 30%'가 실제로는 15%가 되고 나레이션도 절반이 된다.
    volume = max(0, min(100, int(original_volume))) / 100.0
    return (
        f"[0:a]{_COMMON_FMT},volume={volume:.3f}[bg];"
        f"[1:a]{_COMMON_FMT}[nar];"
        "[bg][nar]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )


def mix_narration_into_video(
    report: Reporter | None = None,
    *,
    video_path: str | Path,
    narration_path: str | Path,
    out_dir: str | Path,
    out_name: str = "나레이션영상.mp4",
    original_volume: int = 30,
    duck: bool = False,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """영상에 나레이션 오디오를 얹어 새 mp4를 만든다 (F-51).

    인자:
        report          : jobs가 넘겨주는 진행률 보고 함수 (없으면 무시)
        video_path      : 원본 영상
        narration_path  : concat_narration()이 만든 나레이션 오디오
        out_dir         : 프로젝트의 out/ 폴더
        original_volume : 원본 소리를 몇 %로 줄일지 (0~100). duck=True면 무시된다.
        duck            : True면 고정 감쇠 대신 자동 덕킹(나레이션 말하는 동안만 감쇠)
        output          : 출력 화면비 설정 (framing 형식). 화면비를 바꾸지 않으면 None과 같다

    돌려주는 값:
        {"path","filename","duration","elapsed","had_audio","ducked","original_volume","framing"}

    화면비를 바꾸지 않을 때는 화면(비디오)을 손대지 않는다(-c:v copy). 그림을 다시 그릴
    일이 없으므로 재인코딩할 이유가 없고, 그래서 몇 배 빠르고 화질 손실도 없다.
    화면비를 바꿀 때만 어쩔 수 없이 다시 그린다(느려진다).
    """
    report = report or _noop
    _require("ffmpeg")

    source = Path(video_path)
    if not source.is_file():
        raise RenderError(f"영상 파일이 없습니다: {source}")
    narration = Path(narration_path)
    if not narration.is_file():
        raise RenderError(f"나레이션 오디오 파일이 없습니다: {narration}")

    volume_pct = max(0, min(100, int(original_volume)))

    out_folder = Path(out_dir)
    final_path = _unique_out_path(out_folder, out_name)

    report(0.01, "영상 정보를 확인하고 있습니다…")
    try:
        video_duration = measure_duration(source)
        narration_duration = measure_duration(narration)
    except ProbeError as exc:
        raise RenderError(str(exc)) from exc

    had_audio = has_audio_stream(source)

    # 화면비를 바꿔야 하는지 먼저 본다. 바꿀 필요가 없으면 지금까지처럼 화면을 그대로 복사한다.
    from app.core import framing
    from app.core.ffmpeg import video_dimensions

    src_w, src_h = video_dimensions(source)
    frame = framing.resolve(src_w, src_h, output)
    reframe = bool(frame["filter"])

    tmp_path = out_folder / f".{final_path.stem}.tmp{final_path.suffix}"
    tmp_path.unlink(missing_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source),
        "-i", str(narration),
    ]

    if had_audio:
        # 소리를 섞을 때는 filter_complex를 쓰므로 화면 필터도 같은 자리에 함께 넣어야 한다.
        # (-filter_complex 와 -vf 를 동시에 쓰면 FFmpeg이 거부한다.)
        graph = _mix_filter(volume_pct, duck)
        if reframe:
            graph += f";[0:v]{frame['filter']}[v]"
        cmd += ["-filter_complex", graph, "-map", "[v]" if reframe else "0:v", "-map", "[a]"]
    else:
        # 원본에 소리 트랙이 없으면 섞을 게 없다. 나레이션이 그대로 영상의 소리가 된다.
        # (여기서 [0:a]를 쓰는 필터를 돌리면 FFmpeg이 영문 오류를 내며 죽는다.)
        cmd += ["-map", "0:v", "-map", "1:a"]
        if reframe:
            cmd += ["-vf", frame["filter"]]
        if narration_duration > video_duration:
            # 나레이션이 영상보다 길면 화면 없이 소리만 남는 꼬리가 생긴다. 영상 길이에서 자른다.
            cmd += ["-t", f"{video_duration:.3f}"]

    if reframe:
        # 화면을 잘라 내려면 그림을 다시 그려야 하므로 재인코딩이 불가피하다.
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]  # 화면은 그대로 복사 — 재인코딩 없음 (빠르고 무손실)

    cmd += [
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(tmp_path),
    ]

    if reframe:
        verb = "화면비를 맞추고 나레이션을 합치고 있습니다"
    else:
        verb = "나레이션을 합치고 있습니다" if had_audio else "나레이션을 영상에 넣고 있습니다"
    started = time.monotonic()
    try:
        _run_with_progress(cmd, video_duration, report, verb, base=0.05)
        if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            raise RenderError("영상이 만들어지지 않았습니다. 원본 파일을 확인해 주세요.")
        os.replace(tmp_path, final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    elapsed = time.monotonic() - started
    try:
        out_duration = measure_duration(final_path)
    except ProbeError:
        out_duration = video_duration

    report(1.0, f"완성했습니다: {final_path.name}")

    return {
        "path": str(final_path),
        "filename": final_path.name,
        "duration": round(out_duration, 3),
        "elapsed": round(elapsed, 2),
        "had_audio": had_audio,
        "ducked": bool(duck),
        "original_volume": volume_pct,
        "width": frame["width"],
        "height": frame["height"],
        "framing": {"aspect": frame["aspect"], "fit": frame["fit"], "changed": frame["changed"]},
    }
