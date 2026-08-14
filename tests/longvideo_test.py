"""긴 영상 점검 — 30분짜리 영상에서 음성인식과 내보내기가 끝나는가, 진행률이 정직한가.

`docs/ROADMAP.md` Phase 5 수용 기준:
    "30분 영상에서 STT·렌더링이 완료되고 진행률이 정확하다"

사용법:
    1) 서버를 띄운다        python -m app --port 8766
    2) 30분 영상을 만든다    python tools/make_sample_long.py
    3) 이 파일을 실행한다    set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                            python tests/longvideo_test.py

    ※ **오래 걸린다.** 음성인식과 다시 인코딩을 각각 30분 분량으로 하기 때문이다.
      컴퓨터에 따라 10~40분을 잡아야 한다. 인터넷은 필요 없다.
    ※ 음성인식 모델을 처음 쓰는 컴퓨터라면 내려받느라 6분쯤 더 걸린다
      (memory/whisper-first-run-is-slow.md).

──────────────────────────────────────────────────────────────────────
"진행률이 정확하다"를 어떻게 판정하는가

진행률은 거짓말하기 가장 쉬운 부분이다. 타이머로 숫자만 올려도 사용자는
알아채지 못한다. 그래서 네 가지를 함께 본다:

  ① 뒤로 가지 않는다            (99% → 40% 같은 일이 없다)
  ② 서로 다른 값이 여러 번 나온다 (0% 에 멈춰 있다가 100% 로 튀지 않는다)
  ③ 절반쯤 지났을 때 진행률도 중간쯤이다 (앞에서 99% 를 찍고 오래 머물지 않는다)
  ④ **결과가 영상 전체를 덮는다**  ← 가장 중요하다

④가 핵심인 이유: 앞부분 5분만 처리하고 "완료"라고 말해도 ①②③은 모두 통과한다.
이 프로젝트는 "오류 없이 조용히 앞부분만 처리되는" 결함을 이미 겪었다
(memory/fps-filter-eats-the-first-images.md). 그래서 자막이 영상 끝까지
붙어 있는지, 내보낸 영상의 길이가 원본과 같은지를 반드시 확인한다.
"""

from __future__ import annotations

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
LONG_VIDEO = ROOT / "tests" / "sample" / "sample_30min.mp4"

passed: list[str] = []
failed: list[str] = []
made: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


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


def run_job(label: str, job_id: str, timeout: float = 3600.0):
    """작업을 기다리면서 (경과초, 진행률) 을 계속 기록한다."""
    samples: list[tuple[float, int]] = []
    started = time.time()
    last_print = 0.0
    while time.time() - started < timeout:
        status, job = req(f"/api/jobs/{job_id}")
        if status != 200:
            return None, f"작업 조회 실패 HTTP {status}", samples
        elapsed = time.time() - started
        samples.append((elapsed, int(job.get("percent") or 0)))
        if elapsed - last_print >= 20:
            print(f"      {elapsed:6.0f}초   {job.get('percent'):>3}%   {job.get('message','')[:50]}")
            last_print = elapsed
        if job["status"] == "done":
            print(f"      {elapsed:6.0f}초   완료")
            return job["result"], None, samples
        if job["status"] == "error":
            return None, job.get("error") or "알 수 없는 오류", samples
        if job["status"] == "cancelled":
            return None, "취소됨", samples
        time.sleep(2.0)
    return None, f"{timeout / 60:.0f}분을 넘겨 중단했습니다", samples


def judge_progress(label: str, samples: list[tuple[float, int]]) -> None:
    """진행률이 정직한지 본다."""
    values = [p for _, p in samples]
    if not values:
        check(f"{label}: 진행률을 읽었다", False, "표본 없음")
        return

    check(
        f"{label}: 진행률이 뒤로 가지 않는다",
        all(b >= a for a, b in zip(values, values[1:])),
        f"표본 {len(values)}개",
    )
    distinct = sorted(set(values))
    check(
        f"{label}: 진행률이 여러 단계로 올라간다 (0%에서 100%로 튀지 않는다)",
        len(distinct) >= 5,
        f"서로 다른 값 {len(distinct)}개 {distinct[:8]}{'...' if len(distinct) > 8 else ''}",
    )

    total = samples[-1][0]
    if total > 0:
        mid = [p for t, p in samples if t <= total / 2]
        mid_percent = mid[-1] if mid else 0
        check(
            f"{label}: 시간이 절반 지났을 때 진행률도 중간쯤이다",
            10 <= mid_percent <= 90,
            f"절반 시점({total / 2:.0f}초)에 {mid_percent}%",
        )


def main() -> int:
    print("\n" + "=" * 70)
    print("  긴 영상 점검 — 30분 영상에서 음성인식·내보내기와 진행률")
    print("=" * 70)
    print(f"  서버: {BASE}")

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    if not LONG_VIDEO.is_file():
        print(f"  30분 시험용 영상이 없습니다: {LONG_VIDEO}")
        print("  python tools/make_sample_long.py 를 먼저 실행하세요.")
        return 1

    source_seconds = duration_of(LONG_VIDEO)
    print(f"  시험용 영상: {source_seconds / 60:.1f}분 ({source_seconds:.1f}초), "
          f"{LONG_VIDEO.stat().st_size / 1024 / 1024:.0f}MB")
    check("시험용 영상이 30분 이상이다", source_seconds >= 1800, f"{source_seconds:.1f}초")

    status, proj = req("/api/projects", "POST",
                       {"name": "긴영상점검", "video_path": str(LONG_VIDEO), "mode": "video"})
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)

    # ── 1. 음성인식 ──────────────────────────────────────
    print("\n[1] 30분 영상 음성인식 (오래 걸립니다)")
    status, started = req(f"/api/projects/{pid}/stt", "POST", {"language": "ko", "model": "small"})
    if not check("음성인식 시작", status == 200, f"HTTP {status}"):
        return 1

    t0 = time.time()
    result, error, samples = run_job("음성인식", started["job_id"])
    stt_seconds = time.time() - t0
    if not check("음성인식이 끝까지 완료된다", result is not None, error or ""):
        return 1

    segments = result.get("segments") or []
    print(f"      걸린 시간 {stt_seconds / 60:.1f}분 · 자막 {len(segments)}개 "
          f"· 실시간 대비 {source_seconds / stt_seconds:.1f}배속")
    check("자막이 만들어졌다", len(segments) > 10, f"{len(segments)}개")

    judge_progress("음성인식", samples)

    # ④ 결과가 영상 전체를 덮는가 — 앞부분만 처리하고 끝내지 않았는지
    last_end = max((s.get("end") or 0) for s in segments) if segments else 0
    check(
        "자막이 영상 끝까지 있다 (앞부분만 처리하고 끝내지 않았다)",
        last_end >= source_seconds - 60,
        f"마지막 자막이 {last_end:.0f}초 (영상 {source_seconds:.0f}초)",
    )

    # 음성인식은 결과를 돌려주기만 하고 프로젝트에 저장하지는 않는다.
    # 실제 화면에서는 브라우저가 결과를 받아 저장한다. 점검도 똑같이 해야
    # 다음 단계(내보내기)가 자막을 찾을 수 있다 — 안 하면 "내보낼 자막이
    # 없습니다"라는 400 이 돌아온다.
    status, current = req(f"/api/projects/{pid}")
    current["segments"] = segments
    status, _ = req(f"/api/projects/{pid}", "PUT", current)
    check("음성인식 결과를 프로젝트에 저장한다", status == 200, f"HTTP {status}")

    # ── 2. 자막 입힌 영상 내보내기 ───────────────────────
    print("\n[2] 30분 영상에 자막 새겨 내보내기 (오래 걸립니다)")
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if not check("내보내기 시작", status == 200, f"HTTP {status}"):
        return 1

    t0 = time.time()
    result, error, samples = run_job("내보내기", started["job_id"])
    render_seconds = time.time() - t0
    if not check("내보내기가 끝까지 완료된다", result is not None, error or ""):
        return 1

    out_path = Path(result["path"])
    print(f"      걸린 시간 {render_seconds / 60:.1f}분 · "
          f"{out_path.stat().st_size / 1024 / 1024:.0f}MB")
    check("결과 파일이 있다", out_path.is_file(), out_path.name)

    judge_progress("내보내기", samples)

    out_seconds = duration_of(out_path)
    check(
        "내보낸 영상의 길이가 원본과 같다 (중간에 잘리지 않았다)",
        abs(out_seconds - source_seconds) < 2.0,
        f"원본 {source_seconds:.1f}초 → 결과 {out_seconds:.1f}초",
    )

    print(f"\n  요약: 음성인식 {stt_seconds / 60:.1f}분 + 내보내기 {render_seconds / 60:.1f}분 "
          f"= 모두 {(stt_seconds + render_seconds) / 60:.1f}분")

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
