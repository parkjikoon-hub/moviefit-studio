"""Phase 2 통합 점검 — 대본으로 나레이션과 자막을 한 번에 만드는 기능.

이 프로그램의 핵심 차별점(D1)이 실제로 성립하는지를 확인한다:
    "각 문장 음성의 실제 길이로 자막 시각을 계산하므로 소리와 자막이 어긋나지 않는다"

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app
    2) python tests/phase2_test.py
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

BASE = "http://127.0.0.1:8765"
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"

SCRIPT = """안녕하세요. 무비핏 스튜디오입니다.
이 프로그램은 대본을 넣으면 나레이션을 만들어 줍니다.
자막 시각은 만들어진 음성의 실제 길이로 계산합니다.
그래서 소리와 자막이 어긋나지 않습니다."""

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
        with urllib.request.urlopen(r, timeout=180) as res:
            return res.status, json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:300]}


def wait_job(job_id: str, timeout: float = 600.0, quiet: bool = False):
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
    print("\n" + "=" * 70)
    print("  Phase 2 통합 점검 — 대본 → 나레이션 + 자동 동기화 자막")
    print("=" * 70)

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    made: list[str] = []

    # ── 1. 대본 문장 나누기 ──────────────────────────────
    print("\n[1] 대본을 문장으로 나누기 (F-40)")
    status, proj = req("/api/projects", "POST",
                       {"name": "P2_나레이션시험", "video_path": str(SAMPLE_VIDEO), "mode": "script"})
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)

    proj["script"] = SCRIPT
    req(f"/api/projects/{pid}", "PUT", proj)

    status, split = req(f"/api/projects/{pid}/script/split", "POST", {"script": SCRIPT})
    if check("문장 나누기 미리보기", status == 200, f"HTTP {status}"):
        # "안녕하세요."는 마침표가 있으므로 별도 문장이다 → 모두 5개
        check("문장 5개로 나뉨", split["count"] == 5, f"{split['count']}개")
        for i, s in enumerate(split["sentences"], 1):
            print(f"      {i}. {s}")
        print(f"      예상 길이: {split['estimated_seconds']}초")

    # ── 2. 나레이션 생성 + 자막 타이밍 자동 산출 ─────────
    print("\n[2] 나레이션 생성과 자막 시각 자동 산출 (F-42 — 핵심 기능)")
    status, started = req(f"/api/projects/{pid}/narration", "POST", {"script": SCRIPT})
    if not check("나레이션 생성 시작", status == 200, f"HTTP {status}"):
        return 1

    result, error = wait_job(started["job_id"])
    if not check("나레이션 생성 완료", result is not None, error or ""):
        return 1

    segments = result["segments"]
    check("문장 수만큼 자막 생성", len(segments) == 5, f"{len(segments)}개")
    check("이어 붙인 오디오 생성", bool(result.get("audio")), result.get("audio", ""))
    check("이어 붙이기 오차가 1밀리초 미만",
          abs(result.get("error_ms", 999)) < 1.0, f"{result.get('error_ms')}ms")

    print("      만들어진 자막:")
    for s in segments:
        dur = (s.get("tts") or {}).get("duration")
        print(f"      {s['start']:>6.2f} ~ {s['end']:>6.2f}  (음성 {dur:.2f}초)  {s['text'][:30]}")

    # 핵심 검증: 각 자막 길이가 그 문장 음성의 실측 길이와 같아야 한다
    print("\n[3] 자막 시각이 음성 실측 길이와 일치하는가 (D1의 근거)")
    worst = 0.0
    for s in segments:
        measured = (s.get("tts") or {}).get("duration") or 0
        shown = s["end"] - s["start"]
        worst = max(worst, abs(shown - measured))
    check("모든 자막이 음성 길이와 10밀리초 이내로 일치", worst < 0.01, f"최대 차이 {worst * 1000:.1f}ms")

    # 문장 사이 간격이 설정값(0.3초)대로인가
    gaps = [round(segments[i + 1]["start"] - segments[i]["end"], 3) for i in range(len(segments) - 1)]
    check("문장 사이 간격이 설정대로", all(abs(g - 0.3) < 0.02 for g in gaps), f"간격 {gaps}")

    # ── 4. 한 문장만 다시 만들기 (F-43) ──────────────────
    print("\n[4] 한 문장만 고쳐 다시 만들기 (F-43)")
    status, current = req(f"/api/projects/{pid}")
    before_end = current["segments"][-1]["end"]

    current["segments"][1]["text"] = "이 문장은 훨씬 더 길게 바꾸어서 뒤쪽 타이밍이 밀리는지 확인하려고 합니다."
    req(f"/api/projects/{pid}", "PUT", current)

    status, started = req(f"/api/projects/{pid}/narration", "POST", {"segment_id": "s002"})
    if check("문장 재생성 시작", status == 200, f"HTTP {status}"):
        result, error = wait_job(started["job_id"], quiet=True)
        if check("문장 재생성 완료", result is not None, error or ""):
            after = result["segments"]
            after_end = after[-1]["end"]
            check("뒤쪽 자막 타이밍이 자동으로 밀림",
                  after_end > before_end + 0.5,
                  f"{before_end:.2f}초 → {after_end:.2f}초")
            worst2 = max(abs((s["end"] - s["start"]) - ((s.get("tts") or {}).get("duration") or 0))
                         for s in after)
            check("재계산 후에도 음성 길이와 일치", worst2 < 0.01, f"최대 차이 {worst2 * 1000:.1f}ms")

    # ── 5. 나레이션 내보내기 (F-52, F-51) ────────────────
    print("\n[5] 나레이션 내보내기")
    status, started = req(f"/api/projects/{pid}/narration/export", "POST",
                          {"kind": "audio", "fmt": "mp3"})
    if check("오디오 내보내기 시작", status == 200, f"HTTP {status}"):
        result, error = wait_job(started["job_id"], quiet=True)
        if check("나레이션 오디오 생성 (F-52)", result is not None, error or ""):
            path = Path(result["path"])
            check("파일 존재", path.is_file(), f"{path.stat().st_size / 1024:.0f} KB, {result.get('duration')}초")

    print("\n  영상에 나레이션 입히기:")
    status, started = req(f"/api/projects/{pid}/narration/export", "POST",
                          {"kind": "video", "original_volume": 30})
    if check("영상 합성 시작", status == 200, f"HTTP {status}"):
        result, error = wait_job(started["job_id"])
        if check("나레이션 입힌 영상 생성 (F-51)", result is not None, error or ""):
            path = Path(result["path"])
            check("파일 존재", path.is_file(), f"{path.stat().st_size / 1024:.0f} KB")
            check("원본 소리 볼륨 설정 반영", result.get("original_volume") == 30,
                  str(result.get("original_volume")))

    # ── 6. 나레이션이 영상보다 길 때 미리 알려 주는가 ────
    print("\n[6] 나레이션이 영상보다 길면 미리 알려 주는가")
    status, info = req(f"/api/projects/{pid}/narration/status")
    if check("상태 조회", status == 200, f"HTTP {status}"):
        print(f"      나레이션 {info.get('narration_seconds')}초 / 영상 {info.get('video_seconds')}초")
        check("잘림 경고가 표시됨", bool(info.get("warning")), (info.get("warning") or "경고 없음")[:60])

    # ── 7. 잘못된 상황 ───────────────────────────────────
    print("\n[7] 잘못된 상황에서 죽지 않는가")
    status, empty = req("/api/projects", "POST", {"name": "P2_빈대본", "mode": "script"})
    if status == 201:
        made.append(empty["id"])
        status, body = req(f"/api/projects/{empty['id']}/narration", "POST", {"script": "   "})
        check("빈 대본 → 400과 한국어 안내",
              status == 400 and "대본" in body.get("detail", ""), body.get("detail", "")[:40])
        status, body = req(f"/api/projects/{empty['id']}/narration/export", "POST", {"kind": "video"})
        check("영상 없이 합성 → 400과 한국어 안내",
              status == 400 and "영상" in body.get("detail", ""), body.get("detail", "")[:40])
    status, body = req(f"/api/projects/{pid}/narration", "POST", {"segment_id": "없는문장"})
    check("없는 문장 재생성 → 400", status == 400, body.get("detail", "")[:40])

    # ── 뒷정리 ───────────────────────────────────────────
    print("\n[8] 뒷정리")
    for p in made:
        req(f"/api/projects/{p}", "DELETE")
    check("시험용 프로젝트 삭제", True, f"{len(made)}개")

    print("\n" + "=" * 70)
    print(f"  통과 {passed}개 · 실패 {failed}개")
    print("=" * 70 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
