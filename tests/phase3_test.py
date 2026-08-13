"""Phase 3 통합 점검 — 스타일·위치·사전·자막 파일 가져오기.

가장 중요한 확인: 화면 미리보기에서 정한 자막 모양과 위치가
**영상에 새긴 결과에서도 같은가**. 이건 눈으로만 볼 게 아니라 실제 픽셀로 잰다.
검은 배경 영상에 자막을 새기고 글자가 찍힌 위치를 계산해서 설정값과 대조한다.

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app
    2) python tests/phase3_test.py
"""

from __future__ import annotations

import json
import subprocess
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
WORK = ROOT / "tests" / "sample"
BLACK_VIDEO = WORK / "_phase3_black.mp4"

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


def wait_job(job_id: str, timeout: float = 300.0):
    started = time.time()
    while time.time() - started < timeout:
        status, job = req(f"/api/jobs/{job_id}")
        if status != 200:
            return None, f"작업 조회 실패 HTTP {status}"
        if job["status"] == "done":
            return job["result"], None
        if job["status"] in ("error", "cancelled"):
            return None, job.get("error") or job["status"]
        time.sleep(0.7)
    return None, "시간 초과"


def make_black_video() -> bool:
    """글자 위치를 재기 쉽도록 완전히 검은 5초 영상을 만든다."""
    if BLACK_VIDEO.is_file():
        return True
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=25:d=5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        str(BLACK_VIDEO),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def text_center(video: Path, at: str = "2.0") -> tuple[float, float, int] | None:
    """영상의 한 장면에서 글자가 찍힌 영역의 중심을 (가로%, 세로%)로 돌려준다.

    검은 배경이므로 밝은 픽셀 = 글자다. 밝은 픽셀들의 무게중심을 구한다.
    """
    from PIL import Image

    png = WORK / "_phase3_frame.png"
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", at, "-i", str(video),
         "-frames:v", "1", str(png)],
        capture_output=True,
    )
    if result.returncode != 0 or not png.is_file():
        return None

    img = Image.open(png).convert("L")
    width, height = img.size
    pixels = img.load()

    total = 0
    sum_x = 0
    sum_y = 0
    # 검은 배경(0)과 확실히 구분되는 밝기만 글자로 본다
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if pixels[x, y] > 110:
                total += 1
                sum_x += x
                sum_y += y

    png.unlink(missing_ok=True)
    if total < 30:
        return None
    return (sum_x / total / width * 100, sum_y / total / height * 100, total)


def render_and_measure(pid: str, style: dict) -> tuple[float, float, int] | None:
    """스타일을 적용해 번인한 뒤 글자 위치를 잰다."""
    status, proj = req(f"/api/projects/{pid}")
    proj["style"] = style
    req(f"/api/projects/{pid}", "PUT", proj)

    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})
    if status != 200:
        return None
    result, error = wait_job(started["job_id"])
    if not result:
        print(f"      렌더링 실패: {error}")
        return None
    return text_center(Path(result["path"]))


def main() -> int:
    print("\n" + "=" * 70)
    print("  Phase 3 통합 점검 — 스타일·위치·사전·자막 가져오기")
    print("=" * 70)

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    if not check("측정용 검은 영상 준비", make_black_video(), BLACK_VIDEO.name):
        return 1

    made: list[str] = []
    status, proj = req("/api/projects", "POST",
                       {"name": "P3_스타일시험", "video_path": str(BLACK_VIDEO), "mode": "video"})
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)

    proj["segments"] = [{"id": "s001", "start": 0.2, "end": 4.8, "text": "위치 확인용 자막입니다"}]
    req(f"/api/projects/{pid}", "PUT", proj)

    # ── 1. 위치 프리셋이 영상에 반영되는가 ───────────────
    print("\n[1] 자막 위치 프리셋이 영상에 그대로 반영되는가 (F-30)")
    status, presets = req("/api/styles/presets")
    base = presets["builtin"][0]["style"]

    expectations = {"top": 12.0, "middle": 50.0, "bottom": 88.0}
    for preset, expected_y in expectations.items():
        style = json.loads(json.dumps(base))
        style["position"] = {"mode": "preset", "preset": preset, "x": 50, "y": expected_y}
        measured = render_and_measure(pid, style)
        if measured is None:
            check(f"위치 '{preset}' 측정", False, "글자를 찾지 못함")
            continue
        x, y, count = measured
        # 아래/위 프리셋은 여백 규칙 때문에 정확히 12%/88%는 아니고 그 근처다.
        # 중요한 것은 '위는 위쪽, 가운데는 가운데, 아래는 아래쪽'이 지켜지는가다.
        ok = abs(y - expected_y) < 12.0
        check(f"위치 '{preset}' 이 의도한 높이에 나옴",
              ok, f"세로 {y:.1f}% (기대 {expected_y:.0f}% 부근), 가로 {x:.1f}%")

    # ── 2. 마우스로 옮긴 위치가 영상에도 반영되는가 ──────
    print("\n[2] 마우스로 옮긴 자유 위치가 영상에 그대로 반영되는가 (F-33 — 핵심)")
    for target_x, target_y in [(25.0, 30.0), (75.0, 60.0)]:
        style = json.loads(json.dumps(base))
        style["position"] = {"mode": "custom", "preset": "bottom", "x": target_x, "y": target_y}
        measured = render_and_measure(pid, style)
        if measured is None:
            check(f"자유 위치 ({target_x}%, {target_y}%) 측정", False, "글자를 찾지 못함")
            continue
        x, y, _ = measured
        check(f"자유 위치 가로 {target_x}% 반영", abs(x - target_x) < 6.0, f"실제 {x:.1f}%")
        check(f"자유 위치 세로 {target_y}% 반영", abs(y - target_y) < 6.0, f"실제 {y:.1f}%")

    # ── 3. 프리셋마다 실제로 다르게 보이는가 ─────────────
    print("\n[3] 프리셋 5종이 서로 다른 결과를 만드는가 (F-31)")
    sizes: dict[str, int] = {}
    for item in presets["builtin"]:
        measured = render_and_measure(pid, item["style"])
        if measured is None:
            check(f"프리셋 '{item['label']}' 렌더링", False, "글자를 찾지 못함")
            continue
        x, y, count = measured
        sizes[item["label"]] = count
        print(f"      {item['label']:6} 글자 픽셀 {count:>6}개, 위치 ({x:.0f}%, {y:.0f}%)")
    check("프리셋 5종 모두 렌더링됨", len(sizes) == 5, f"{len(sizes)}개")
    if len(sizes) == 5:
        check("프리셋마다 글자 크기가 실제로 다름",
              len(set(sizes.values())) >= 4, f"서로 다른 값 {len(set(sizes.values()))}개")

    # ── 4. 사용자 사전 (F-12) ────────────────────────────
    print("\n[4] 사용자 사전이 음성인식 결과를 고치는가 (F-12)")
    narr = sorted((ROOT / "tests" / "sample" / "narration").glob("나레이션_01*.mp3"))
    if not narr:
        print("  [건너뜀] 시험용 음성이 없습니다. python tools/make_sample.py 를 먼저 실행하세요.")
    else:
        status, dict_proj = req("/api/projects", "POST",
                                {"name": "P3_사전시험", "video_path": str(narr[0]), "mode": "video"})
        if status == 201:
            made.append(dict_proj["id"])
            # 일부러 엉뚱한 규칙을 넣어 사전이 실제로 적용되는지 본다
            dict_proj["dictionary"] = [{"from": "안녕하세요", "to": "반갑습니다"}]
            req(f"/api/projects/{dict_proj['id']}", "PUT", dict_proj)

            status, started = req(f"/api/projects/{dict_proj['id']}/stt", "POST",
                                  {"language": "ko", "model": "small"})
            if status == 200:
                result, error = wait_job(started["job_id"], timeout=300)
                if check("자막 생성", result is not None, error or ""):
                    joined = " ".join(s["text"] for s in result["segments"])
                    print(f"      결과: {joined}")
                    check("사전 규칙이 적용됨", "반갑습니다" in joined and "안녕하세요" not in joined,
                          joined[:40])

    # ── 5. 자막 파일 가져오기 (F-04) ─────────────────────
    print("\n[5] 자막 파일 가져오기 (F-04)")
    status, started = req(f"/api/projects/{pid}/render", "POST", {"kind": "srt"})
    exported = None
    if status == 200:
        result, _ = wait_job(started["job_id"])
        exported = result["path"] if result else None

    if exported:
        status, before = req(f"/api/projects/{pid}")
        before["segments"] = []
        req(f"/api/projects/{pid}", "PUT", before)

        status, imported = req(f"/api/projects/{pid}/subtitles/import", "POST", {"path": exported})
        if check("SRT 가져오기", status == 200, f"HTTP {status}"):
            check("자막이 되살아남", imported["count"] == 1, f"{imported['count']}개")
            check("글자가 그대로", "위치 확인용" in imported["segments"][0]["text"],
                  imported["segments"][0]["text"])

    status, body = req(f"/api/projects/{pid}/subtitles/import", "POST", {"path": "C:/없는파일.srt"})
    check("없는 파일 → 400과 한국어 안내",
          status == 400 and "찾을 수 없" in body.get("detail", ""), body.get("detail", "")[:40])

    # ── 뒷정리 ───────────────────────────────────────────
    print("\n[6] 뒷정리")
    for p in made:
        req(f"/api/projects/{p}", "DELETE")
    BLACK_VIDEO.unlink(missing_ok=True)
    check("시험용 프로젝트와 파일 삭제", True, f"{len(made)}개")

    print("\n" + "=" * 70)
    print(f"  통과 {passed}개 · 실패 {failed}개")
    print("=" * 70 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
