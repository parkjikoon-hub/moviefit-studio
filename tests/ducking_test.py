"""자동 덕킹 점검 — 나레이션이 말하는 동안 원본 소리가 실제로 줄어드는가.

`docs/ROADMAP.md` Phase 4 수용 기준:
    "덕킹을 켜면 나레이션 구간의 원본 소리가 실제로 줄어든다 (파형 확인)"

사용법:
    1) 서버를 띄운다              python -m app --port 8766
    2) 시험용 영상을 만든다       python tools/make_sample.py
    3) 이 파일을 실행한다         set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                                  python tests/ducking_test.py

    ※ 나레이션 생성에 edge-tts 를 쓰므로 **인터넷이 필요하다.**

──────────────────────────────────────────────────────────────────────
어떻게 재는가 — 섞인 소리에서 원본만 골라내는 방법

`sample_10s.mp4` 의 소리는 **440Hz 사인파 하나뿐**이다 (tools/make_sample.py).
그래서 결과물을 주파수로 갈라내면 두 소리를 따로 잴 수 있다:

    440Hz 대역만 통과   → 남는 것은 **원본 소리**
    900Hz 위만 통과     → 남는 것은 **나레이션**(사람 목소리)

이렇게 하면 "나레이션이 말하는 순간에 원본이 눌리는가"를 직접 볼 수 있다.
소리 크기 전체를 재면 나레이션 소리가 더해져서 오히려 커지므로 아무것도
증명하지 못한다 — 반드시 갈라서 재야 한다.

──────────────────────────────────────────────────────────────────────
왜 대조군이 필요한가

덕킹을 켠 영상 하나만 재서 "원본이 흔들렸다"고 말하면 안 된다. 그 흔들림이
덕킹 때문인지, 인코딩이나 측정 방법 때문인지 구분할 수 없기 때문이다.
그래서 **덕킹을 끈 영상(원본 100%)을 똑같은 방법으로 재서** 그쪽은 평탄한지
함께 확인한다. 대조군이 평탄한데 실험군만 눌렸다면, 그 차이는 덕킹이 만든 것이다.

이 프로젝트가 반복해서 데인 것이 "오류 없이 조용히 틀리는" 결함이다
(memory/fps-filter-eats-the-first-images.md). 덕킹도 필터가 아무 일을 안 해도
FFmpeg 은 종료 코드 0으로 끝나고 영상은 멀쩡히 나온다.
"""

from __future__ import annotations

import array
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 윈도우 명령창은 cp949라 그냥 출력하면 한글이 깨지거나 죽는다 (memory/windows-console-encoding.md)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"

# 나레이션을 영상(10초)보다 짧게 만든다. 뒤쪽에 나레이션이 없는 구간이 남아야
# "나레이션이 없을 때의 원본 크기"를 잴 수 있다. release=400ms 인 압축기는
# 문장 사이 0.3초 틈에서는 다 풀리지 않으므로, 긴 꼬리가 반드시 필요하다.
SCRIPT = "덕킹 점검용 첫 문장입니다. 원본 소리가 줄어드는지 봅니다."

SAMPLE_RATE = 8000  # 440Hz 를 재기에 충분하다 (나이퀴스트 4000Hz)
WINDOW = 0.10  # 0.1초씩 끊어서 잰다

passed: list[str] = []
failed: list[str] = []
made_projects: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
    return bool(ok)


def req(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=600) as res:
            raw = res.read().decode("utf-8")
            return res.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:300]}


def wait_job(job_id: str, timeout: float = 600.0):
    started = time.time()
    while time.time() - started < timeout:
        status, job = req(f"/api/jobs/{job_id}")
        if status != 200:
            return None, f"작업 조회 실패 HTTP {status}"
        if job["status"] == "done":
            return job["result"], None
        if job["status"] == "error":
            return None, job.get("error") or "알 수 없는 오류"
        if job["status"] == "cancelled":
            return None, "취소됨"
        time.sleep(1.0)
    return None, "시간이 너무 오래 걸려 중단했습니다"


def band_rms(path: Path, audio_filter: str) -> list[float]:
    """영상의 소리를 걸러낸 뒤 0.1초 창마다 소리 크기(RMS)를 재서 목록으로 준다.

    RMS = 그 구간 소리의 실효 크기. 순간값이 아니라 구간 전체의 세기를 나타낸다.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-af", audio_filter,
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
        ],
        capture_output=True,
    )
    raw = proc.stdout
    if not raw:
        raise RuntimeError(f"소리를 읽지 못했습니다: {proc.stderr.decode('utf-8', 'replace')[:200]}")

    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])

    n = int(SAMPLE_RATE * WINDOW)
    out: list[float] = []
    for i in range(0, len(samples) - n + 1, n):
        total = 0
        for v in samples[i : i + n]:
            total += v * v
        out.append((total / n) ** 0.5)
    return out


# 440Hz 사인파(원본)만 남긴다. width_type=h 는 폭을 Hz 로 준다는 뜻이다.
FILTER_ORIGINAL = "bandpass=f=440:width_type=h:w=30"
# 900Hz 위만 남긴다. 두 번 겹쳐 440Hz 를 확실히 지운다 → 남는 것은 사람 목소리
FILTER_NARRATION = "highpass=f=900,highpass=f=900"


def measure(path: Path) -> tuple[list[float], list[float]]:
    return band_rms(path, FILTER_ORIGINAL), band_rms(path, FILTER_NARRATION)


def split_windows(narr_sec: float, video_sec: float, count: int) -> tuple[list[int], list[int]]:
    """창들을 '나레이션이 말하는 중'과 '나레이션이 끝난 뒤'로 나눈다.

    소리 크기로 나누지 않고 **시각으로** 나눈다. 440Hz 사인파는 아무리 높은 대역만
    통과시켜도 찌꺼기가 남아서(2278 × 24dB 감쇠 ≈ 143) '조용함' 기준을 넘어 버린다.
    실제로 그 방식으로 재 보니 조용한 창이 100개 중 2개밖에 안 잡혔다.

    대신 양 끝을 넉넉히 잘라 낸다:
      · 앞뒤 0.5초 — 페이드나 인코딩 경계의 영향을 피한다
      · 나레이션이 끝난 뒤 1.0초 — 압축기가 풀리는 시간(release=400ms)을 기다린다

    이 구간 나누기가 옳은지는 [3]에서 나레이션 신호로 따로 확인한다.
    """
    start = int(0.5 / WINDOW)
    speak_end = int(max(0.0, narr_sec - 0.5) / WINDOW)
    quiet_start = int((narr_sec + 1.0) / WINDOW)
    quiet_end = int(max(0.0, video_sec - 0.5) / WINDOW)

    loud = [i for i in range(start, min(speak_end, count))]
    quiet = [i for i in range(quiet_start, min(quiet_end, count))]
    return loud, quiet


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> int:
    print("\n" + "=" * 70)
    print("  자동 덕킹 점검 — 나레이션 구간에서 원본 소리가 실제로 줄어드는가")
    print("=" * 70)
    print(f"  서버: {BASE}")

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    if not SAMPLE_VIDEO.is_file():
        print(f"  시험용 영상이 없습니다: {SAMPLE_VIDEO}")
        print("  python tools/make_sample.py 를 먼저 실행하세요.")
        return 1

    # ── 1. 준비: 프로젝트와 나레이션 ─────────────────────
    print("\n[1] 준비 — 프로젝트와 나레이션 만들기")
    status, proj = req(
        "/api/projects", "POST",
        {"name": "덕킹시험", "video_path": str(SAMPLE_VIDEO), "mode": "script"},
    )
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made_projects.append(pid)

    proj["script"] = SCRIPT
    req(f"/api/projects/{pid}", "PUT", proj)

    status, started = req(f"/api/projects/{pid}/narration", "POST", {"script": SCRIPT})
    if not check("나레이션 생성 시작", status == 200, f"HTTP {status}"):
        return 1
    result, error = wait_job(started["job_id"])
    if not check("나레이션 생성 완료 (인터넷 필요)", result is not None, error or ""):
        return 1

    status, info = req(f"/api/projects/{pid}/narration/status")
    narr_sec = info.get("narration_seconds") or 0
    video_sec = info.get("video_seconds") or 0
    check(
        "나레이션이 영상보다 짧다 (조용한 꼬리 구간이 있어야 잴 수 있다)",
        0 < narr_sec < video_sec - 1.5,
        f"나레이션 {narr_sec}초 / 영상 {video_sec}초",
    )

    # ── 2. 대조군과 세 단계 만들기 ───────────────────────
    print("\n[2] 영상 만들기 — 덕킹 끔(대조군) + 세기 3단계")

    def export(label: str, body: dict) -> Path | None:
        status, started = req(f"/api/projects/{pid}/narration/export", "POST", body)
        if not check(f"{label} 내보내기 시작", status == 200, f"HTTP {status}"):
            return None
        result, error = wait_job(started["job_id"])
        if not check(f"{label} 영상 생성", result is not None, error or ""):
            return None
        return Path(result["path"])

    flat_path = export("덕킹 끔(대조군)", {"kind": "video", "duck": False, "original_volume": 100})
    if flat_path is None:
        return 1

    level_paths: dict[str, Path] = {}
    for level, name in (("weak", "약하게"), ("normal", "보통"), ("strong", "많이")):
        path = export(f"덕킹 {name}", {"kind": "video", "duck": True, "duck_level": level})
        if path is None:
            return 1
        level_paths[level] = path

    check("네 영상이 모두 다른 파일이다",
          len({flat_path, *level_paths.values()}) == 4,
          ", ".join(p.name for p in level_paths.values()))

    # ── 3. 소리를 갈라서 잰다 ────────────────────────────
    print("\n[3] 440Hz(원본)와 900Hz 위(나레이션)를 갈라서 재기")
    try:
        flat_orig, _ = measure(flat_path)
        measured = {lv: measure(p) for lv, p in level_paths.items()}
    except RuntimeError as exc:
        check("소리 측정", False, str(exc))
        return 1

    norm_orig, norm_narr = measured["normal"]
    check("원본(440Hz) 신호가 잡힌다", max(norm_orig) > 100, f"최대 {max(norm_orig):.0f}")
    check("나레이션(900Hz+) 신호가 잡힌다", max(norm_narr) > 100, f"최대 {max(norm_narr):.0f}")

    loud, quiet = split_windows(narr_sec, video_sec, len(norm_orig))
    check(
        "말하는 구간과 조용한 구간이 둘 다 잡혔다",
        len(loud) >= 5 and len(quiet) >= 5,
        f"말하는 창 {len(loud)}개 · 조용한 창 {len(quiet)}개 (창 하나 = {WINDOW}초)",
    )
    if len(loud) < 5 or len(quiet) < 5:
        return 1

    # 시각으로 나눈 구간이 정말 맞는지 확인한다. 나레이션 신호가 앞 구간에서
    # 뚜렷하게 커야 한다. 이게 틀리면 아래 판정 전체가 엉뚱한 것을 잰 것이 된다.
    narr_loud, narr_quiet = mean([norm_narr[i] for i in loud]), mean([norm_narr[i] for i in quiet])
    check(
        "구간 나누기가 옳다 — 앞 구간에서 나레이션이 실제로 말하고 있다",
        narr_loud > narr_quiet * 2.0,
        f"말하는 구간 {narr_loud:.0f} vs 끝난 뒤 {narr_quiet:.0f} (2배 이상이어야 함)",
    )

    def ratio_of(orig: list[float]) -> tuple[float, float, float]:
        lo, qu = mean([orig[i] for i in loud]), mean([orig[i] for i in quiet])
        return lo, qu, (lo / qu if qu else 0.0)

    # ── 4. 핵심 판정 ─────────────────────────────────────
    print("\n[4] 판정 — 세기마다 얼마나 눌리는가")
    flat_loud, flat_quiet, flat_ratio = ratio_of(flat_orig)
    print(f"      덕킹 끔  : 말할 때 {flat_loud:7.1f} / 조용할 때 {flat_quiet:7.1f}  → {flat_ratio:.3f}")

    ratios: dict[str, float] = {}
    for level, name in (("weak", "약하게"), ("normal", "보통 "), ("strong", "많이 ")):
        lo, qu, r = ratio_of(measured[level][0])
        ratios[level] = r
        print(f"      {name}   : 말할 때 {lo:7.1f} / 조용할 때 {qu:7.1f}  → {r:.3f}"
              f"   (원본의 약 {r * 100:.0f}%)")
    print("      (1.000 = 전혀 안 줄어듦 · 0.500 = 절반으로 줄어듦)")

    check(
        "대조군 — 덕킹을 끄면 원본이 평탄하다 (측정·인코딩 탓이 아님을 보임)",
        flat_ratio >= 0.85,
        f"비율 {flat_ratio:.3f} (기준 0.85 이상)",
    )
    for level, name in (("weak", "약하게"), ("normal", "보통"), ("strong", "많이")):
        check(
            f"{name} — 나레이션 구간의 원본이 실제로 줄어든다",
            ratios[level] <= flat_ratio - 0.10,
            f"비율 {ratios[level]:.3f} (대조군 {flat_ratio:.3f})",
        )

    # 세기 단추가 진짜로 세기를 바꾸는가 — 이름만 다르고 결과가 같으면 거짓말이다
    check(
        "세기를 올릴수록 더 많이 줄어든다 (약하게 > 보통 > 많이)",
        ratios["weak"] > ratios["normal"] > ratios["strong"],
        f"약하게 {ratios['weak']:.3f} > 보통 {ratios['normal']:.3f} > 많이 {ratios['strong']:.3f}",
    )
    check(
        "단계 사이 차이가 귀에 들릴 만큼 벌어져 있다",
        (ratios["weak"] - ratios["normal"]) >= 0.05
        and (ratios["normal"] - ratios["strong"]) >= 0.03,
        f"약하게−보통 {ratios['weak'] - ratios['normal']:.3f} · "
        f"보통−많이 {ratios['normal'] - ratios['strong']:.3f}",
    )

    # 덕킹은 '나레이션이 말하는 동안에만' 눌러야 한다. 말이 없는 구간의 원본까지
    # 줄여 버리면 그것은 덕킹이 아니라 그냥 볼륨을 낮춘 것이다.
    for level, name in (("weak", "약하게"), ("normal", "보통"), ("strong", "많이")):
        _, qu, _ = ratio_of(measured[level][0])
        recovery = qu / flat_quiet if flat_quiet else 0.0
        check(
            f"{name} — 나레이션이 없는 구간의 원본은 건드리지 않는다",
            recovery >= 0.85,
            f"{qu:.1f} / 대조군 {flat_quiet:.1f} = {recovery:.3f}",
        )

    print("\n  화면 안내에 적을 값 (app.js 의 DUCK_HINTS):")
    for level, name in (("weak", "약하게"), ("normal", "보통"), ("strong", "많이")):
        print(f"      {name:<5} → 약 {ratios[level] * 100:.0f}%")

    return 0


def cleanup() -> None:
    for pid in made_projects:
        try:
            req(f"/api/projects/{pid}", "DELETE")
        except Exception:
            pass


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    finally:
        cleanup()
        print("\n" + "=" * 70)
        print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
        if failed:
            print("\n  실패한 항목:")
            for name in failed:
                print(f"    - {name}")
        print("=" * 70 + "\n")
    sys.exit(1 if failed else code)
