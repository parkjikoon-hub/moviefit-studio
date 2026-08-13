"""Phase 1 통합 점검 — 자막 자동 생성부터 내보내기까지 실제로 돌려 본다.

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app
    2) python tests/phase1_test.py

주의: 음성인식 모델을 처음 받는 경우 6분 정도 걸릴 수 있다.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os  # 점검할 서버 주소를 환경변수로 바꿀 수 있게 한다

# 설치본이 8765를 쓰고 있으면 개발 서버를 다른 포트로 띄우고 여기로 겨냥한다.
#   예)  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"
NARR_DIR = ROOT / "tests" / "sample" / "narration"

passed = 0
failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [통과] {label}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {label}" + (f"  ({detail})" if detail else ""))
    return ok


def req(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    url = BASE + urllib.parse.quote(path, safe="/?&=.")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=120) as res:
            return res.status, json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:300]}


def wait_job(job_id: str, timeout: float = 900.0, quiet: bool = False):
    """작업이 끝날 때까지 기다리며 진행률을 보여 준다."""
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        status, job = req(f"/api/jobs/{job_id}")
        if status != 200:
            return None, f"작업 조회 실패 HTTP {status}"

        line = f"    {job['percent']:>3}%  {job['message']}"
        if line != last and not quiet:
            print(line)
            last = line

        if job["status"] == "done":
            return job["result"], None
        if job["status"] == "error":
            return None, job.get("error") or "알 수 없는 오류"
        if job["status"] == "cancelled":
            return None, "취소됨"
        time.sleep(1.0)
    return None, "시간이 너무 오래 걸려 중단했습니다"


def main() -> int:
    print("\n" + "=" * 68)
    print("  Phase 1 통합 점검 — 자막 생성부터 내보내기까지")
    print("=" * 68)

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 다른 창에서 'python -m app' 을 먼저 실행하세요.")
        return 1

    made: list[str] = []

    # ── 1. 실제 한국어 음성으로 자막 자동 생성 ───────────
    print("\n[1] 자막 자동 생성 (F-10) — 실제 한국어 음성")
    narrations = sorted(NARR_DIR.glob("나레이션_*.mp3"))
    if not narrations:
        print("  [건너뜀] tests/sample/narration/ 에 음성이 없습니다. python tools/make_sample.py 를 먼저 실행하세요.")
    else:
        status, proj = req("/api/projects", "POST",
                           {"name": "P1_자막생성시험", "video_path": str(narrations[1]), "mode": "video"})
        if check("음성 파일로 프로젝트 생성", status == 201, f"HTTP {status}"):
            made.append(proj["id"])
            # 사전 규칙을 넣어 교정까지 함께 확인한다
            proj["dictionary"] = [{"from": "무비피", "to": "무비핏"}]
            req(f"/api/projects/{proj['id']}", "PUT", proj)

            status, started = req(f"/api/projects/{proj['id']}/stt", "POST",
                                  {"language": "ko", "model": "small", "max_chars": 20, "max_lines": 2})
            if check("자막 생성 작업 시작", status == 200 and "job_id" in started, f"HTTP {status}"):
                print("    (모델을 처음 받는 경우 몇 분 걸립니다)")
                result, error = wait_job(started["job_id"])
                if check("자막 생성 완료", result is not None, error or ""):
                    segs = result.get("segments", [])
                    check("자막이 실제로 만들어짐", len(segs) > 0, f"{len(segs)}개")
                    for s in segs:
                        print(f"      {s['start']:>6.2f} ~ {s['end']:>6.2f}   {s['text']}")
                    check("한국어가 인식됨",
                          any(any("가" <= ch <= "힣" for ch in s["text"]) for s in segs))

    # ── 2. 자막 넣고 내보내기 ────────────────────────────
    print("\n[2] 내보내기 (F-03 자막파일, F-50 번인, F-54 미리보기)")
    status, proj = req("/api/projects", "POST",
                       {"name": "P1_내보내기시험", "video_path": str(SAMPLE_VIDEO), "mode": "video"})
    if not check("영상 프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    made.append(proj["id"])
    pid = proj["id"]

    proj["segments"] = [
        {"id": "s001", "start": 0.5, "end": 3.2, "text": "안녕하세요, 자막 테스트입니다."},
        {"id": "s002", "start": 3.4, "end": 6.5, "text": "두 줄로 나뉜 자막\n아랫줄입니다."},
        {"id": "s003", "start": 6.7, "end": 9.5, "text": "중괄호 {테스트} 와 기호 100%"},
    ]
    req(f"/api/projects/{pid}", "PUT", proj)

    # SRT
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "srt"})
    if check("SRT 내보내기 시작", status == 200, f"HTTP {status}"):
        result, error = wait_job(started["job_id"], quiet=True)
        if check("SRT 파일 생성", result is not None, error or ""):
            srt_path = Path(result["path"])
            check("파일이 실제로 존재", srt_path.is_file(), srt_path.name)
            # 바이트로 읽는다. read_text()는 CRLF를 LF로 바꿔 버려서
            # 줄바꿈 문자를 있는 그대로 확인할 수 없다.
            raw = srt_path.read_bytes().decode("utf-8")
            check("SRT 형식이 올바름", "-->" in raw and raw.strip().startswith("1"))
            check("한글이 깨지지 않음", "안녕하세요" in raw)
            check("SRT 표준 줄바꿈(CRLF)", "\r\n" in raw)
            # 아래 두 가지는 실제로 있었던 결함이다. 다시 생기지 않게 고정 검사로 둔다.
            check("중괄호 안 글자가 지워지지 않음 (과거 결함)", "{테스트}" in raw)
            check("직접 넣은 줄바꿈이 유지됨 (과거 결함)",
                  "두 줄로 나뉜 자막\r\n아랫줄입니다." in raw,
                  repr(raw[raw.find("두 줄로"): raw.find("두 줄로") + 40]) if "두 줄로" in raw else "문장 없음")
            print("      --- SRT 앞부분 ---")
            for line in raw.splitlines()[:8]:
                print(f"      {line}")

    # VTT
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "vtt"})
    if status == 200:
        result, error = wait_job(started["job_id"], quiet=True)
        if check("VTT 파일 생성", result is not None, error or ""):
            vtt = Path(result["path"]).read_text(encoding="utf-8")
            check("VTT 머리글", vtt.startswith("WEBVTT"))

    # 10초 미리보기
    print("\n  10초 미리보기 렌더링:")
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "preview"})
    if check("미리보기 시작", status == 200, f"HTTP {status}"):
        began = time.time()
        result, error = wait_job(started["job_id"])
        if check("미리보기 영상 생성", result is not None, error or ""):
            path = Path(result["path"])
            check("파일 존재", path.is_file(), f"{path.stat().st_size / 1024:.0f} KB")
            print(f"      걸린 시간: {time.time() - began:.1f}초")

    # 자막 번인
    print("\n  자막 새긴 영상 렌더링:")
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if check("번인 시작", status == 200, f"HTTP {status}"):
        began = time.time()
        result, error = wait_job(started["job_id"])
        if check("자막 새긴 영상 생성", result is not None, error or ""):
            path = Path(result["path"])
            check("파일 존재", path.is_file(), f"{path.stat().st_size / 1024:.0f} KB")
            print(f"      걸린 시간: {time.time() - began:.1f}초")
            print(f"      결과물: {path}")

    # ── 3. 잘못된 상황 ───────────────────────────────────
    print("\n[3] 잘못된 상황에서 죽지 않는가")
    status, empty = req("/api/projects", "POST", {"name": "P1_빈프로젝트", "mode": "script"})
    if status == 201:
        made.append(empty["id"])
        status, body = req(f"/api/projects/{empty['id']}/render", "POST", {"kind": "srt"})
        check("자막 없이 내보내기 → 400과 한국어 안내",
              status == 400 and "자막" in body.get("detail", ""), body.get("detail", "")[:40])
        status, body = req(f"/api/projects/{empty['id']}/stt", "POST", {})
        check("영상 없이 자막생성 → 400과 한국어 안내",
              status == 400 and "없습니다" in body.get("detail", ""), body.get("detail", "")[:40])
    status, body = req("/api/projects/없는프로젝트/render", "POST", {"kind": "srt"})
    check("없는 프로젝트 → 404", status == 404)

    # ── 뒷정리 ───────────────────────────────────────────
    print("\n[4] 뒷정리")
    for pid in made:
        req(f"/api/projects/{pid}", "DELETE")
    check("시험용 프로젝트 삭제", True, f"{len(made)}개")

    print("\n" + "=" * 68)
    print(f"  통과 {passed}개 · 실패 {failed}개")
    print("=" * 68 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
