"""배경음악 점검 — 영상에 음악이 실제로 깔리는가.

사용법:
    1) 서버를 띄운다      python -m app --port 8766
    2) 이 파일을 실행한다  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                          python tests/bgm_test.py

    ※ 인터넷이 필요 없다. 시험용 음악은 이 파일이 직접 만든다.

──────────────────────────────────────────────────────────────────────
어떻게 "깔렸다"를 판정하는가

시험용 음악을 **1500Hz 사인파**로 만든다. 시험 영상의 소리는 **440Hz** 이므로,
결과물에서 주파수로 갈라내면 둘을 따로 잴 수 있다.

  · 440Hz 만 통과  → 원본 소리가 그대로 남아 있는가
  · 1500Hz 만 통과 → 음악이 실제로 들어갔는가

※ 처음에는 음악을 880Hz 로 잡았다가 실패했다. 880 은 440 의 **정확히 2배음**이라,
  음악을 하나도 안 넣어도 그 대역에 소리가 새어 나온다(압축 과정에서 생기는 배음).
  1500Hz 는 440 의 배수가 아니므로(440×3=1320, ×4=1760) 겹치지 않는다.

'파일이 만들어졌다'만 보면 음악이 하나도 안 들어가도 통과한다. 그래서 소리를
갈라서 **양쪽 다** 있는지 확인한다 (덕킹 점검과 같은 방법).
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

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"     # 소리 = 440Hz 사인파
MUSIC = ROOT / "tests" / "sample" / "sample_music_3s.mp3"        # 1500Hz, 일부러 짧게

SAMPLE_RATE = 8000
passed: list[str] = []
failed: list[str] = []
made: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return bool(ok)


def req(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        BASE + urllib.parse.quote(path, safe="/?&=.:%-"), data=data, method=method
    )
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=300) as res:
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


def make_music() -> None:
    """1500Hz 짜리 3초 음악을 만든다 (영상 10초보다 짧아야 '되풀이'를 확인할 수 있다)."""
    MUSIC.parent.mkdir(parents=True, exist_ok=True)
    MUSIC.unlink(missing_ok=True)  # 주파수를 바꿨을 수 있으므로 항상 새로 만든다
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=1500:duration=3", "-c:a", "libmp3lame", "-q:a", "4", str(MUSIC)],
        check=True, capture_output=True,
    )


def band_rms(path: Path, audio_filter: str) -> list[float]:
    """소리를 걸러낸 뒤 0.5초 창마다 크기를 잰다."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-af", audio_filter,
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
    )
    if not proc.stdout:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[:200])
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])

    n = SAMPLE_RATE // 2
    out = []
    for i in range(0, len(samples) - n + 1, n):
        total = sum(v * v for v in samples[i:i + n])
        out.append((total / n) ** 0.5)
    return out


FILTER_ORIGINAL = "bandpass=f=440:width_type=h:w=30"    # 원본 영상의 소리
FILTER_MUSIC = "bandpass=f=1500:width_type=h:w=60"      # 넣은 음악 (440의 배음이 아닌 자리)


def duration_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def main() -> int:
    print("\n" + "=" * 70)
    print("  배경음악 점검 — 영상에 음악이 실제로 깔리는가")
    print("=" * 70)
    print(f"  서버: {BASE}")

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다.")
        return 1
    if not SAMPLE_VIDEO.is_file():
        print(f"  시험 영상이 없습니다: {SAMPLE_VIDEO}  (python tools/make_sample.py)")
        return 1

    make_music()
    check("시험용 음악 준비 (1500Hz · 3초)", MUSIC.is_file(),
          f"{MUSIC.name} · {duration_of(MUSIC):.1f}초")

    # ── 1. 배경음악 없이 (대조군) ────────────────────────
    print("\n[1] 대조군 — 배경음악 없이 자막 영상 만들기")
    status, proj = req("/api/projects", "POST",
                       {"name": "배경음점검", "video_path": str(SAMPLE_VIDEO), "mode": "video"})
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)
    proj["segments"] = [{"id": "s1", "start": 0.5, "end": 3.0, "text": "배경음 시험"}]
    req(f"/api/projects/{pid}", "PUT", proj)

    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if not check("자막 영상 내보내기 시작", status == 200, f"HTTP {status}"):
        return 1
    plain, error = wait_job(started["job_id"])
    if not check("자막 영상 생성", plain is not None, error or ""):
        return 1
    plain_path = Path(plain["path"])
    check("대조군에는 배경음 표시가 없다", not plain.get("bgm"), str(plain.get("bgm")))

    # ── 2. 배경음악을 넣고 ───────────────────────────────
    print("\n[2] 배경음악을 넣고 다시 만들기")
    status, current = req(f"/api/projects/{pid}")
    current["bgm_path"] = str(MUSIC)
    current["bgm_volume"] = 40
    status, _ = req(f"/api/projects/{pid}", "PUT", current)
    check("배경음악 설정 저장", status == 200, f"HTTP {status}")

    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if not check("내보내기 시작", status == 200, f"HTTP {status}"):
        return 1
    withbgm, error = wait_job(started["job_id"])
    if not check("배경음 넣은 영상 생성", withbgm is not None, error or ""):
        return 1
    bgm_path = Path(withbgm["path"])
    check("결과에 배경음 표시가 있다", withbgm.get("bgm") is True, str(withbgm.get("bgm")))
    check("파일 이름에 배경음이 드러난다", "배경음" in bgm_path.name, bgm_path.name)

    # ── 3. 소리를 갈라서 잰다 (핵심) ─────────────────────
    print("\n[3] 판정 — 440Hz(원본)와 1500Hz(음악)를 갈라서 재기")
    try:
        plain_orig = band_rms(plain_path, FILTER_ORIGINAL)
        plain_music = band_rms(plain_path, FILTER_MUSIC)
        bgm_orig = band_rms(bgm_path, FILTER_ORIGINAL)
        bgm_music = band_rms(bgm_path, FILTER_MUSIC)
    except RuntimeError as exc:
        check("소리 측정", False, str(exc))
        return 1

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print(f"      대조군 : 원본 {avg(plain_orig):7.1f} · 음악대역 {avg(plain_music):7.1f}")
    print(f"      배경음 : 원본 {avg(bgm_orig):7.1f} · 음악대역 {avg(bgm_music):7.1f}")

    # 대조군에도 0 이 나오지는 않는다 — 압축과 필터가 남기는 아주 작은 찌꺼기가 있다.
    # 중요한 것은 '0인가'가 아니라 **넣었을 때와 자릿수가 다른가**이다.
    check("대조군에는 음악(1500Hz)이 사실상 없다", avg(plain_music) < 100,
          f"{avg(plain_music):.1f} (소음 바닥 수준)")
    check("배경음 영상에는 음악(1500Hz)이 뚜렷하다",
          avg(bgm_music) > avg(plain_music) * 5 and avg(bgm_music) > 200,
          f"{avg(bgm_music):.1f} — 대조군의 {avg(bgm_music) / max(1, avg(plain_music)):.0f}배")
    # 대조군은 원본 소리를 그대로 복사(-c:a copy)하지만, 배경음을 넣을 때는 다시 섞으면서
    # 모노를 스테레오로 편다. 그때 FFmpeg 이 채널마다 1/√2(-3dB)를 곱한다 —
    # 두 스피커로 갈라도 전체 세기가 같게 유지하려는 표준 동작이라 **귀로는 같은 크기**다
    # (audio_mix.py 의 _COMMON_FMT 주석에 실측이 적혀 있다). 그래서 0.707배를 기준으로 본다.
    ratio = avg(bgm_orig) / avg(plain_orig) if avg(plain_orig) else 0.0
    check("원본 소리도 그대로 남아 있다 (음악이 덮어쓰지 않았다)",
          0.62 <= ratio <= 1.15,
          f"{avg(bgm_orig):.1f} / 대조군 {avg(plain_orig):.1f} = {ratio:.3f} "
          f"(스테레오로 펴면서 생기는 0.707배가 정상)")

    # ── 4. 짧은 음악이 끝까지 되풀이되는가 ───────────────
    print("\n[4] 3초짜리 음악이 10초 영상 끝까지 이어지는가")
    late = bgm_music[len(bgm_music) * 2 // 3:]  # 뒤쪽 3분의 1
    check("영상 뒷부분에도 음악이 있다 (짧은 음악이 되풀이된다)",
          avg(late) > 60, f"뒷부분 평균 {avg(late):.1f}")

    out_sec, src_sec = duration_of(bgm_path), duration_of(SAMPLE_VIDEO)
    check("영상 길이가 변하지 않았다", abs(out_sec - src_sec) < 0.3,
          f"원본 {src_sec:.2f}초 → 결과 {out_sec:.2f}초")

    # ── 5. 음악 파일이 사라졌을 때 ───────────────────────
    print("\n[5] 음악 파일이 사라져도 영상은 나오는가")
    status, current = req(f"/api/projects/{pid}")
    current["bgm_path"] = str(MUSIC.parent / "없는음악.mp3")
    req(f"/api/projects/{pid}", "PUT", current)
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if check("내보내기 시작", status == 200, f"HTTP {status}"):
        result, error = wait_job(started["job_id"])
        check("영상은 그대로 만들어진다 (음악만 빠진다)", result is not None, error or "")
        if result:
            warn = result.get("bgm_warning") or ""
            check("무슨 일이 있었는지 한국어로 알려 준다",
                  "배경음악" in warn, warn[:60])

    return 0


def cleanup() -> None:
    for pid in made:
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
