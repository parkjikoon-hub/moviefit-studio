"""화면 효과 — 물방울 맺힘 · 비눗방울 · 작은 폭죽 점검 (5단계).

사용법:
    python tests/artfx_test.py                    FFmpeg·Pillow 만 있으면 된다
    MOVIEFIT_TEST_URL=http://127.0.0.1:8766 python tests/artfx_test.py   화면까지

이 셋만 따로 점검하는 이유: 앞의 13종과 **만드는 방법이 다르다.** 파이썬이 그림을
그려 두고 FFmpeg 이 `movie=` 로 읽는다. 그래서 그림 파일이 없으면 아예 못 만든다.

무엇을 지키는가:

  · 그림 파일 폴더를 안 주면 **조용히 건너뛰지 않고 터진다**
    — 조용히 건너뛰면 "효과를 걸었는데 아무 일도 안 일어나는" 결과가 된다
  · 굴절 지도의 **자가 어긋나지 않는다** — 어긋나면 온 화면이 밀린다
  · 셋 다 구간 밖이 원본과 한 값도 다르지 않다
  · 셋 다 화면을 지나치게 가리지 않는다 (5단계도 같은 상한을 지킨다)
  · 비눗방울은 실제로 **위로** 가고, 폭죽은 시각마다 **다른 장면**이 나온다
  · 폭죽 렌더가 **끝난다** — loop 로 만든 흐름은 끝이 없어 shortest 를 빠뜨리면 안 끝난다
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import effects, fxart  # noqa: E402

passed: list[str] = []
failed: list[str] = []
skipped: list[str] = []

ART_KINDS = ("water_drops", "bubbles", "fireworks")
LABELS = {k: effects.KINDS[k]["label"] for k in ART_KINDS if k in effects.KINDS}


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def skip(name: str, why: str) -> None:
    skipped.append(name)
    print(f"[ 건너뜀 ] {name}   — {why}")


# ══════════════════════════════════════════════════════════════
# 1. 등록표
# ══════════════════════════════════════════════════════════════
print("\n=== 1. 등록표 ===")

for kind in ART_KINDS:
    check(f"등록표에 {kind} 가 있다", kind in effects.KINDS, LABELS.get(kind, "없음"))

check("셋 다 그림을 그리는 갈래(art)로 등록되어 있다",
      all(effects.KINDS[k].get("art") for k in ART_KINDS))

check("셋 다 한 줄 설명이 붙어 있다",
      all(effects.KINDS[k].get("hint") for k in ART_KINDS))

check("물방울·비눗방울·폭죽이 비·눈보다 나중에 온다 (날씨 위에 얹힌다)",
      all(effects.KINDS[k]["order"] > effects.KINDS["snow"]["order"] for k in ART_KINDS))

check("색감 프리셋이 셋보다 나중에 온다 (효과까지 함께 물들어야 자연스럽다)",
      all(effects.KINDS["warm"]["order"] > effects.KINDS[k]["order"] for k in ART_KINDS))

check("폭죽은 자리를 정할 수 있다 (요소요소에 놓는 것이 쓰임새다)",
      {"x", "y"} <= set(effects.KINDS["fireworks"]["params"]))

check("비눗방울은 속도를 조절할 수 있다",
      "speed" in effects.KINDS["bubbles"]["params"])

# 그림이 필요한 효과를 알아보는가
check("그림이 필요한 효과를 알아본다",
      effects.needs_art([{"kind": "bubbles"}])
      and not effects.needs_art([{"kind": "rain"}]))


# ══════════════════════════════════════════════════════════════
# 2. 폴더를 안 주면 조용히 넘어가지 않는다
# ══════════════════════════════════════════════════════════════
print("\n=== 2. 폴더를 안 주면 터지는가 ===")
#
# 이 저장소에서 나온 결함 대부분이 '오류 없이 틀린 결과'였다. 그림 폴더가 없을 때
# 효과를 조용히 빼 버리면 사용자는 "효과를 걸었는데 아무 일도 안 일어난다"를 겪는다.

bars_art = effects.normalize(
    [{"kind": "bubbles", "start": 1.0, "end": 3.0, "strength": "medium"}], duration=10.0)
try:
    effects.build_filter(bars_art, 1280, 720, 30.0)
    check("그림 폴더 없이 부르면 오류를 낸다", False, "조용히 넘어갔다")
except ValueError as exc:
    check("그림 폴더 없이 부르면 오류를 낸다", True, f"{exc}"[:60])

bars_plain = effects.normalize(
    [{"kind": "rain", "start": 1.0, "end": 3.0, "strength": "medium"}], duration=10.0)
try:
    made = effects.build_filter(bars_plain, 1280, 720, 30.0)
    check("그림이 필요 없는 효과는 폴더 없이도 그대로 만들어진다", bool(made))
except ValueError:
    check("그림이 필요 없는 효과는 폴더 없이도 그대로 만들어진다", False, "터졌다")


# ══════════════════════════════════════════════════════════════
# 3. 필터 문자열에 못 박은 것
# ══════════════════════════════════════════════════════════════
print("\n=== 3. 필터에 못 박은 것 ===")

art_dir = Path(tempfile.mkdtemp(prefix="artfx_"))


def flt(kind: str, start=2.0, end=4.0, strength="medium", params=None,
        width=1280, height=720, fps=30.0) -> str:
    bar = {"kind": kind, "start": start, "end": end, "strength": strength}
    if params:
        bar["params"] = params
    return effects.build_filter(
        effects.normalize([bar], duration=10.0), width, height, fps, folder=art_dir) or ""


drops = flt("water_drops")
check("물방울: 굴절 지도의 자를 되돌린다 (안 하면 온 화면이 밀린다)",
      "minval" in drops and "maxval" in drops,
      "그림의 0~255 가 필터 안에서 16~235 로 눌린다 — 128(안 밂)이 126 이 된다")
check("물방울: displace 로 화면을 휘게 한다", "displace=" in drops)

fire = flt("fireworks")
check("폭죽: shortest=1 을 붙인다 (안 붙이면 렌더가 안 끝난다)", "shortest=1" in fire)
check("폭죽: 장면을 넘기려고 crop 에 시간식을 쓴다",
      "crop=" in fire and "floor(mod((t-" in fire)
check("폭죽: 막대가 시작할 때 터진다 (막대 시각이 식에 들어간다)",
      "t-2.000" in fire, f"필터 일부: …{fire[fire.find('floor(mod((t-'):][:44]}…")

bub = flt("bubbles")
check("비눗방울: 겹치는 자리를 시간식으로 움직인다", "overlay=x='" in bub and "sin(" in bub)
check("비눗방울: 위로 가도록 자리를 만든다 (mod 로 되풀이한다)", "mod(t*" in bub)

for kind in ART_KINDS:
    check(f"{LABELS[kind]}: 사용자가 정한 구간에만 켜진다",
          "enable='between(t,2.000,4.000)" in flt(kind))
    check(f"{LABELS[kind]}: 필터에 파일 이름만 들어간다 (경로를 넣으면 깨진다)",
          str(art_dir) not in flt(kind) and ":\\" not in flt(kind))

# 설정이 같으면 그림을 다시 쓰고, 다르면 따로 만든다
two_same = effects.build_filter(effects.normalize([
    {"kind": "bubbles", "start": 1.0, "end": 2.0, "strength": "medium"},
    {"kind": "bubbles", "start": 4.0, "end": 5.0, "strength": "medium"},
], duration=10.0), 1280, 720, 30.0, folder=art_dir) or ""
check("설정이 같은 막대끼리는 그림 한 장을 같이 쓴다", two_same.count("movie=") == 1,
      f"movie= {two_same.count('movie=')}번")

two_diff = effects.build_filter(effects.normalize([
    {"kind": "bubbles", "start": 1.0, "end": 2.0, "strength": "medium",
     "params": {"speed": 50}},
    {"kind": "bubbles", "start": 4.0, "end": 5.0, "strength": "medium",
     "params": {"speed": 200}},
], duration=10.0), 1280, 720, 30.0, folder=art_dir) or ""
check("속도가 다르면 그림을 따로 만든다 (같이 쓰면 한쪽 속도가 무시된다)",
      two_diff.count("movie=") == 2, f"movie= {two_diff.count('movie=')}번")

two_fire = effects.build_filter(effects.normalize([
    {"kind": "fireworks", "start": 1.0, "end": 2.0, "strength": "medium"},
    {"kind": "fireworks", "start": 4.0, "end": 5.0, "strength": "medium"},
], duration=10.0), 1280, 720, 30.0, folder=art_dir) or ""
check("폭죽은 막대마다 따로 얹는다 (묶으면 두 번째가 터지다 만 장면부터 보인다)",
      two_fire.count("t-1.000") == 1 and two_fire.count("t-4.000") == 1)


# ══════════════════════════════════════════════════════════════
# 4. 실제로 만들어 픽셀로 재기
# ══════════════════════════════════════════════════════════════
print("\n=== 4. 실제로 만들어 픽셀로 재기 ===")

try:
    import numpy as np
    from PIL import Image
    have_pixels = True
except Exception as exc:      # noqa: BLE001
    have_pixels = False
    print(f"      numpy/Pillow 가 없습니다: {exc}")

try:
    subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=30)
    have_ffmpeg = True
except Exception:      # noqa: BLE001
    have_ffmpeg = False

if not (have_pixels and have_ffmpeg):
    skip("픽셀 검사", "numpy/Pillow 또는 FFmpeg 이 없습니다")
else:
    CW, CH, CFPS, CSECS = 1280, 720, 30, 5.0

    def scene() -> Path | None:
        """결이 있는 화면. 색막대로 재면 '결을 얼마나 흐트러뜨리는가'를 못 잰다."""
        rng = np.random.default_rng(7)
        yy, xx = np.mgrid[0:CH, 0:CW].astype(np.float32)
        sky = np.clip(150 - yy / CH * 40, 0, 255)
        img = np.dstack([sky * 0.80, sky * 0.88, sky * 1.00]).astype(np.float32)
        low = yy > CH * 0.55
        for chan, tone in enumerate((120.0, 108.0, 82.0)):
            img[..., chan][low] = tone
        for size, amp in ((4, 26.0), (9, 18.0), (23, 12.0), (57, 9.0)):
            small = rng.normal(0.0, 1.0, (CH // size + 2, CW // size + 2)).astype(np.float32)
            img += (np.array(Image.fromarray(small).resize((CW, CH), Image.BICUBIC)) * amp)[..., None]
        for cx, cy, rad, col in ((330, 430, 74, (196, 168, 96)),
                                 (900, 380, 58, (86, 122, 150)),
                                 (640, 300, 40, (208, 196, 176))):
            spot = (xx - cx) ** 2 + (yy - cy) ** 2 < rad * rad
            for chan in range(3):
                img[..., chan][spot] = col[chan]
        img += rng.normal(0.0, 3.0, img.shape).astype(np.float32)
        png = art_dir / "scene.png"
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(png)
        dst = art_dir / "scene.mkv"
        done = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-loop", "1", "-i", str(png), "-t", f"{CSECS}", "-r", str(CFPS),
             "-vf", f"scale={CW + 40}:{CH + 24},crop={CW}:{CH}"
                    ":'20+18*sin(2*PI*0.10*t)':'12+8*sin(2*PI*0.07*t)'",
             "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(dst)],
            capture_output=True, timeout=600)
        return dst if done.returncode == 0 else None

    def render(clip: Path, vf: str, name: str, limit: int = 600):
        """FFmpeg 을 **그림이 있는 폴더에서** 돌린다 — 실제 렌더와 같은 조건이다."""
        dst = art_dir / f"{name}.mkv"
        dst.unlink(missing_ok=True)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(clip)]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-c:v", "ffv1", "-an", str(dst)]
        began = time.monotonic()
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=limit, cwd=str(art_dir))
        except subprocess.TimeoutExpired:
            return None, limit
        if done.returncode != 0:
            print(f"      렌더 실패({name}): {(done.stderr or '').strip()[:220]}")
            return None, time.monotonic() - began
        return dst, time.monotonic() - began

    def shot(video: Path, at: float):
        dst = art_dir / "_f.png"
        dst.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(dst)],
                       capture_output=True, timeout=120)
        return np.array(Image.open(dst).convert("RGB")).astype(np.float32)

    def grain(rgb) -> float:
        lum = rgb.mean(axis=2)
        return float((np.abs(np.diff(lum, axis=1)).mean()
                      + np.abs(np.diff(lum, axis=0)).mean()) / 2)

    def added(made: Path, plain: Path, at: float):
        """효과가 **더한 것만** 떼어 낸다. 원본이 움직이므로 두 시각을 그냥 비교하면 속는다."""
        return np.abs(shot(made, at) - shot(plain, at)).mean(axis=2) > 8

    clip = scene()
    plain, _ = render(clip, "", "plain") if clip else (None, 0)
    if plain is None:
        skip("픽셀 검사", "시험 화면을 만들지 못했습니다")
    else:
        base_in, base_out = shot(plain, 3.0), shot(plain, 1.0)
        check("시험 화면이 실제 영상처럼 결을 갖고 있다 (색막대가 아니다)",
              grain(base_in) > 3.0, f"국소대비 {grain(base_in):.2f}")

        # 폭죽은 한 판이 1초라 3.0초에는 이미 끝나 있다. 가장 화려한 시각을 찾아 잰다.
        WHEN = {"fireworks": 2.40}
        # 5단계도 같은 상한을 지킨다 (memory/effects-must-not-obscure-the-picture.md)
        CEIL = {"water_drops": 18.0, "bubbles": 18.0, "fireworks": 18.0}

        for kind in ART_KINDS:
            at = WHEN.get(kind, 3.0)
            pushes, areas = [], []
            for level in effects.STRENGTHS:
                made, _ = render(clip, flt(kind, strength=level), f"p_{kind}_{level}")
                if made is None:
                    pushes.append(None); areas.append(None); continue
                now = shot(made, at)
                gap = np.abs(now - shot(plain, at)).mean(axis=2)
                pushes.append(float(gap.mean()))
                areas.append(float((gap >= 8).mean() * 100))
                if level == "medium":
                    outside = int((np.abs(shot(made, 1.0) - base_out) > 0).sum())
                    check(f"{LABELS[kind]}: 구간 밖은 원본과 한 값도 다르지 않다",
                          outside == 0, f"다른 값 {outside:,}개")
                if level == "high":
                    check(f"{LABELS[kind]}: 결(디테일)을 지우거나 어수선하게 만들지 않는다",
                          0.80 <= grain(now) / grain(base_in) <= 1.40,
                          f"남은 결 {grain(now) / grain(base_in) * 100:.0f}% (허용 80~140%)")

            if None in pushes:
                check(f"{LABELS[kind]}: 세기 3단계", False, "렌더 실패")
                continue

            check(f"{LABELS[kind]}: 구간 안은 실제로 달라진다", pushes[1] > 0.05,
                  f"평균 밀림 {pushes[1]:.2f} · 덮인 면적 {areas[1]:.1f}%")
            check(f"{LABELS[kind]}: 세기가 셀수록 더 많이 걸린다",
                  pushes[0] < pushes[1] < pushes[2],
                  f"{pushes[0]:.2f} · {pushes[1]:.2f} · {pushes[2]:.2f}")
            gap1, gap2 = pushes[1] / max(pushes[0], 1e-6), pushes[2] / max(pushes[1], 1e-6)
            check(f"{LABELS[kind]}: 단계 사이가 1.3배 넘게 벌어진다 (가짜 선택지가 아니다)",
                  gap1 >= 1.3 and gap2 >= 1.3, f"간격 {gap1:.2f}배 · {gap2:.2f}배")
            check(f"{LABELS[kind]}: '많이'가 화면을 지나치게 덮지 않는다",
                  pushes[2] <= CEIL[kind],
                  f"평균 밀림 {pushes[2]:.1f} (상한 {CEIL[kind]:.0f}) · "
                  f"덮인 면적 {areas[2]:.1f}%")

        # ── 비눗방울은 실제로 위로 가는가 ────────────────────────
        #    무게중심으로 재면 안 된다 — 화면 가득한 무늬는 무게중심이 늘 가운데다.
        #    비 점검이 쓰는 방법(무늬를 굴려서 맞춰 보기)을 그대로 쓴다.
        made, _ = render(clip, flt("bubbles", start=0.0, end=5.0, strength="high"), "bb_up")
        if made is None:
            check("비눗방울: 실제로 위로 떠오른다", False, "렌더 실패")
        else:
            a = added(made, plain, 2.0)[:, 200:-200]
            b = added(made, plain, 2.0 + 10 / 30)[:, 200:-200]
            best, at_shift = -1.0, 0
            for shift in range(-40, 41):
                rolled = np.roll(a, shift, axis=0)
                union = int((rolled | b).sum())
                score = float((rolled & b).sum()) / union if union else 0.0
                if score > best:
                    best, at_shift = score, shift
            check("비눗방울: 실제로 **위로** 떠오른다 (아래로 가면 틀린 것이다)",
                  at_shift < 0,
                  f"10프레임 동안 세로로 {at_shift:+d}픽셀 (음수라야 위로 간 것) · 맞은 정도 {best:.2f}")

        # ── 폭죽은 시각마다 다른 장면인가 ────────────────────────
        made, took = render(clip, flt("fireworks", strength="high"), "fw_move")
        if made is None:
            check("폭죽: 시각마다 다른 장면이 나온다", False, "렌더 실패")
        else:
            early, late = added(made, plain, 2.10), added(made, plain, 2.60)
            union = int((early | late).sum())
            overlap = int((early & late).sum()) / union if union else 1.0
            check("폭죽: 시각마다 다른 장면이 나온다 (그림 한 장을 붙인 것이 아니다)",
                  overlap < 0.5 and union > 300,
                  f"2.10초 {int(early.sum()):,}화소 · 2.60초 {int(late.sum()):,}화소 · "
                  f"겹침 {overlap * 100:.0f}%")
            check("폭죽: 렌더가 끝난다 (loop 는 끝이 없어 shortest 를 빠뜨리면 안 끝난다)",
                  took < 200, f"{took:.1f}초에 끝남")

        # ── 굴절 지도의 자가 어긋나지 않는가 ─────────────────────
        #    이것이 이 파일에서 가장 중요한 검사다. 어긋나면 방울이 없는 자리까지
        #    2픽셀씩 밀려 **화면의 71%** 가 바뀐다 (실제로 그렇게 만들었다가 잡았다).
        made, _ = render(clip, flt("water_drops", strength="low",
                                   params={"size": 40}), "wd_scale")
        if made is not None:
            gap = np.abs(shot(made, 3.0) - shot(plain, 3.0)).mean(axis=2)
            check("물방울: 방울이 없는 자리는 건드리지 않는다 (지도의 자가 맞다)",
                  float((gap >= 8).mean() * 100) < 25.0,
                  f"덮인 면적 {float((gap >= 8).mean() * 100):.1f}% "
                  f"(자가 어긋나면 70%가 넘는다)")

        # ── 그림 파일이 실제로 만들어졌는가 ──────────────────────
        drawn = sorted(p.name for p in art_dir.glob("fx_*.png"))
        check("그림 파일이 실제로 만들어졌다", len(drawn) > 0, f"{len(drawn)}장")
        check("그림 이름에 필터를 깨뜨리는 문자가 없다",
              all(not (set(n) & set(",;[]':")) for n in drawn),
              "쉼표·콜론·대괄호가 들어가면 필터그래프가 통째로 깨진다")


# ══════════════════════════════════════════════════════════════
# 5. 서버가 화면에 알려 주는가
# ══════════════════════════════════════════════════════════════
print("\n=== 5. 서버가 알려 주는 목록 ===")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")

try:
    url = BASE + urllib.parse.quote("/api/system/effect-kinds", safe="/?&=.:%-")
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as res:
        served = json.loads(res.read().decode("utf-8") or "{}").get("kinds", [])
except Exception as exc:      # noqa: BLE001
    skip("서버 목록", f"서버에 연결하지 못했습니다 ({BASE}): {exc}")
else:
    names = {k["kind"] for k in served}
    check("서버가 셋을 모두 알려 준다 (화면 단추가 저절로 생긴다)",
          set(ART_KINDS) <= names,
          f"빠진 것: {sorted(set(ART_KINDS) - names) or '없음'}")
    fw = next((k for k in served if k["kind"] == "fireworks"), None)
    check("폭죽의 값 설명서가 함께 온다 (화면이 슬라이더를 그릴 수 있다)",
          bool(fw) and {"x", "y", "size"} <= {p["key"] for p in fw["params"]},
          f"폭죽의 값: {[p['label'] for p in fw['params']] if fw else None}")


# ══════════════════════════════════════════════════════════════
for leftover in art_dir.glob("*"):
    leftover.unlink(missing_ok=True)
art_dir.rmdir()

print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개"
      + (f" · 건너뜀 {len(skipped)}개" if skipped else ""))
for name in skipped:
    print(f"   · 건너뜀: {name}")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
sys.exit(1 if failed else 0)
