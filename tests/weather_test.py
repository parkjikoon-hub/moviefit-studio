"""화면 효과 — 비 · 눈 점검 (2단계).

사용법:
    python tests/weather_test.py

    · FFmpeg 만 있으면 4절까지 돈다 (서버가 필요 없다). 여기가 이 점검의 핵심이다.
    · 서버까지 켜져 있으면 5절(실물 렌더·자막 생존)까지 돈다.
        MOVIEFIT_TEST_URL=http://127.0.0.1:8766 python tests/weather_test.py

이 점검이 무엇을 지키는가 — 비·눈은 **오류 없이 틀리기 쉬운** 부류다. 실제로 만드는
동안 다음이 전부 "FFmpeg 종료 코드 0 · 파일 정상 · 그런데 틀림"으로 나타났다:

  · 문턱값을 화면 눈금(0~255)으로 적어 필터 눈금(16~235)의 최대치를 넘김 → 점이 0개
  · 레이어의 검정을 16으로 둠 → 아무것도 없는 자리까지 밝아져 **온 화면에 안개**
  · 잘라내는 창을 아래로 내림 → 비가 **하늘로 솟음**
  · 합성 전에 색공간을 왕복시킴 → 효과를 켜기만 해도 **영상 전체 색이 변함**

그래서 이 점검은 "그림이 나왔다"로 판정하지 않는다. 효과를 건 영상과 안 건 영상의
**픽셀을 직접 대조**하고, 특히 **구간 바깥이 한 값도 다르지 않은지**를 본다.
"""

from __future__ import annotations

import json
import math
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

from app.core import effects  # noqa: E402

passed: list[str] = []
failed: list[str] = []
skipped: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def skip(name: str, why: str) -> None:
    skipped.append(name)
    print(f"[ 건너뜀 ] {name}   — {why}")


def bars(kind: str, *spans, strength: str = "medium") -> list[dict]:
    return [{"kind": kind, "start": s, "end": e, "strength": strength} for s, e in spans]


def flt(kind: str, *spans, strength: str = "medium",
        width: int = 1280, height: int = 720) -> str:
    made = effects.build_filter(
        effects.normalize(bars(kind, *spans, strength=strength), duration=10.0),
        width, height, 30.0,
    )
    return made or ""


WEATHER = ("rain", "snow")
KOREAN = {"rain": "비", "snow": "눈"}


# ══════════════════════════════════════════════════════════════
# 1. 등록표 — 2단계의 목표는 "등록표에 항목을 더하는 것으로 끝난다"였다
# ══════════════════════════════════════════════════════════════
print("\n=== 1. 등록표 ===")

for kind in WEATHER:
    check(f"등록표에 {KOREAN[kind]}가 있다", kind in effects.KINDS,
          f"등록된 종류: {sorted(effects.KINDS)}")

check("비·눈이 화면에 보낼 목록에도 들어간다",
      {k["kind"] for k in effects.kind_list()} >= set(WEATHER),
      f"목록: {[k['kind'] for k in effects.kind_list()]}")

check("비·눈은 화면 위에 얹는 방식(layer)으로 등록되어 있다",
      all(callable(effects.KINDS[k].get("layer")) for k in WEATHER))

check("줌 강조는 사슬 방식(build) 그대로다 — 앞 단계를 건드리지 않았다",
      callable(effects.KINDS["zoom_punch"].get("build")))

check("비가 눈보다, 둘 다 줌 강조보다 나중에 걸린다 (화면을 주무른 뒤에 그린다)",
      effects.KINDS["zoom_punch"]["order"] < effects.KINDS["rain"]["order"]
      < effects.KINDS["snow"]["order"],
      f"줌 {effects.KINDS['zoom_punch']['order']} < 비 {effects.KINDS['rain']['order']}"
      f" < 눈 {effects.KINDS['snow']['order']}")


# ══════════════════════════════════════════════════════════════
# 2. 필터 문자열 — 실제로 넘어졌던 함정들이 못 박혀 있는가
# ══════════════════════════════════════════════════════════════
print("\n=== 2. 넘어졌던 함정이 막혀 있는가 ===")

for kind in WEATHER:
    name, made = KOREAN[kind], flt(kind, (1.0, 3.0))

    check(f"{name}: 무늬가 프레임마다 바뀌지 않는다 (t 플래그를 안 붙인다)",
          "c0f=u" in made and "c0f=t" not in made,
          "t 를 붙이면 내리는 것이 아니라 깜빡인다 (실측: 프레임 일치 0.9%)")

    check(f"{name}: 문턱값을 밝기 자의 양 끝(minval·maxval)으로 적는다",
          "minval" in made and "maxval" in made,
          "숫자로 적으면 화면 눈금(0~255)과 필터 눈금(16~235)이 어긋나 점이 0개가 된다")

    check(f"{name}: 점이 없는 자리는 16이 아니라 **0** 이다 (안개 방지)",
          "maxval,0)" in made,
          f"필터에서 찾은 곳: {'있음' if 'maxval,0)' in made else '없음'}")

    # 2026-08-15 저녁에 합성 방식을 바꿨다. 예전에는 **밝기 면에만** screen 을 걸고
    # 색 면은 원본을 그대로 두었는데, 그러면 밝아진 화소가 원래 색을 그대로 지녀
    # **풀밭 위의 빗줄기가 초록빛**이 되었다. 흰 그림을 알파로 얹어 고쳤다.
    check(f"{name}: 흰 그림을 **알파로** 얹는다 (밝기만 올리면 배경색을 머금는다)",
          "alphamerge" in made and "lutyuv=y=maxval" in made
          and "format=yuva420p" in made and "overlay=0:0" in made)

    check(f"{name}: 흰색을 숫자가 아니라 maxval 로 적는다",
          "lutyuv=y=235" not in made and "lutyuv=y=255" not in made,
          "숫자로 적으면 화면 눈금(0~255)과 필터 눈금(16~235)이 어긋난다")

    # 밝기 면만 섞던 옛 경로다. c1_opacity=0 은 실제로 색을 통째로 지운 적이 있다.
    check(f"{name}: 옛 blend 경로가 남아 있지 않다",
          "blend=" not in made and "c1_opacity=0" not in made,
          "색을 안 건드리는 것이 곧 결함이었다")

    check(f"{name}: 색공간을 왕복시키지 않는다 (켜기만 해도 색이 변하면 안 된다)",
          "gbrp" not in made,
          "조사 때 쓰던 format=gbrp 왕복은 화소값의 31%를 바꾸고 최대 49까지 밀었다")

    check(f"{name}: 그림을 세로로 세 번 이어 붙인다 (되풀이 이음매 없애기)",
          "vstack=inputs=3" in made)

    check(f"{name}: 잘라내는 창을 **위로** 올린다 (아래로 내리면 하늘로 솟는다)",
          f"-mod(t*" in made, f"필터 일부: …{made[made.find('crop='):][:70]}…")

    has_gate = "enable='between(t,1.000,3.000)" in made
    check(f"{name}: 사용자가 정한 구간에만 켜진다", has_gate,
          "1.0~3.0초" if has_gate else f"켜는 구간이 필터에 없습니다: {made[:120]}")

    check(f"{name}: 끝이 없는 생성 필터(color=)를 쓰지 않는다 (렌더가 안 끝난다)",
          "color=" not in made)

check("비: 빗줄기는 세로로만 늘린다 (neighbor)", "flags=neighbor" in flt("rain", (1.0, 3.0)))
check("눈: 송이는 부드럽게 늘려 둥글게 만든다 (bicubic)", "flags=bicubic" in flt("snow", (1.0, 3.0)))
check("눈은 앞뒤 두 겹이다 (한 겹이면 모두 한 몸처럼 흔들린다)",
      flt("snow", (1.0, 3.0)).count("noise=") == 2,
      f"그림 {flt('snow', (1.0, 3.0)).count('noise=')}장")
check("눈만 좌우로 흔들린다", "sin(2*PI*" in flt("snow", (1.0, 3.0))
      and "sin(2*PI*" not in flt("rain", (1.0, 3.0)))


# ══════════════════════════════════════════════════════════════
# 3. 막대를 많이 놓아도 그림은 세기 수만큼만 만든다
#    (막대마다 그림을 만들면 막대 수만큼 느려진다)
# ══════════════════════════════════════════════════════════════
print("\n=== 3. 막대를 많이 놓았을 때 ===")

same = flt("rain", (1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0))
check("비: 세기가 같은 막대 4개는 그림 한 장을 같이 쓴다",
      same.count("noise=") == 1, f"그림 {same.count('noise=')}장")
check("비: 막대 4개의 구간이 모두 필터에 들어간다",
      all(f"between(t,{s}.000,{e}.000)" in same
          for s, e in ((1, 2), (3, 4), (5, 6), (7, 8))),
      f"필터: …{same[same.find('enable='):][:150]}…")

mixed = effects.build_filter(
    effects.normalize(
        bars("rain", (1.0, 2.0), strength="low")
        + bars("rain", (3.0, 4.0), strength="medium")
        + bars("rain", (5.0, 6.0), strength="high"), duration=10.0),
    1280, 720, 30.0) or ""
check("비: 세기가 셋이면 그림도 세 장이다", mixed.count("noise=") == 3,
      f"그림 {mixed.count('noise=')}장")

both = effects.build_filter(
    effects.normalize(bars("rain", (1.0, 3.0)) + bars("snow", (2.0, 4.0)), duration=10.0),
    1280, 720, 30.0) or ""
check("비와 눈을 함께 걸 수 있다", both.count("noise=") == 3, f"그림 {both.count('noise=')}장")

trio = effects.build_filter(
    effects.normalize(
        bars("zoom_punch", (0.5, 1.5)) + bars("rain", (1.0, 3.0)) + bars("snow", (2.0, 4.0)),
        duration=10.0), 1280, 720, 30.0) or ""
check("줌 강조와 비·눈을 함께 걸면 줌이 먼저 온다",
      "zoompan" in trio and trio.index("zoompan") < trio.index("noise="))


# ══════════════════════════════════════════════════════════════
# 4. 세기 3단계 값 — 두 값을 **함께** 움직였는가
# ══════════════════════════════════════════════════════════════
print("\n=== 4. 세기 3단계 값 ===")

for kind in WEATHER:
    spec = effects.KINDS[kind]["strengths"]
    dens = [spec[s]["density"] for s in ("low", "medium", "high")]
    opac = [spec[s]["opacity"] for s in ("low", "medium", "high")]
    check(f"{KOREAN[kind]}: 셀수록 점이 많아진다 (문턱값이 낮아진다)",
          dens[0] > dens[1] > dens[2], f"문턱 {dens}")
    check(f"{KOREAN[kind]}: 셀수록 진해진다",
          opac[0] < opac[1] < opac[2], f"진하기 {opac}")
    check(f"{KOREAN[kind]}: 값을 하나만 움직이지 않았다 (덕킹에서 겪은 가짜 선택지 방지)",
          len(set(dens)) == 3 and len(set(opac)) == 3)


# ══════════════════════════════════════════════════════════════
# 5. 픽셀로 재기 — 여기가 핵심. 서버가 없어도 돈다.
# ══════════════════════════════════════════════════════════════
print("\n=== 5. 실제로 만들어 픽셀로 재기 ===")

SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"


def _tool(name: str) -> bool:
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=30)
        return True
    except Exception:
        return False


try:
    import numpy as np
    from PIL import Image
    have_pixels = True
except Exception as exc:      # noqa: BLE001
    have_pixels = False
    print(f"      numpy/Pillow 가 없어 픽셀 검사를 건너뜁니다: {exc}")

if not have_pixels:
    skip("픽셀 검사", "numpy 또는 Pillow 없음")
elif not _tool("ffmpeg"):
    skip("픽셀 검사", "FFmpeg 없음")
elif not SAMPLE.is_file():
    skip("픽셀 검사", f"샘플 영상 없음: {SAMPLE}")
else:
    work = Path(tempfile.mkdtemp(prefix="weather_"))

    def render(vf: str | None, name: str, pre: str = "", seconds: float = 6.0) -> Path | None:
        """무손실(ffv1)로 굽는다.

        일부러 무손실을 쓴다. H.264 는 뒤 프레임을 미리 보고 압축 방식을 정하므로,
        **뒤쪽에만 비가 있어도 앞쪽 프레임의 압축 결과가 달라진다.** 실제로 그것을
        효과가 샌 것으로 오해할 뻔했다 (구간 밖에서 16,899개가 달랐다). 무손실로
        구우면 필터가 낸 값이 그대로 남아 압축 탓과 필터 탓이 섞이지 않는다.
        """
        dst = work / f"{name}.mkv"
        dst.unlink(missing_ok=True)
        chain = ",".join(p for p in (pre, vf or "") if p)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-i", str(SAMPLE), "-t", f"{seconds}"]
        if chain:
            cmd += ["-vf", chain]
        cmd += ["-c:v", "ffv1", "-an", str(dst)]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=600)
        if out.returncode != 0 or not dst.is_file():
            print(f"      렌더 실패({name}): {(out.stderr or '').strip()[:300]}")
            return None
        return dst

    def gray(video: Path, at: float):
        dst = work / "_f.png"
        dst.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(dst)],
                       capture_output=True, timeout=120)
        return np.array(Image.open(dst).convert("L")).astype(np.int16)

    try:
        plain = render(None, "plain")
        base15 = gray(plain, 1.5) if plain else None
        base30 = gray(plain, 3.0) if plain else None

        for kind in WEATHER:
            name = KOREAN[kind]
            # 2.0~4.0초에만 건다
            made = render(flt(kind, (2.0, 4.0)), f"{kind}_gate")
            if made is None or base15 is None:
                check(f"{name}: 실물 측정", False, "렌더 실패")
                continue

            # ── T5. 구간 밖은 **한 값도** 달라선 안 된다
            for at in (1.0, 5.0):
                diff = int((np.abs(gray(made, at) - gray(plain, at)) > 0).sum())
                check(f"{name}: 구간 밖({at}초)은 원본과 한 값도 다르지 않다",
                      diff == 0, f"다른 값 {diff:,}개")

            # ── T6. 구간 안은 확실히 달라져야 한다 + 안개가 없어야 한다
            lift = gray(made, 3.0) - base30
            bright = int((lift > 8).sum())
            median = float(np.median(lift))
            check(f"{name}: 구간 안(3.0초)은 확실히 달라진다",
                  bright > lift.size * 0.01,
                  f"밝아진 픽셀 {bright:,} ({100 * bright / lift.size:.2f}%)")
            check(f"{name}: 안개가 끼지 않는다 (아무것도 없는 자리는 그대로)",
                  abs(median) <= 1.0,
                  f"화면 전체 밝기 변화의 중앙값 {median:+.1f} (0이어야 정상)")

            # ── 색이 살아 있는가.
            #    이 점검이 없어서 **화면이 통째로 흑백이 되는 결함을 놓쳤다.**
            #    위의 검사들은 전부 흑백으로 재기 때문에 색이 사라져도 다 통과한다.
            def colour(video, at):
                dst = work / "_c.png"
                dst.unlink(missing_ok=True)
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                                "-nostdin", "-ss", f"{at}", "-i", str(video),
                                "-frames:v", "1", str(dst)], capture_output=True, timeout=120)
                rgb = np.array(Image.open(dst).convert("RGB")).astype(np.int16)
                return float(np.abs(rgb[:, :, 0] - rgb[:, :, 2]).mean())

            was, now = colour(plain, 3.0), colour(made, 3.0)
            check(f"{name}: 색이 살아 있다 (화면이 흑백이 되지 않는다)",
                  now > was * 0.75,
                  f"색의 진하기 {was:.1f} → {now:.1f} (샘플은 컬러바 영상이다)")

            # ── 내리는가.
            #    **효과가 밝힌 자리만** 떼어 내서 본다. 합성된 영상을 통째로 보면
            #    원본 화면까지 딸려 들어와 어떻게 밀어도 93%가 맞아 버린다
            #    (실제로 그렇게 재다가 멀쩡한 것을 실패로 판정했다).
            always = render(flt(kind, (0.0, 6.0)), f"{kind}_move")
            if always is not None:
                def only(at: float):
                    """효과가 없는 같은 시각과 견줘 '밝아진 자리'만 남긴다."""
                    return ((gray(always, at) - gray(plain, at)) > 8)[150:-150]

                a, b = only(2.0), only(2.0 + 1 / 30)
                best, at_shift = -1.0, 0
                for shift in range(-45, 46):
                    rolled = np.roll(a, shift, axis=0)
                    union = int((rolled | b).sum())
                    score = float((rolled & b).sum()) / union if union else 0.0
                    if score > best:
                        best, at_shift = score, shift
                check(f"{name}: 아래로 떨어진다 (하늘로 솟지 않는다)",
                      at_shift > 0, f"한 프레임에 {at_shift:+d}픽셀 (양수여야 아래)")

                # 0.5초 뒤에는 무늬가 충분히 흘러가 거의 겹치지 않아야 한다.
                later = only(2.5)
                union = int((a | later).sum())
                drift = float((a & later).sum()) / union if union else 1.0
                check(f"{name}: 멈춰 있지 않고 실제로 움직인다",
                      drift < 0.5,
                      f"0.5초 뒤와의 겹침 {drift:.3f} (멈춰 있으면 1.0에 가깝다)")

            # ── 세기 3단계가 화면에서 실제로 구별되는가
            counts = []
            for level in ("low", "medium", "high"):
                one = render(flt(kind, (2.0, 4.0), strength=level), f"{kind}_{level}")
                counts.append(int(((gray(one, 3.0) - base30) > 8).sum()) if one else -1)
            check(f"{name}: 세기가 셀수록 화면이 더 많이 바뀐다",
                  -1 not in counts and counts[0] < counts[1] < counts[2],
                  f"약하게 {counts[0]:,} · 보통 {counts[1]:,} · 많이 {counts[2]:,}")
            if -1 not in counts and counts[0] > 0:
                gap1, gap2 = counts[1] / counts[0], counts[2] / counts[1]
                check(f"{name}: 단계 사이가 1.3배 넘게 벌어진다 (가짜 선택지가 아니다)",
                      gap1 >= 1.3 and gap2 >= 1.3,
                      f"약→보통 {gap1:.2f}배 · 보통→많이 {gap2:.2f}배")

            # ── 세로 영상(9:16)에서도 되는가 — 조사는 가로에서만 했다
            tall = "crop=ih*9/16:ih,scale=406:720"
            tall_plain = render(None, f"{kind}_tallplain", pre=tall)
            tall_fx = render(flt(kind, (2.0, 4.0), width=406, height=720),
                             f"{kind}_tallfx", pre=tall)
            if tall_plain is not None and tall_fx is not None:
                d = gray(tall_fx, 3.0) - gray(tall_plain, 3.0)
                out_diff = int((np.abs(gray(tall_fx, 1.0) - gray(tall_plain, 1.0)) > 0).sum())
                check(f"{name}: 세로 영상(9:16)에서도 걸린다",
                      int((d > 8).sum()) > d.size * 0.01,
                      f"밝아진 픽셀 {int((d > 8).sum()):,} ({100 * (d > 8).mean():.2f}%)")
                check(f"{name}: 세로 영상에서도 구간 밖은 그대로다",
                      out_diff == 0, f"다른 값 {out_diff:,}개")

        # ── 효과가 없으면 필터를 만들지 않으므로 원본과 완전히 같아야 한다
        check("효과를 하나도 안 걸면 필터가 없다",
              effects.build_filter([], 1280, 720, 30.0) is None)

    finally:
        for leftover in work.glob("*"):
            leftover.unlink(missing_ok=True)
        work.rmdir()


# ══════════════════════════════════════════════════════════════
# 6. 서버로 실물 렌더 — 자막이 살아 있는가 (T8), 길이가 그대로인가
# ══════════════════════════════════════════════════════════════
print("\n=== 6. 실제 내보내기 (서버 필요) ===")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 300):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


def run_job(job_id: str, limit: float = 900.0) -> dict:
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
        capture_output=True, text=True, timeout=300)
    return json.loads(out.stdout)["streams"][0]


try:
    api("/api/health", timeout=5)
    server_up = True
except Exception as exc:      # noqa: BLE001
    server_up = False
    skip("실물 내보내기", f"서버에 연결하지 못했습니다 ({BASE}): {exc}")

if server_up and not (have_pixels and SAMPLE.is_file()):
    server_up = False
    skip("실물 내보내기", "샘플 영상 또는 numpy/Pillow 없음")

if server_up:
    kinds = {k["kind"] for k in api("/api/system/effect-kinds").get("kinds", [])}
    check("서버가 비·눈을 화면에 알려 준다 (화면 단추가 저절로 생긴다)",
          kinds >= set(WEATHER), f"서버가 알려 준 종류: {sorted(kinds)}")

    pid = ""
    try:
        proj = api("/api/projects", "POST",
                   {"name": "비눈점검", "video_path": str(SAMPLE), "mode": "video"})
        pid = proj["id"]
        proj["output"] = {"aspect": "source", "fit": "crop", "focus_x": 50, "focus_y": 50,
                          "pad_blur": True, "zoom": 1.0}

        def make(segments, fx, tag):
            proj["segments"] = segments
            proj["effects"] = fx
            api(f"/api/projects/{pid}", "PUT", proj)
            job = api(f"/api/projects/{pid}/render", "POST",
                      {"kind": "preview", "preview_seconds": 6})
            return Path(run_job(job["job_id"])["path"])

        blank = [{"id": "s1", "start": 2.5, "end": 3.5, "text": ""}]
        worded = [{"id": "s1", "start": 2.5, "end": 3.5, "text": "자막이 살아 있는가"}]
        rainfx = [{"kind": "rain", "start": 2.0, "end": 4.0, "strength": "high"}]

        no_fx = make(blank, [], "plain")
        with_fx = make(blank, rainfx, "rain")

        saved = api(f"/api/projects/{pid}")
        check("비 막대가 저장되고 이름표가 붙어서 돌아온다",
              len(saved.get("effects") or []) == 1
              and saved["effects"][0].get("kind") == "rain"
              and saved["effects"][0].get("id"),
              f"실제 {saved.get('effects')!r}")

        a, b = probe(no_fx), probe(with_fx)
        check("비를 걸어도 영상 길이가 그대로다",
              abs(float(a["duration"]) - float(b["duration"])) < 0.1,
              f"{a['duration']}초 / {b['duration']}초")
        check("비를 걸어도 프레임 수가 그대로다",
              a["nb_read_frames"] == b["nb_read_frames"],
              f"{a['nb_read_frames']}장 / {b['nb_read_frames']}장")
        check("비를 걸어도 프레임률이 그대로다",
              a["r_frame_rate"] == b["r_frame_rate"], f"{a['r_frame_rate']} / {b['r_frame_rate']}")
        check("비를 걸어도 화면 크기가 그대로다",
              (a["width"], a["height"]) == (b["width"], b["height"]),
              f"{a['width']}×{a['height']} / {b['width']}×{b['height']}")

        # T8 — 자막이 살아 있는가.
        # "밝은 픽셀이 많다"로 세면 안 된다. 비 자체가 밝기 때문이다. 그래서
        # **같은 비를 걸고 글자만 비운 영상**을 한 번 더 만들어 차이를 본다.
        # 두 영상의 다른 점은 오직 자막이므로, 늘어난 밝은 픽셀이 곧 글자다.
        fx_worded = make(worded, rainfx, "rain_text")
        work2 = Path(tempfile.mkdtemp(prefix="weather_sub_"))
        try:
            def grab(video: Path, at: float, tag: str):
                dst = work2 / f"{tag}.png"
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                                "-nostdin", "-ss", f"{at}", "-i", str(video),
                                "-frames:v", "1", str(dst)], capture_output=True, timeout=120)
                return np.array(Image.open(dst).convert("L")).astype(np.int16)

            lower_blank = grab(with_fx, 3.0, "sb")[int(a["height"]) * 2 // 3:]
            lower_text = grab(fx_worded, 3.0, "st")[int(a["height"]) * 2 // 3:]
            grew = int((lower_text > 200).sum()) - int((lower_blank > 200).sum())
            check("비를 켜도 자막이 살아 있다 (효과가 자막을 덮지 않는다)",
                  grew > 300,
                  f"글자로 늘어난 밝은 픽셀 {grew:,}개 "
                  f"(글자 있음 {int((lower_text > 200).sum()):,} − "
                  f"글자 없음 {int((lower_blank > 200).sum()):,})")
        finally:
            for leftover in work2.glob("*"):
                leftover.unlink(missing_ok=True)
            work2.rmdir()

    except Exception as exc:      # noqa: BLE001
        check("서버로 비를 실제로 내보낸다", False, f"{type(exc).__name__}: {exc}")
    finally:
        if pid:
            try:
                api(f"/api/projects/{pid}", "DELETE")
            except Exception:      # noqa: BLE001
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
