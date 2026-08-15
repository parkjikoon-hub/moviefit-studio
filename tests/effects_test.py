"""화면 효과 띠(사용자가 구간을 정해 거는 효과) 점검.

사용법:
    python tests/effects_test.py        서버를 띄우지 않아도 된다 (계산만 검사한다)

이 점검이 확인하려는 것 — `docs/DESIGN_effects_and_zoom.md` 의 뼈대 요구사항:
  · 효과 목록의 기본값은 **비어 있다** (아무것도 미리 넣지 않는다)
  · 사용자가 보낸 값을 시스템 경계에서 다듬는다 (구간·세기·종류)
  · 막대를 **여러 개, 겹쳐서** 놓을 수 있다  ← "요소요소 폭죽"이 되려면 필수
  · 세기 3단계가 **가짜 선택지가 아니다** (memory/options-must-actually-differ.md)
  · zoompan 의 실측된 함정 둘(fps·d)이 필터에 반영되어 있다
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import effects  # noqa: E402

passed: list[str] = []
failed: list[str] = []
skipped: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def bar(**over) -> dict:
    base = {"kind": "zoom_punch", "start": 1.0, "end": 3.0, "strength": "medium"}
    base.update(over)
    return base


# ══════════════════════════════════════════════════════════════
# 1. 등록표 — 효과를 하나 더 붙이는 일이 여기 한 줄이어야 한다
# ══════════════════════════════════════════════════════════════
print("\n=== 1. 효과 등록표 ===")

check("등록표에 줌 강조가 있다", "zoom_punch" in effects.KINDS,
      f"등록된 종류: {sorted(effects.KINDS)}")

check("모든 효과에 한국어 이름이 붙어 있다",
      all(k.get("label") for k in effects.KINDS.values()),
      ", ".join(f"{n}={k.get('label')}" for n, k in effects.KINDS.items()))

check("모든 효과가 세기 3단계를 갖고 있다",
      all(set(k.get("strengths", {})) == {"low", "medium", "high"} for k in effects.KINDS.values()),
      ", ".join(f"{n}={sorted(k.get('strengths', {}))}" for n, k in effects.KINDS.items()))


# ══════════════════════════════════════════════════════════════
# 2. 값 다듬기 — 사용자가 보내는 값이므로 경계에서 한 번 거른다
# ══════════════════════════════════════════════════════════════
print("\n=== 2. 값 다듬기 ===")

check("효과를 안 보내면 빈 목록이다 (아무것도 미리 넣지 않는다)",
      effects.normalize(None, duration=10.0) == [], f"실제 {effects.normalize(None, duration=10.0)!r}")

check("빈 목록은 빈 목록 그대로다", effects.normalize([], duration=10.0) == [])

unknown = effects.normalize([bar(kind="유니콘")], duration=10.0)
check("등록표에 없는 종류는 버린다", unknown == [], f"실제 {unknown!r}")

backwards = effects.normalize([bar(start=5.0, end=2.0)], duration=10.0)
check("끝이 시작보다 앞서면 버린다", backwards == [], f"실제 {backwards!r}")

zero = effects.normalize([bar(start=2.0, end=2.0)], duration=10.0)
check("길이가 0이면 버린다", zero == [], f"실제 {zero!r}")

over = effects.normalize([bar(start=8.0, end=99.0)], duration=10.0)
check("영상 길이를 넘으면 영상 끝까지로 줄인다",
      len(over) == 1 and over[0]["end"] == 10.0, f"실제 {over!r}")

outside = effects.normalize([bar(start=20.0, end=25.0)], duration=10.0)
check("영상이 끝난 뒤의 막대는 버린다", outside == [], f"실제 {outside!r}")

negative = effects.normalize([bar(start=-5.0, end=2.0)], duration=10.0)
check("시작이 음수면 0초로 당긴다",
      len(negative) == 1 and negative[0]["start"] == 0.0, f"실제 {negative!r}")

weird = effects.normalize([bar(strength="아주많이")], duration=10.0)
check("세기 이름이 이상하면 보통으로 되돌린다",
      len(weird) == 1 and weird[0]["strength"] == "medium", f"실제 {weird!r}")

named = effects.normalize([bar(), bar(start=4.0, end=5.0)], duration=10.0)
check("막대마다 서로 다른 이름표(id)가 붙는다",
      len({b["id"] for b in named}) == 2, f"실제 {[b['id'] for b in named]}")

kept = effects.normalize([{"id": "내이름", **bar()}], duration=10.0)
check("이미 이름표가 있으면 그대로 둔다",
      kept and kept[0]["id"] == "내이름", f"실제 {kept!r}")


# ══════════════════════════════════════════════════════════════
# 3. 막대를 여러 개·겹쳐서 — "요소요소 폭죽"의 조건
# ══════════════════════════════════════════════════════════════
print("\n=== 3. 막대 여러 개 ===")

many = effects.normalize(
    [bar(start=1.0, end=2.0), bar(start=4.0, end=5.0), bar(start=7.0, end=8.0)],
    duration=10.0,
)
check("막대를 여러 개 놓을 수 있다", len(many) == 3, f"실제 {len(many)}개")

overlap = effects.normalize([bar(start=1.0, end=5.0), bar(start=3.0, end=7.0)], duration=10.0)
check("막대가 겹쳐도 버리지 않는다", len(overlap) == 2, f"실제 {len(overlap)}개")

shuffled = effects.normalize([bar(start=7.0, end=8.0), bar(start=1.0, end=2.0)], duration=10.0)
check("막대를 시작 시각 순서로 정리해 준다",
      [b["start"] for b in shuffled] == [1.0, 7.0], f"실제 {[b['start'] for b in shuffled]}")


# ══════════════════════════════════════════════════════════════
# 4. 세기 3단계가 가짜 선택지가 아닌가
#    화면이 커지는 정도는 (배율 - 1) 에 비례한다. 그 간격을 잰다.
# ══════════════════════════════════════════════════════════════
print("\n=== 4. 세기 3단계 ===")

zp = effects.KINDS["zoom_punch"]["strengths"]
low, med, high = zp["low"]["scale"], zp["medium"]["scale"], zp["high"]["scale"]

check("세기가 셀수록 배율이 커진다", low < med < high, f"{low} < {med} < {high}")

gap1 = (med - 1) / (low - 1)
gap2 = (high - 1) / (med - 1)
check("단계 사이가 1.3배 넘게 벌어진다 (가짜 선택지가 아니다)",
      gap1 >= 1.3 and gap2 >= 1.3, f"약→보통 {gap1:.2f}배 · 보통→많이 {gap2:.2f}배")

check("가장 센 단계도 상한을 넘지 않는다", high <= 2.0, f"많이 = {high}배")


# ══════════════════════════════════════════════════════════════
# 5. 필터 만들기 — 실측한 zoompan 함정 둘이 반영되었는가
# ══════════════════════════════════════════════════════════════
print("\n=== 5. 필터 만들기 ===")

check("효과가 없으면 필터도 없다 (기존 경로를 건드리지 않는다)",
      effects.build_filter([], 1080, 1920, 30.0) is None,
      f"실제 {effects.build_filter([], 1080, 1920, 30.0)!r}")

one = effects.normalize([bar(start=1.0, end=3.0)], duration=10.0)
flt = effects.build_filter(one, 1080, 1920, 30.0)

check("줌 강조는 zoompan 으로 만든다", "zoompan" in (flt or ""), f"필터: {(flt or '')[:80]}…")

check("원본 프레임률을 명시한다 (안 하면 10초가 12초로 늘어난다 — 실측)",
      "fps=30" in (flt or ""), f"필터: {flt}")

check("d=1 을 명시한다 (안 하면 같은 프레임이 되풀이된다)",
      "d=1" in (flt or ""), f"필터: {flt}")

check("출력 크기를 명시한다", "s=1080x1920" in (flt or ""), f"필터: {flt}")

# 1.0초~3.0초 = 30fps 에서 30번~90번 프레임
check("사용자가 정한 구간이 프레임 번호로 들어간다",
      "30" in (flt or "") and "90" in (flt or ""), f"필터: {flt}")

two = effects.normalize([bar(start=1.0, end=2.0), bar(start=5.0, end=6.0)], duration=10.0)
flt2 = effects.build_filter(two, 1080, 1920, 30.0)
check("막대가 여럿이어도 zoompan 은 한 번만 건다 (여러 번 걸면 그만큼 느려진다)",
      (flt2 or "").count("zoompan") == 1, f"zoompan {(flt2 or '').count('zoompan')}번")

check("막대가 여럿이면 구간이 모두 들어간다",
      "150" in (flt2 or "") and "180" in (flt2 or ""),
      f"5.0초=150번, 6.0초=180번 프레임: {flt2}")

soft = effects.build_filter(effects.normalize([bar(strength="low")], duration=10.0), 1080, 1920, 30.0)
loud = effects.build_filter(effects.normalize([bar(strength="high")], duration=10.0), 1080, 1920, 30.0)
check("세기를 바꾸면 필터 문자열이 실제로 달라진다", soft != loud,
      "약하게와 많이가 같은 필터를 냈습니다" if soft == loud else "다름")


# ══════════════════════════════════════════════════════════════
# 6. 실물 — 실제로 영상을 만들어 확인한다
#    T5 가 이 점검의 핵심이다: **효과 구간 바깥이 효과 없는 영상과 같은가.**
#    이것이 "사용자가 정한 구간에만 걸린다"의 유일한 증거다.
#    서버가 켜져 있어야 하며, 없으면 건너뛴 것으로 분명히 표시한다.
# ══════════════════════════════════════════════════════════════
print("\n=== 6. T5·T6: 실제로 만든 영상 측정 ===")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 300):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


def run_job(job_id: str, limit: float = 600.0) -> dict:
    deadline = time.time() + limit
    while time.time() < deadline:
        info = api(f"/api/jobs/{job_id}")
        if info["status"] == "done":
            return info.get("result") or {}
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        time.sleep(1.0)
    raise TimeoutError("작업이 제한 시간 안에 끝나지 않았습니다.")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,nb_read_frames,duration,r_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=180,
    )
    return json.loads(out.stdout)["streams"][0]


def frame_psnr(a: Path, b: Path, at: float, work: Path) -> float | None:
    """두 영상의 같은 시각 한 장면이 얼마나 닮았는지. 클수록 닮았다."""
    pa, pb = work / f"_a{at}.png", work / f"_b{at}.png"
    for src, dst in ((a, pa), (b, pb)):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                        "-ss", str(at), "-frames:v", "1", str(dst)],
                       check=True, timeout=120)
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(pa), "-i", str(pb), "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    pa.unlink(missing_ok=True)
    pb.unlink(missing_ok=True)
    hit = re.search(r"average:(inf|[0-9.]+)", out.stderr or "")
    if not hit:
        return None
    return float("inf") if hit.group(1) == "inf" else float(hit.group(1))


try:
    api("/api/health", timeout=5)
    server_up = True
except Exception as exc:
    server_up = False
    print(f"      서버에 연결하지 못했습니다 ({BASE}) — 실물 점검을 **건너뜁니다**: {exc}")
    skipped.append("T5·T6 실물 점검 (서버 없음)")

if server_up and not SAMPLE.is_file():
    server_up = False
    print(f"      샘플 영상이 없어 **건너뜁니다**: {SAMPLE}")
    skipped.append("T5·T6 실물 점검 (샘플 영상 없음)")

if server_up:
    pid = ""
    try:
        proj = api("/api/projects", "POST",
                   {"name": "효과점검", "video_path": str(SAMPLE), "mode": "video"})
        pid = proj["id"]
        check("새 프로젝트의 효과 목록은 비어 있다 (아무것도 미리 넣지 않는다)",
              proj.get("effects") == [], f"실제 {proj.get('effects')!r}")

        proj["segments"] = [{"id": "s1", "start": 0.2, "end": 1.0, "text": ""}]
        proj["output"] = {"aspect": "source", "fit": "crop", "focus_x": 50, "focus_y": 50,
                          "pad_blur": True, "zoom": 1.0}

        # ① 효과 없이 한 벌
        proj["effects"] = []
        api(f"/api/projects/{pid}", "PUT", proj)
        job = api(f"/api/projects/{pid}/render", "POST",
                  {"kind": "preview", "preview_seconds": 6})
        plain = Path(run_job(job["job_id"])["path"])

        # ② 2.0~4.0초에만 줌 강조를 걸어 한 벌
        proj["effects"] = [{"kind": "zoom_punch", "start": 2.0, "end": 4.0, "strength": "high"}]
        saved = api(f"/api/projects/{pid}", "PUT", proj)
        check("효과 막대가 저장되고 이름표가 붙어서 돌아온다",
              len(saved.get("effects") or []) == 1 and saved["effects"][0].get("id"),
              f"실제 {saved.get('effects')!r}")

        job = api(f"/api/projects/{pid}/render", "POST",
                  {"kind": "preview", "preview_seconds": 6})
        withfx = Path(run_job(job["job_id"])["path"])

        a, b = probe(plain), probe(withfx)
        check("효과를 걸어도 영상 길이가 그대로다 (zoompan 의 fps 함정)",
              abs(float(a["duration"]) - float(b["duration"])) < 0.1,
              f"효과 없음 {a['duration']}초 / 효과 있음 {b['duration']}초")
        check("효과를 걸어도 프레임 수가 그대로다",
              a["nb_read_frames"] == b["nb_read_frames"],
              f"효과 없음 {a['nb_read_frames']}장 / 효과 있음 {b['nb_read_frames']}장")
        check("효과를 걸어도 프레임률이 그대로다",
              a["r_frame_rate"] == b["r_frame_rate"],
              f"효과 없음 {a['r_frame_rate']} / 효과 있음 {b['r_frame_rate']}")
        check("효과를 걸어도 화면 크기가 그대로다",
              (a["width"], a["height"]) == (b["width"], b["height"]),
              f"{a['width']}×{a['height']} / {b['width']}×{b['height']}")

        work = withfx.parent
        before = frame_psnr(plain, withfx, 1.0, work)
        inside = frame_psnr(plain, withfx, 3.0, work)
        after = frame_psnr(plain, withfx, 5.0, work)

        # T5 — 이 점검의 핵심.
        check("효과 구간 **앞쪽**은 효과 없는 영상과 같다 (1.0초)",
              before is not None and before > 40.0, f"닮음 {before} (40 위면 사실상 같음)")
        check("효과 구간 **뒤쪽**도 효과 없는 영상과 같다 (5.0초)",
              after is not None and after > 40.0, f"닮음 {after} (40 위면 사실상 같음)")
        # T6
        check("효과 구간 **안**은 확실히 달라진다 (3.0초)",
              inside is not None and inside < 25.0, f"닮음 {inside} (낮을수록 다름)")
        check("구간 안과 밖의 차이가 뚜렷하다",
              None not in (before, inside, after) and inside < min(before, after) - 10,
              f"밖 {before}/{after} vs 안 {inside}")

    except Exception as exc:
        check("실제로 만든 영상으로 효과 구간을 확인한다", False, f"{type(exc).__name__}: {exc}")
    finally:
        if pid:
            try:
                api(f"/api/projects/{pid}", "DELETE")
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개"
      + (f" · 건너뜀 {len(skipped)}개" if skipped else ""))
for name in skipped:
    print(f"   · 건너뜀: {name}")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
