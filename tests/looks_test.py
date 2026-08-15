"""화면 효과 — 색감·강조·부분 흐림과 **값 조절(슬라이더)** 점검 (3~4단계).

사용법:
    python tests/looks_test.py                    FFmpeg 만 있으면 된다 (서버 불필요)
    MOVIEFIT_TEST_URL=http://127.0.0.1:8766 python tests/looks_test.py   화면까지

무엇을 지키는가:

  · 효과마다 다른 값(속도·자리·밝기)이 **자기 범위 안에서** 다듬어진다
    — 예전에는 모든 값을 0~100 으로 잘랐다. 그러면 속도를 100 위로 못 올린다
  · 값을 바꾸면 **화면에서 실제로 달라진다** (이름만 있는 손잡이가 아니다)
  · 자리를 정하는 효과는 **정말 그 자리에** 걸린다
  · 모든 효과가 구간을 지킨다 — 구간 밖은 원본과 한 값도 다르지 않다
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def skip(name: str, why: str) -> None:
    skipped.append(name)
    print(f"[ 건너뜀 ] {name}   — {why}")


def one(kind: str, start=2.0, end=4.0, strength="medium", params=None) -> list[dict]:
    bar = {"kind": kind, "start": start, "end": end, "strength": strength}
    if params:
        bar["params"] = params
    return effects.normalize([bar], duration=10.0)


def flt(kind: str, **over) -> str:
    width = over.pop("width", 1280)
    height = over.pop("height", 720)
    return effects.build_filter(one(kind, **over), width, height, 30.0) or ""


NEW_KINDS = ["blur_area", "spotlight", "vignette", "color_adjust",
             "warm", "cool", "vivid", "vintage", "mono", "box_mark"]
LABELS = {k: effects.KINDS[k]["label"] for k in NEW_KINDS if k in effects.KINDS}


# ══════════════════════════════════════════════════════════════
# 1. 등록표
# ══════════════════════════════════════════════════════════════
print("\n=== 1. 등록표 ===")

for kind in NEW_KINDS:
    check(f"등록표에 {kind} 가 있다", kind in effects.KINDS,
          LABELS.get(kind, "없음"))

check("효과가 16가지 등록되어 있다", len(effects.KINDS) == 16,
      f"실제 {len(effects.KINDS)}가지: {[k['label'] for k in effects.kind_list()]}")

check("모든 효과에 한 줄 설명이 붙어 있다",
      all(k.get("hint") for k in effects.KINDS.values()))

check("네모 테두리가 맨 마지막에 그려진다 (색감이 표시까지 물들이면 안 된다)",
      effects.KINDS["box_mark"]["order"] == max(k["order"] for k in effects.KINDS.values()))

check("색감 프리셋이 비·눈보다 나중에 온다 (효과까지 함께 물들어야 자연스럽다)",
      effects.KINDS["warm"]["order"] > effects.KINDS["rain"]["order"])


# ══════════════════════════════════════════════════════════════
# 2. 값(슬라이더) 체계
# ══════════════════════════════════════════════════════════════
print("\n=== 2. 값 조절 체계 ===")

listing = {k["kind"]: k for k in effects.kind_list()}

check("화면에 넘기는 값 설명서가 목록 형태다 (순서가 정해져야 슬라이더가 안 뒤바뀐다)",
      all(isinstance(k["params"], list) for k in listing.values()))

check("값마다 이름·최소·최대·기본값이 다 있다",
      all(all({"key", "label", "min", "max", "default"} <= set(p) for p in k["params"])
          for k in listing.values()),
      "하나라도 빠지면 화면이 슬라이더를 못 그린다")

check("비와 눈에 속도 조절이 붙어 있다",
      all(any(p["key"] == "speed" for p in listing[k]["params"]) for k in ("rain", "snow")),
      f"비: {[p['key'] for p in listing['rain']['params']]}")

speed_spec = next(p for p in listing["rain"]["params"] if p["key"] == "speed")
check("속도는 100%보다 위로도 올릴 수 있다",
      speed_spec["max"] > 100 and speed_spec["min"] < 100,
      f"{speed_spec['min']}~{speed_spec['max']}%, 기본 {speed_spec['default']}%")

fast = effects.normalize(
    [{"kind": "rain", "start": 1.0, "end": 2.0, "strength": "medium",
      "params": {"speed": 9999}}], duration=10.0)
check("범위를 넘는 속도는 최대값으로 잘린다",
      fast and fast[0]["params"]["speed"] == speed_spec["max"],
      f"실제 {fast[0]['params'] if fast else None}")

dark = effects.normalize(
    [{"kind": "color_adjust", "start": 1.0, "end": 2.0, "strength": "medium",
      "params": {"brightness": -500}}], duration=10.0)
check("밝기는 음수 범위를 갖는다 (예전처럼 0으로 잘리면 어둡게 못 한다)",
      dark and dark[0]["params"]["brightness"] == -100,
      f"실제 {dark[0]['params']['brightness'] if dark else None}")

junk = effects.normalize(
    [{"kind": "spotlight", "start": 1.0, "end": 2.0, "strength": "medium",
      "params": {"x": "왼쪽", "size": None}}], duration=10.0)
check("값이 숫자가 아니면 기본값으로 되돌린다",
      junk and junk[0]["params"]["x"] == 50 and junk[0]["params"]["size"] == 35,
      f"실제 {junk[0]['params'] if junk else None}")

check("등록표에 없는 값은 저장하지 않는다",
      "몰래" not in (effects.normalize(
          [{"kind": "vignette", "start": 1.0, "end": 2.0, "strength": "low",
            "params": {"몰래": 1}}], duration=10.0)[0]["params"]))

check("값이 없는 효과는 빈 값으로 남는다",
      effects.defaults_for("zoom_punch") == {}
      and effects.defaults_for("rain") == {"speed": 100, "opacity": 100})

slow = flt("rain", params={"speed": 40})
quick = flt("rain", params={"speed": 200})
check("속도를 바꾸면 필터가 실제로 달라진다",
      "mod(t*360.0" in slow and "mod(t*1800.0" in quick,
      f"40% → 360픽셀/초, 200% → 1800픽셀/초")

check("설정이 같은 막대끼리는 그림을 한 장만 만든다",
      (effects.build_filter(
          effects.normalize([
              {"kind": "rain", "start": 1.0, "end": 2.0, "strength": "medium"},
              {"kind": "rain", "start": 4.0, "end": 5.0, "strength": "medium"},
          ], duration=10.0), 1280, 720, 30.0) or "").count("noise=") == 1)

check("속도가 다르면 그림을 따로 만든다 (같이 쓰면 한쪽 속도가 무시된다)",
      (effects.build_filter(
          effects.normalize([
              {"kind": "rain", "start": 1.0, "end": 2.0, "strength": "medium",
               "params": {"speed": 50}},
              {"kind": "rain", "start": 4.0, "end": 5.0, "strength": "medium",
               "params": {"speed": 200}},
          ], duration=10.0), 1280, 720, 30.0) or "").count("noise=") == 2)


# ══════════════════════════════════════════════════════════════
# 3. 필터 문자열에 못 박은 것
# ══════════════════════════════════════════════════════════════
print("\n=== 3. 필터에 못 박은 것 ===")

check("따뜻하게는 eq 를 colorbalance 보다 **앞에** 둔다",
      flt("warm").index("eq=") < flt("warm").index("colorbalance="),
      "뒤에 두면 색공간 변환이 끼어 구간 밖 화소가 ±2 밀린다 (실측)")

check("빈티지도 eq 가 앞이다",
      flt("vintage").index("eq=") < flt("vintage").index("colorchannelmixer="))

check("모든 효과가 구간 지정을 필터에 넣는다",
      all("enable='between(t,2.000,4.000)" in flt(k) for k in NEW_KINDS),
      "빠지면 영상 전체에 걸린다")

check("주변 어둡게는 **검은 그림을 알파로** 얹는다 (밝기만 곱하면 색이 튄다)",
      "format=yuva420p" in flt("spotlight") and "lum=16" in flt("spotlight")
      and "overlay=0:0" in flt("spotlight")
      and "c0_mode=multiply" not in flt("spotlight"),
      "밝기(Y)만 줄이고 색차(U·V)를 두면 밝기에 견준 색이 커져 화면이 보라색이 된다")

check("비·눈은 밝기 면만 얹고 색 면은 건드리지 않는다",
      "c0_mode=screen" in flt("rain") and "c1_mode=normal" in flt("rain")
      and "c2_mode=normal" in flt("rain") and "c1_opacity=0" not in flt("rain"),
      "opacity=0 을 주면 색이 효과 그림의 중립값으로 덮여 화면이 흑백이 된다")

check("주변 어둡게의 마스크는 작은 자에서 그린 뒤 늘린다 (geq 는 느리다)",
      "scale=160:" in flt("spotlight") and "flags=bicubic" in flt("spotlight"))

check("부분 흐림은 네모만 오려서 흐린다 (화면 전체를 흐리지 않는다)",
      "crop=" in flt("blur_area") and "boxblur=" in flt("blur_area")
      and "overlay=" in flt("blur_area"))

wide = flt("box_mark", params={"x": 50, "y": 50, "w": 50, "h": 50})
check("네모 테두리의 자리와 크기가 화면 비율대로 픽셀이 된다",
      "w=640:h=360" in wide, f"화면 1280×720 의 50% → 640×360: {wide[:90]}")

edge = flt("box_mark", params={"x": 0, "y": 0, "w": 50, "h": 50})
check("네모가 화면 밖으로 나가지 않게 민다",
      "x=0:y=0" in edge, f"필터: {edge[:70]}")


# ══════════════════════════════════════════════════════════════
# 4. 실제로 만들어 픽셀로 재기
# ══════════════════════════════════════════════════════════════
print("\n=== 4. 실제로 만들어 픽셀로 재기 ===")

SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"

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

if not (have_pixels and have_ffmpeg and SAMPLE.is_file()):
    skip("픽셀 검사", "numpy/Pillow · FFmpeg · 샘플 영상 중 하나가 없습니다")
else:
    work = Path(tempfile.mkdtemp(prefix="looks_"))

    def render(vf: str | None, name: str, seconds: float = 5.0) -> Path | None:
        """무손실(ffv1)로 굽는다 — H.264 는 뒤 프레임을 미리 보고 압축을 정하므로
        구간 밖까지 값이 달라져 '필터가 샌 것'처럼 보인다."""
        dst = work / f"{name}.mkv"
        dst.unlink(missing_ok=True)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-i", str(SAMPLE), "-t", f"{seconds}"]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-c:v", "ffv1", "-an", str(dst)]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=900)
        if out.returncode != 0:
            print(f"      렌더 실패({name}): {(out.stderr or '').strip()[:250]}")
            return None
        return dst

    def shot(video: Path, at: float):
        dst = work / "_f.png"
        dst.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(dst)],
                       capture_output=True, timeout=120)
        return np.array(Image.open(dst).convert("RGB")).astype(np.int16)

    try:
        plain = render(None, "plain")
        base_out, base_in = shot(plain, 1.0), shot(plain, 3.0)

        # 값을 안 건드리면 아무 일도 안 하는 효과가 있으므로 시험용 값을 준다
        TRIALS = {
            "blur_area": {"x": 30, "y": 40, "w": 30, "h": 30},
            "spotlight": {"x": 35, "y": 50, "size": 25},
            "vignette": None,
            "color_adjust": {"brightness": 25, "contrast": 140, "saturation": 60},
            "warm": None, "cool": None, "vivid": None, "vintage": None, "mono": None,
            "box_mark": {"x": 30, "y": 40, "w": 25, "h": 25},
        }

        for kind in NEW_KINDS:
            made = render(flt(kind, params=TRIALS[kind]), f"k_{kind}")
            if made is None:
                check(f"{LABELS[kind]}: 실제로 만들어진다", False, "렌더 실패")
                continue
            outside = int((np.abs(shot(made, 1.0) - base_out) > 0).sum())
            inside = int((np.abs(shot(made, 3.0) - base_in) > 0).sum())
            check(f"{LABELS[kind]}: 구간 밖은 원본과 한 값도 다르지 않다",
                  outside == 0, f"다른 값 {outside:,}개")
            # 네모 테두리는 **선만** 그리므로 바뀌는 값이 원래 적다.
            # 320×180 테두리를 6픽셀 두께로 그리면 1만 8천 값쯤이 정상이다.
            least = 8000 if kind == "box_mark" else 20000
            check(f"{LABELS[kind]}: 구간 안은 실제로 달라진다",
                  inside > least, f"바뀐 값 {inside:,}개 (최소 {least:,})")

            # ── 색이 사라지지 않았는가.
            #    비·눈·주변 어둡게에서 **화면이 통째로 흑백이 되는 결함**이 실제로 났고,
            #    흑백으로만 재는 검사는 전부 통과했다. 그래서 색을 따로 잰다.
            #    색을 일부러 빼는 효과(흑백·빈티지·채도 내림)는 기준을 따로 둔다.
            def spread(image):
                return float(np.abs(image[:, :, 0] - image[:, :, 2]).mean())

            was, now = spread(base_in), spread(shot(made, 3.0))
            if kind == "mono":
                check("흑백: 색이 확실히 빠진다", now < was * 0.1,
                      f"색의 진하기 {was:.1f} → {now:.1f}")
            elif kind in ("vintage", "color_adjust"):
                check(f"{LABELS[kind]}: 색을 줄이되 없애지는 않는다",
                      was * 0.15 < now < was * 0.95, f"색의 진하기 {was:.1f} → {now:.1f}")
            else:
                floor = 0.45 if kind in ("spotlight", "vignette") else 0.9
                check(f"{LABELS[kind]}: 색이 살아 있다 (화면이 흑백이 되지 않는다)",
                      now > was * floor,
                      f"색의 진하기 {was:.1f} → {now:.1f} "
                      f"(어두워지는 효과는 색차도 함께 줄어 기준이 낮다)")

        # ── 자리를 정하는 효과가 정말 그 자리에 걸리는가 ──────────
        print("\n--- 자리 지정이 실제로 먹히는가 ---")
        # 주변 어둡게는 여기 넣으면 안 된다 — 그것은 **밝은 곳 말고 나머지**를 바꾸므로
        # 바뀐 곳의 가운데가 오히려 반대로 움직인다. 따로 잰다(바로 아래).
        for kind, left_params, right_params in (
            ("box_mark", {"x": 20, "y": 50, "w": 20, "h": 20},
             {"x": 80, "y": 50, "w": 20, "h": 20}),
            ("blur_area", {"x": 20, "y": 50, "w": 25, "h": 25},
             {"x": 80, "y": 50, "w": 25, "h": 25}),
        ):
            spots = []
            for side, params in (("왼쪽", left_params), ("오른쪽", right_params)):
                made = render(flt(kind, params=params), f"p_{kind}_{side}")
                if made is None:
                    spots.append(None); continue
                diff = np.abs(shot(made, 3.0) - base_in).sum(axis=2)
                if diff.sum() == 0:
                    spots.append(None); continue
                columns = diff.sum(axis=0)
                spots.append(float((columns * np.arange(columns.size)).sum() / columns.sum()))
            if None in spots:
                check(f"{LABELS[kind]}: 자리를 옮기면 효과도 옮겨진다", False, "측정 실패")
                continue
            check(f"{LABELS[kind]}: 자리를 옮기면 효과도 실제로 옮겨진다",
                  spots[1] - spots[0] > 300,
                  f"바뀐 곳의 가운데: 왼쪽 {spots[0]:.0f}픽셀 → 오른쪽 {spots[1]:.0f}픽셀"
                  f" (화면 너비 1280)")

        # ── 주변 어둡게: 밝게 남는 곳이 정한 자리를 따라가는가 ──────
        #    바뀐 곳이 아니라 **안 바뀐 곳**이 옮겨져야 한다.
        LEFT, RIGHT = slice(190, 330), slice(950, 1090)
        kept = {}
        for side, params in (("왼쪽", {"x": 20, "y": 50, "size": 20}),
                             ("오른쪽", {"x": 80, "y": 50, "size": 20})):
            made = render(flt("spotlight", params=params), f"sp_{side}")
            if made is None:
                kept[side] = None; continue
            got, was = shot(made, 3.0).mean(axis=2), base_in.mean(axis=2)
            rows = slice(300, 420)
            kept[side] = (
                float(got[rows, LEFT].mean() / max(1.0, was[rows, LEFT].mean())),
                float(got[rows, RIGHT].mean() / max(1.0, was[rows, RIGHT].mean())),
            )
        if None not in kept.values():
            # 문턱 0.2 → 0.10. 효과를 일부러 순하게 바꿨기 때문이다(2026-08-15).
            # 재는 것은 **자리가 따라오는가**이지 얼마나 어두운가가 아니므로, 방향이
            # 뚜렷하면 통과해야 맞다. 0.10 은 잡음(±0.01)보다 열 배 크다.
            check("주변 어둡게: 밝게 남는 곳이 정한 자리를 따라간다",
                  kept["왼쪽"][0] > kept["왼쪽"][1] + 0.10
                  and kept["오른쪽"][1] > kept["오른쪽"][0] + 0.10,
                  f"자리를 왼쪽에 두면 왼쪽 {kept['왼쪽'][0] * 100:.0f}% / "
                  f"오른쪽 {kept['왼쪽'][1] * 100:.0f}% 남고, "
                  f"오른쪽에 두면 왼쪽 {kept['오른쪽'][0] * 100:.0f}% / "
                  f"오른쪽 {kept['오른쪽'][1] * 100:.0f}% 남는다")
        else:
            check("주변 어둡게: 밝게 남는 곳이 정한 자리를 따라간다", False, "측정 실패")

        # ── 주변 어둡게는 가운데는 살리고 둘레만 어둡게 하는가 ─────
        #    작은 귀퉁이 한 조각으로 재면 안 된다. 시험 영상은 왼쪽 귀퉁이가 **원래
        #    새까매서** 밝기 비율이 0/0 이 된다(실제로 여기서 0으로 나눠 터졌다).
        #    테두리 전체의 밝기 **합**으로 재면 그 문제가 없다.
        def edge_keep(video) -> float:
            got, was = shot(video, 3.0).mean(axis=2), base_in.mean(axis=2)
            band = np.ones(got.shape, dtype=bool)
            band[100:-100, 180:-180] = False          # 가운데를 뺀 테두리
            return float(got[band].sum() / max(1.0, was[band].sum()))

        made = render(flt("spotlight", params={"x": 50, "y": 50, "size": 25}), "sp_mid")
        if made is not None:
            got, was = shot(made, 3.0).mean(axis=2), base_in.mean(axis=2)
            mid = float(got[330:390, 610:670].sum() / max(1.0, was[330:390, 610:670].sum()))
            # 예전에는 "테두리가 60% 아래로 어두워질 것"을 요구했다. 그것은 **과하게
            # 어두운 상태를 점검이 강제하던 것**이라 바꿨다(2026-08-15). 재야 할 것은
            # 가운데와 둘레의 **차이**이지 둘레의 절대 어둡기가 아니다.
            rim = edge_keep(made)
            check("주변 어둡게: 가운데는 밝기를 지키고 둘레만 어두워진다",
                  mid > 0.93 and mid - rim > 0.12,
                  f"가운데 {mid * 100:.0f}% 유지 · 테두리 {rim * 100:.0f}% 유지"
                  f" (차이 {(mid - rim) * 100:.0f}%p)")

        # ── 흑백이 정말 색을 빼는가 ─────────────────────────────
        made = render(flt("mono"), "mono_chk")
        if made is not None:
            got = shot(made, 3.0)
            spread = float(np.abs(got[:, :, 0] - got[:, :, 2]).mean())
            before = float(np.abs(base_in[:, :, 0] - base_in[:, :, 2]).mean())
            check("흑백: 빨강과 파랑의 차이가 사라진다",
                  spread < max(1.0, before) * 0.35 or spread < 1.5,
                  f"효과 전 {before:.2f} → 효과 후 {spread:.2f}")

        # ── 따뜻하게는 정말 따뜻해지는가 (이름과 결과가 맞는가) ─────
        #    "원본과 달라졌다"만 보면 따뜻하게와 차갑게가 **서로 뒤바뀌어 있어도**
        #    둘 다 통과한다. 어느 쪽으로 달라졌는지를 봐야 한다.
        #    재는 바탕도 중요하다. 영상 원본으로 재면 원본이 이미 갖고 있는 색이
        #    섞여 들어가고, 채도를 올리는 것만으로도 그 색이 커져 **색이 옮겨간 것처럼
        #    보인다.** 실제로 파란 사진에서 '따뜻하게'가 더 파래지는 것으로 잡혔다.
        #    **중립 회색**에 걸면 오직 효과가 만든 색만 남는다.
        def warmth(look_filter: str) -> float:
            """중립 회색에 걸었을 때 빨강에서 파랑을 뺀 값. 클수록 따뜻하다."""
            dst = work / "_g.png"
            dst.unlink(missing_ok=True)
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:d=1:r=10"]
            if look_filter:
                cmd += ["-vf", look_filter]
            cmd += ["-frames:v", "1", str(dst)]
            subprocess.run(cmd, capture_output=True, timeout=120)
            rgb = np.array(Image.open(dst).convert("RGB")).astype(np.int16)
            return float(rgb[:, :, 0].mean() - rgb[:, :, 2].mean())

        # 구간 지정을 뺀 순수한 색 필터로 잰다 (회색 그림은 1프레임뿐이다)
        def look_only(kind: str, strength: str = "medium", opacity: float = 100) -> str:
            return ",".join(effects.look_filters(kind, strength, opacity))

        flat = warmth("")
        hot, cold = warmth(look_only("warm")), warmth(look_only("cool"))
        check("따뜻하게는 붉은 쪽으로, 차갑게는 푸른 쪽으로 간다",
              hot > flat + 8 and cold < flat - 8,
              f"중립 회색 {flat:+.1f} → 따뜻하게 {hot:+.1f} · 차갑게 {cold:+.1f}")
        check("따뜻하게와 차갑게가 서로 뚜렷이 다르다", hot - cold > 30,
              f"둘의 차이 {hot - cold:.1f}")

        for kind in ("warm", "cool"):
            steps = [abs(warmth(look_only(kind, s)) - flat)
                     for s in ("low", "medium", "high")]
            gaps = (steps[1] / max(steps[0], 0.1), steps[2] / max(steps[1], 0.1))
            check(f"{LABELS[kind]}: 세기 3단계가 1.3배 넘게 벌어진다",
                  steps[0] < steps[1] < steps[2] and min(gaps) >= 1.3,
                  f"색이 옮겨간 정도 {steps[0]:.0f} → {steps[1]:.0f} → {steps[2]:.0f}"
                  f"  (간격 {gaps[0]:.2f}배 · {gaps[1]:.2f}배)")

        bright = render(flt("color_adjust", params={"brightness": 60, "contrast": 100,
                                                    "saturation": 100}), "t_up")
        dim = render(flt("color_adjust", params={"brightness": -60, "contrast": 100,
                                                 "saturation": 100}), "t_down")
        if bright is not None and dim is not None:
            up, down = float(shot(bright, 3.0).mean()), float(shot(dim, 3.0).mean())
            check("밝기 슬라이더를 올리면 밝아지고 내리면 어두워진다",
                  up > base_in.mean() + 5 and down < base_in.mean() - 5,
                  f"원본 {base_in.mean():.0f} → 올림 {up:.0f} · 내림 {down:.0f}")

        # ── 세기 3단계가 화면에서 구별되는가 ───────────────────
        print("\n--- 세기 3단계가 화면에서 구별되는가 ---")
        for kind in ("vignette", "vivid", "spotlight", "blur_area"):
            amounts = []
            for level in ("low", "medium", "high"):
                made = render(flt(kind, strength=level, params=TRIALS[kind]),
                              f"s_{kind}_{level}")
                amounts.append(float(np.abs(shot(made, 3.0) - base_in).mean())
                               if made is not None else -1.0)
            ok = -1.0 not in amounts and amounts[0] < amounts[1] < amounts[2]
            gaps = ""
            if -1.0 not in amounts and amounts[0] > 0:
                gaps = (f"  간격 {amounts[1] / amounts[0]:.2f}배 ·"
                        f" {amounts[2] / amounts[1]:.2f}배")
            check(f"{LABELS[kind]}: 세기가 셀수록 화면이 더 많이 바뀐다", ok,
                  f"약 {amounts[0]:.2f} · 보통 {amounts[1]:.2f} · 많이 {amounts[2]:.2f}{gaps}")

        # 주변 어둡게는 위 지표(화면 평균 변화)가 둔하다 — 세 단계 모두 화면 대부분이
        # 어두워지므로 평균만 보면 6~8%밖에 안 벌어진다. 사용자가 실제로 느끼는 것은
        # **둘레가 얼마나 어두운가**이므로 그것으로 다시 잰다.
        rest = []
        for level in ("low", "medium", "high"):
            made = render(flt("spotlight", strength=level,
                              params={"x": 50, "y": 50, "size": 25}), f"d_{level}")
            rest.append(edge_keep(made) if made is not None else None)
        if None not in rest and min(rest) > 0:
            # ⚠ 예전에는 **남은 밝기끼리** 나눴다(rest[0]/rest[1]). 그것은 '어두워지는
            #   정도'가 아니다 — 효과가 셀 때만 우연히 1.3배를 넘고, 순해지면 세 단계가
            #   잘 벌어져 있어도 1에 가까워진다. 실제로 순하게 바꾸자 1.13배로 나와
            #   멀쩡한 사다리를 실패로 판정했다. 재야 할 것은 **어두워진 양**이다.
            dark = [1.0 - r for r in rest]
            gap1, gap2 = dark[1] / dark[0], dark[2] / dark[1]
            check("주변 어둡게: 세 단계의 어두워지는 정도가 1.3배 넘게 벌어진다",
                  dark[0] < dark[1] < dark[2] and gap1 >= 1.3 and gap2 >= 1.3,
                  f"테두리가 어두워진 양 {dark[0] * 100:.0f}% → {dark[1] * 100:.0f}%"
                  f" → {dark[2] * 100:.0f}%  (간격 {gap1:.2f}배 · {gap2:.2f}배)")
            # 위쪽 한계 — 이것이 없어서 사다리가 위로만 밀려 올라갔다.
            # (memory/effects-must-not-obscure-the-picture.md)
            check("주변 어둡게: 가장 센 단계도 둘레 밝기를 62% 밑으로 떨어뜨리지 않는다",
                  rest[2] >= 0.62,
                  f"'많이'에서 테두리에 남는 밝기 {rest[2] * 100:.0f}% (최소 62%)")
            check("주변 어둡게: 가장 약한 단계도 눈에 띄게 어두워진다",
                  dark[0] >= 0.08,
                  f"'약하게'가 어둡게 하는 양 {dark[0] * 100:.0f}% (최소 8%)")
        else:
            check("주변 어둡게: 세 단계의 어두워지는 정도가 1.3배 넘게 벌어진다",
                  False, "측정 실패")

        # ── 속도 조절이 화면에서 실제로 먹히는가 ─────────────────
        print("\n--- 속도 조절 ---")
        for kind, base_speed in (("rain", 900), ("snow", 115)):
            moves = []
            for pace in (50, 150):
                made = render(flt(kind, start=0.0, end=5.0, params={"speed": pace}),
                              f"v_{kind}_{pace}")
                if made is None:
                    moves.append(None); continue
                # 효과가 밝힌 자리만 떼어 낸다 — 원본 화면이 섞이면 못 잰다
                a = ((shot(made, 2.0) - shot(plain, 2.0)).mean(axis=2) > 8)[160:-160]
                b = ((shot(made, 2.0 + 1 / 30) - shot(plain, 2.0 + 1 / 30)).mean(axis=2) > 8)[160:-160]
                best, at = -1.0, 0
                for shift in range(0, 110):
                    rolled = np.roll(a, shift, axis=0)
                    union = int((rolled | b).sum())
                    score = float((rolled & b).sum()) / union if union else 0.0
                    if score > best:
                        best, at = score, shift
                moves.append(at)
            if None in moves:
                check(f"{LABELS.get(kind, kind)}: 속도를 올리면 더 빨리 떨어진다", False, "측정 실패")
                continue
            want_slow = round(base_speed * 0.5 / 30)
            want_fast = round(base_speed * 1.5 / 30)
            check(f"{effects.KINDS[kind]['label']}: 속도를 올리면 실제로 더 빨리 떨어진다",
                  moves[1] > moves[0],
                  f"50% → {moves[0]}픽셀/프레임 (기대 {want_slow}) · "
                  f"150% → {moves[1]}픽셀/프레임 (기대 {want_fast})")

    finally:
        for leftover in work.glob("*"):
            leftover.unlink(missing_ok=True)
        work.rmdir()


# ══════════════════════════════════════════════════════════════
# 5. 화면을 가리지 않는가 (위쪽 한계)
# ══════════════════════════════════════════════════════════════
#
# 왜 이 절이 따로 있는가: 세기 3단계를 정할 때 지키던 기준은 "단계가 1.3배 넘게
# 벌어질 것" **하나뿐**이었다. 그것은 아래에서 미는 힘만 주므로 '많이'가 끝없이
# 세졌고, 사용자가 "효과들이 화면을 너무 가려 영상에 집중할 수 없다"고 지적했다.
# 그때 점검 715개는 전부 통과하고 있었다.
# (memory/effects-must-not-obscure-the-picture.md)
#
# 그리고 **여기서만 결이 있는 화면을 따로 만들어 쓴다.** 위 4절이 쓰는 샘플은
# 색막대라 국소대비가 0.69밖에 안 되어 '결을 얼마나 흐트러뜨리는가'를 아예 잴 수
# 없다. 실제 영상과 비슷한 성질(중간 밝기·적당한 색·결)을 갖춘 화면이 필요하다.
print("\n=== 5. 화면을 가리지 않는가 ===")

if not (have_pixels and have_ffmpeg):
    skip("가림 한계", "numpy/Pillow 또는 FFmpeg 이 없습니다")
else:
    CW, CH, CFPS, CSECS = 1280, 720, 30, 5.0
    cover_work = Path(tempfile.mkdtemp(prefix="cover_"))

    # 4절의 shot() 을 쓰면 안 된다 — 그 함수가 쓰는 임시 폴더는 4절 끝에서 지워진다.
    def cover_shot(video: Path, at: float):
        dst = cover_work / "_f.png"
        dst.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(dst)],
                       capture_output=True, timeout=120)
        return np.array(Image.open(dst).convert("RGB")).astype(np.float32)

    def make_textured(dst: Path) -> Path | None:
        """결이 있는 풍경 비슷한 화면. 통계를 실제 영상에 맞춘다."""
        rng = np.random.default_rng(7)
        yy, xx = np.mgrid[0:CH, 0:CW].astype(np.float32)
        sky = np.clip(150 - yy / CH * 40, 0, 255)
        img = np.dstack([sky * 0.80, sky * 0.88, sky * 1.00]).astype(np.float32)
        ground = yy > CH * 0.55
        for chan, tone in enumerate((120.0, 108.0, 82.0)):
            img[..., chan][ground] = tone
        for scale, amp in ((4, 26.0), (9, 18.0), (23, 12.0), (57, 9.0)):
            small = rng.normal(0.0, 1.0, (CH // scale + 2, CW // scale + 2)).astype(np.float32)
            img += (np.array(Image.fromarray(small).resize((CW, CH), Image.BICUBIC)) * amp)[..., None]
        for cx, cy, rad, col in ((330, 430, 74, (196, 168, 96)),
                                 (900, 380, 58, (86, 122, 150)),
                                 (640, 300, 40, (208, 196, 176))):
            spot = (xx - cx) ** 2 + (yy - cy) ** 2 < rad * rad
            for chan in range(3):
                img[..., chan][spot] = col[chan]
        img += rng.normal(0.0, 3.0, img.shape).astype(np.float32)
        png = cover_work / "scene.png"
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(png)
        done = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-loop", "1", "-i", str(png), "-t", f"{CSECS}", "-r", str(CFPS),
             "-vf", f"scale={CW + 40}:{CH + 24},crop={CW}:{CH}"
                    ":'20+18*sin(2*PI*0.10*t)':'12+8*sin(2*PI*0.07*t)'",
             "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(dst)],
            capture_output=True, timeout=600)
        return dst if done.returncode == 0 else None

    def cover_render(clip: Path, vf: str, name: str) -> Path | None:
        dst = cover_work / f"{name}.mkv"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(clip)]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-c:v", "ffv1", "-an", str(dst)]
        done = subprocess.run(cmd, capture_output=True, timeout=900)
        return dst if done.returncode == 0 else None

    def grain(rgb) -> float:
        """결이 얼마나 살아 있는가 — 이웃 화소와의 차이 평균."""
        lum = rgb.mean(axis=2)
        return float((np.abs(np.diff(lum, axis=1)).mean()
                      + np.abs(np.diff(lum, axis=0)).mean()) / 2)

    def colourful(rgb) -> float:
        """**밝기에 견준** 색의 진하기 — 사람이 '색이 진하다'고 느끼는 값.

        4절의 `spread()`(빨강-파랑의 절대 차이)로는 이 결함을 못 잡는다. 빨강과
        파랑의 차이는 `1.402(V-128) + 1.772(U-128)` 이라 **밝기와 아무 상관이 없어서**,
        밝기만 반으로 줄여도 그 값은 그대로다. 실제로 주변 어둡게가 화면을 보라색으로
        물들이는 동안 그 검사는 통과하고 있었다.
        """
        top, bottom = rgb.max(axis=2), rgb.min(axis=2)
        return float(((top - bottom) / np.maximum(top, 1.0)).mean())

    # 효과마다 '가림'의 뜻이 다르므로 재는 자도 다르다.
    #   push   — 화면 전체 평균 밀림의 상한 (0~255 자)
    #   light  — '많이'에서도 남아 있어야 할 밝기 비율 (어둡게 하는 효과)
    #   tex    — 결이 얼마나 늘거나 줄어도 되는가 (비·눈은 결을 **더한다**)
    #   colour — 색이 얼마나 진해져도 되는가. **어둡게 하는 효과에만** 건다.
    #            색을 바꾸는 것이 목적인 효과(따뜻하게·빈티지…)에는 걸지 않는다
    LIMITS = {
        "rain":     {"push": 18.0, "tex": (0.80, 1.40)},
        "snow":     {"push": 18.0, "tex": (0.80, 1.40)},
        "spotlight": {"light": 0.62, "colour": 1.15},
        "vignette":  {"light": 0.62, "colour": 1.15},
        "warm":     {"push": 18.0},
        "cool":     {"push": 18.0},
        "vivid":    {"push": 18.0},
        "vintage":  {"push": 18.0},
    }
    # 상한을 두지 않는 것과 그 이유 — 빠뜨린 것이 아니라 **일부러** 뺀 것이다.
    EXEMPT = {
        "zoom_punch": "화면을 덮는 것이 아니라 옮기는 효과다",
        "color_adjust": "사용자가 슬라이더로 직접 정한다",
        "mono": "색을 빼는 것이 목적이고 결은 지우지 않는다",
        "blur_area": "정한 자리만 건드리는 것이 목적이다",
        "box_mark": "정한 자리만 건드리는 것이 목적이다",
        # 아래 셋은 그림 파일이 있어야 만들어지므로 렌더 방법이 다르다.
        # 같은 잣대(덮인 면적·평균 밀림·남은 결)로 tests/artfx_test.py 에서 잰다.
        "water_drops": "그림 파일을 쓰므로 artfx_test.py 에서 같은 잣대로 잰다",
        "bubbles": "그림 파일을 쓰므로 artfx_test.py 에서 같은 잣대로 잰다",
        "fireworks": "그림 파일을 쓰므로 artfx_test.py 에서 같은 잣대로 잰다",
    }

    try:
        scene = make_textured(cover_work / "scene.mkv")
        flat = cover_render(scene, "", "flat") if scene else None
        if flat is None:
            skip("가림 한계", "시험 화면을 만들지 못했습니다")
        else:
            ref = cover_shot(flat, 3.0)
            check("시험 화면이 실제 영상처럼 결을 갖고 있다 (색막대가 아니다)",
                  grain(ref) > 3.0,
                  f"국소대비 {grain(ref):.2f} (색막대는 0.7 언저리다)")

            check("상한을 두지 않은 효과에는 그 이유가 적혀 있다",
                  set(LIMITS) | set(EXEMPT) == set(effects.KINDS),
                  f"상한 {len(LIMITS)}종 · 면제 {len(EXEMPT)}종 / 전체 {len(effects.KINDS)}종")

            for kind, rule in LIMITS.items():
                label = effects.KINDS[kind]["label"]
                seen = {}
                for level in ("low", "high"):
                    made = cover_render(scene, flt(kind, strength=level), f"c_{kind}_{level}")
                    seen[level] = cover_shot(made, 3.0) if made else None
                if seen["low"] is None or seen["high"] is None:
                    check(f"{label}: 가림 한계", False, "렌더 실패")
                    continue

                soft = float(np.abs(seen["low"] - ref).mean())
                hard = float(np.abs(seen["high"] - ref).mean())

                # 아래쪽 — '약하게'가 아무 일도 안 하면 이름만 있는 가짜 단계다.
                # 값을 낮추다가 실제로 이 상태를 만든 적이 있다 (평균 밀림 0.00).
                check(f"{label}: '약하게'가 아무 일도 안 하지 않는다",
                      soft > 0.3, f"평균 밀림 {soft:.2f} (최소 0.3)")

                if "push" in rule:
                    check(f"{label}: '많이'가 화면을 지나치게 덮지 않는다",
                          hard <= rule["push"],
                          f"평균 밀림 {hard:.1f} (상한 {rule['push']:.0f})")
                if "light" in rule:
                    left = float(seen["high"].mean() / ref.mean())
                    check(f"{label}: '많이'에서도 화면 밝기가 남아 있다",
                          left >= rule["light"],
                          f"남은 밝기 {left * 100:.0f}% (최소 {rule['light'] * 100:.0f}%)")
                if "colour" in rule:
                    # 어둡게 하는 효과가 **색을 진하게 만들면 안 된다.** 밝기만 줄이고
                    # 색차를 그대로 두면 화면이 보라색으로 물든다 — 실제로 그렇게
                    # 만들었다가 데모를 눈으로 보고 잡았다(색의 진하기 150%).
                    tint = colourful(seen["high"]) / colourful(ref)
                    check(f"{label}: 어두워질 때 색이 튀지 않는다",
                          tint <= rule["colour"],
                          f"색의 진하기 {tint * 100:.0f}% "
                          f"(상한 {rule['colour'] * 100:.0f}%)")
                if "tex" in rule:
                    low_t, high_t = rule["tex"]
                    kept = grain(seen["high"]) / grain(ref)
                    # 결이 **늘어나는 것도** 가리는 것이다 — 화면이 어수선해져
                    # 시선이 내용이 아니라 효과로 간다. 비 '많이'가 193%였다.
                    check(f"{label}: '많이'가 화면을 어수선하게 만들지 않는다",
                          low_t <= kept <= high_t,
                          f"남은 결 {kept * 100:.0f}% (허용 {low_t * 100:.0f}~{high_t * 100:.0f}%)")

            # ── 5-2. 진하기(투명 정도)를 사용자가 정할 수 있는가 ──────────
            #
            # 세기 3단계만으로는 원하는 만큼을 못 고른다는 지적을 받아 붙인 손잡이다.
            # 두 가지를 함께 지켜야 한다:
            #
            #   ① 기본값이 **반드시 100%** 여야 한다. 기본값을 올리면 위 상한 점검이
            #      더 진한 값을 재게 되어, 14절에서 값을 낮춘 일이 통째로 무의미해진다.
            #   ② 슬라이더가 **실제로 화면을 바꿔야** 한다. 이름만 있는 손잡이는
            #      사용자를 속이는 것이다 (memory/options-must-actually-differ.md).
            #
            # 흑백만 '약하게'에서 잰다. '보통'·'많이'는 이미 채도가 0이라 진하기를
            # 100% 위로 올려도 더 뺄 색이 없다(실측 1.00배). 그것은 가짜 손잡이가
            # 아니라 **물리적인 끝**이고, 아래쪽으로는 정상적으로 움직인다.
            OPACITY_KINDS = {"spotlight": "high", "vignette": "high",
                             "rain": "high", "snow": "high", "warm": "high",
                             "cool": "high", "vivid": "high", "vintage": "high",
                             "mono": "low"}

            check("진하기 슬라이더가 14절에서 값을 낮춘 효과 전부에 붙어 있다",
                  {k for k, s in effects.KINDS.items() if "opacity" in s["params"]}
                  == set(OPACITY_KINDS),
                  f"붙은 것 {sorted(k for k, s in effects.KINDS.items() if 'opacity' in s['params'])}")

            check("진하기의 기본값이 100%다 (기본값을 올리면 위 상한 점검이 무력해진다)",
                  all(effects.defaults_for(k)["opacity"] == 100 for k in OPACITY_KINDS),
                  f"실제 {[effects.defaults_for(k)['opacity'] for k in OPACITY_KINDS]}")

            for kind, level in OPACITY_KINDS.items():
                label = effects.KINDS[kind]["label"]
                steps, shots = [], {}
                for opa in (50, 100, 200):
                    made = cover_render(scene, flt(kind, strength=level,
                                                   params={"opacity": opa}),
                                        f"o_{kind}_{opa}")
                    shots[opa] = cover_shot(made, 3.0) if made else None
                    steps.append(float(np.abs(shots[opa] - ref).mean())
                                 if made else None)
                # 진하기를 끝까지 올려도 어둡게 하는 효과가 색을 튀게 하면 안 된다.
                # 슬라이더는 사용자가 정하는 것이지만, **망가진 그림**을 내놓는 것은
                # 사용자가 정한 것이 아니라 만든 쪽의 결함이다.
                if kind in LIMITS and "colour" in LIMITS[kind] and shots[200] is not None:
                    tint = colourful(shots[200]) / colourful(ref)
                    check(f"{label}: 진하기를 끝까지 올려도 색이 튀지 않는다",
                          tint <= LIMITS[kind]["colour"],
                          f"진하기 200%에서 색의 진하기 {tint * 100:.0f}% "
                          f"(상한 {LIMITS[kind]['colour'] * 100:.0f}%)")
                if None in steps:
                    check(f"{label}: 진하기가 화면을 실제로 바꾼다", False, "렌더 실패")
                    continue
                gaps = (steps[1] / max(steps[0], 1e-6), steps[2] / max(steps[1], 1e-6))
                check(f"{label}: 진하기가 화면을 실제로 바꾼다 (이름만 있는 손잡이가 아니다)",
                      steps[0] < steps[1] < steps[2] and min(gaps) >= 1.3,
                      f"50% {steps[0]:.2f} · 100% {steps[1]:.2f} · 200% {steps[2]:.2f}"
                      f"  (간격 {gaps[0]:.2f}배 · {gaps[1]:.2f}배)")
    finally:
        for leftover in cover_work.glob("*"):
            leftover.unlink(missing_ok=True)
        cover_work.rmdir()


# ══════════════════════════════════════════════════════════════
# 6. 서버가 화면에 제대로 알려 주는가
# ══════════════════════════════════════════════════════════════
print("\n=== 6. 서버가 알려 주는 목록 ===")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")


def api(path: str, timeout: int = 30):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


try:
    served = api("/api/system/effect-kinds").get("kinds", [])
except Exception as exc:      # noqa: BLE001
    skip("서버 목록", f"서버에 연결하지 못했습니다 ({BASE}): {exc}")
else:
    check("서버가 16가지를 모두 알려 준다", len(served) == 16,
          f"실제 {len(served)}가지")
    check("서버가 값 설명서까지 함께 알려 준다 (화면이 슬라이더를 그릴 수 있다)",
          any(k["kind"] == "rain" and any(p["key"] == "speed" for p in k["params"])
              for k in served),
          f"비의 값: {[p['key'] for k in served if k['kind'] == 'rain' for p in k['params']]}")
    # 2026-08-15 에 색감 계열 전부에 진하기 슬라이더가 붙어, 값이 하나도 없는 효과는
    # 줌 강조만 남았다.
    check("값이 필요 없는 효과는 빈 목록으로 온다",
          all(k["params"] == [] for k in served if k["kind"] == "zoom_punch"))
    check("색감 계열에는 진하기 슬라이더가 함께 온다",
          all(any(p["key"] == "opacity" for p in k["params"])
              for k in served if k["kind"] in ("vignette", "warm", "mono")),
          f"빈티지의 값: {[p['key'] for k in served if k['kind'] == 'vintage' for p in k['params']]}")


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
