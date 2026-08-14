"""오류 안내 점검 — 잘못된 것을 넣어도 죽지 않고 한국어로 알려 주는가.

`docs/ROADMAP.md` Phase 5 수용 기준:
    "없는 파일·빈 대본·지원 안 되는 형식을 넣어도 죽지 않고 한국어 안내가 뜬다"

사용법:
    1) 서버를 띄운다      python -m app --port 8766
    2) 이 파일을 실행한다  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                          python tests/errors_test.py

    ※ 인터넷이 필요 없다. 시험용 영상도 필요 없다 (이 파일이 직접 만든다).

무엇을 보는가 — 세 가지를 한꺼번에 본다:
  ① 서버가 죽지 않는가          (마지막에 /api/health 로 확인)
  ② 알맞은 응답 코드가 오는가    (400·404 등. 500이면 처리 못 한 것이다)
  ③ **첫 문장이 한국어인가**     ← 이것이 핵심이다

③을 "한글이 들어 있는가"가 아니라 "**맨 앞이** 한글인가"로 보는 이유:
사용자가 실제로 읽는 것은 앞부분이다. "Invalid data found ... (파일이 손상되었습니다)"
처럼 영어가 앞에 오면, 비개발자에게는 한국어 설명이 있으나 마나다.
"""

from __future__ import annotations

import json
import os
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
WORK = ROOT / "tests" / "sample" / "_오류시험"

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


def wait_job(job_id: str, timeout: float = 300.0) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        status, job = req(f"/api/jobs/{job_id}")
        if status != 200:
            return {"status": "조회실패"}
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(1.0)
    return {"status": "timeout"}


def is_korean_first(message: str) -> bool:
    """메시지의 첫 글자가 한글인가. 사용자가 제일 먼저 읽는 부분이다."""
    text = (message or "").strip()
    if not text:
        return False
    first = text[0]
    return "가" <= first <= "힣"


def korean_error(name: str, status: int, body: dict, expect: int) -> None:
    """응답 코드와 '첫 문장이 한국어인가'를 함께 본다."""
    detail = body.get("detail")
    if isinstance(detail, list):  # FastAPI 기본 검증 오류 (영어 구조체)
        detail = json.dumps(detail, ensure_ascii=False)
    detail = detail if isinstance(detail, str) else str(detail)
    ok = status == expect and is_korean_first(detail)
    check(name, ok, f"HTTP {status} · {detail[:70]}")


def main() -> int:
    print("\n" + "=" * 70)
    print("  오류 안내 점검 — 잘못된 입력에 한국어로 답하는가")
    print("=" * 70)
    print(f"  서버: {BASE}")

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    # 시험용 '나쁜 파일' 세 개를 만든다
    WORK.mkdir(parents=True, exist_ok=True)
    not_a_video = WORK / "그냥글.txt"
    not_a_video.write_text("이것은 영상이 아닙니다", encoding="utf-8")
    empty_video = WORK / "빈영상.mp4"
    empty_video.write_bytes(b"")
    broken_video = WORK / "깨진영상.mp4"
    broken_video.write_bytes(b"THIS IS NOT A REAL MP4" * 60)

    # ── 1. 파일이 잘못된 경우 ────────────────────────────
    print("\n[1] 파일이 잘못된 경우 — 프로젝트를 만들 때 걸러 내는가")

    korean_error(
        "없는 파일을 고르면 한국어로 알려 준다",
        *req("/api/projects", "POST",
             {"name": "오류_없는파일", "video_path": str(WORK / "없는파일.mp4"), "mode": "video"}),
        expect=400,
    )
    korean_error(
        "지원하지 않는 형식(.txt)을 고르면 한국어로 알려 준다",
        *req("/api/projects", "POST",
             {"name": "오류_형식", "video_path": str(not_a_video), "mode": "video"}),
        expect=400,
    )
    korean_error(
        "없는 모드를 주면 한국어로 알려 준다",
        *req("/api/projects", "POST", {"name": "오류_모드", "mode": "이상한모드"}),
        expect=400,
    )
    korean_error(
        "없는 프로젝트를 열면 한국어로 알려 준다",
        *req("/api/projects/이런프로젝트는없다_00000"),
        expect=404,
    )

    # ── 2. 대본·나레이션이 잘못된 경우 ───────────────────
    print("\n[2] 대본·나레이션이 잘못된 경우")

    status, proj = req("/api/projects", "POST", {"name": "오류시험_대본", "mode": "script"})
    if not check("시험용 대본 프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)

    korean_error(
        "빈 대본으로 나레이션을 만들려 하면 한국어로 알려 준다",
        *req(f"/api/projects/{pid}/narration", "POST", {"script": "   "}),
        expect=400,
    )
    korean_error(
        "영상 없이 '나레이션 입힌 영상'을 만들려 하면 한국어로 알려 준다",
        *req(f"/api/projects/{pid}/narration/export", "POST", {"kind": "video"}),
        expect=400,
    )
    korean_error(
        "영상·음성이 없는데 시간 붙이기를 하면 한국어로 알려 준다",
        *req(f"/api/projects/{pid}/align", "POST", {"script": "아무 글"}),
        expect=400,
    )

    # ── 3. 파일이 깨진 경우 — 나중에 터지는 자리 ─────────
    # 확장자만 맞으면 프로젝트는 만들어진다. 진짜 판정은 그 파일을 실제로
    # 읽을 때 일어나므로, 그 자리에서도 한국어가 나오는지 확인해야 한다.
    print("\n[3] 파일이 깨진 경우 — 실제로 읽으려 할 때 한국어로 알려 주는가")

    for label, path in (("내용이 깨진 영상", broken_video), ("0바이트 영상", empty_video)):
        status, made_proj = req(
            "/api/projects", "POST",
            {"name": f"오류_{label}", "video_path": str(path), "mode": "video"},
        )
        if not check(f"{label}으로 프로젝트는 만들어진다 (확장자만 봄)", status == 201, f"HTTP {status}"):
            continue
        bad_pid = made_proj["id"]
        made.append(bad_pid)

        status, started = req(f"/api/projects/{bad_pid}/stt", "POST", {})
        if not check(f"{label}: 음성인식을 시작할 수는 있다", status == 200, f"HTTP {status}"):
            continue
        job = wait_job(started["job_id"])
        error = job.get("error") or ""
        check(
            f"{label}: 서버가 죽지 않고 작업만 실패로 끝난다",
            job.get("status") == "error",
            f"status={job.get('status')}",
        )
        check(
            f"{label}: 실패 안내의 첫 문장이 한국어다",
            is_korean_first(error),
            error[:70],
        )

    # ── 4. 서버가 살아 있는가 ────────────────────────────
    print("\n[4] 이 모든 것을 겪고도 서버가 살아 있는가")
    status, health = req("/api/health")
    check("서버가 정상 응답한다", status == 200 and health.get("ok") is True, str(health))

    status, listing = req("/api/projects")
    check("프로젝트 목록도 정상이다", status == 200, f"HTTP {status}")

    return 0


def cleanup() -> None:
    for pid in made:
        try:
            req(f"/api/projects/{pid}", "DELETE")
        except Exception:
            pass
    for name in ("그냥글.txt", "빈영상.mp4", "깨진영상.mp4"):
        try:
            (WORK / name).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        WORK.rmdir()
    except OSError:
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
