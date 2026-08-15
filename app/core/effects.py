"""화면 효과 띠 — 사용자가 **구간을 정해서** 거는 효과들의 단일 출처.

이 파일의 존재 이유는 하나다. **효과를 새로 하나 붙이는 일이 `KINDS` 에 항목 하나를
더하는 것으로 끝나게** 하는 것이다. 앞으로 비·눈·비눗방울·작은 폭죽·주변 어둡게·
부분 흐림 같은 것을 계속 붙일 예정인데, 그때마다 저장 구조와 화면과 렌더링을 따로
손대면 그때마다 미리보기와 결과물이 어긋난다.

관통 원칙 — **어떤 효과도 "몇 초에 자동으로 들어간다"고 못 박지 않는다.**
효과는 전부 사용자가 타임라인에 막대를 놓아야만 생기고, 기본값은 빈 목록이다.

막대 하나의 생김새:

    {"id": "fx-1", "kind": "zoom_punch", "start": 12.0, "end": 14.5,
     "strength": "medium", "params": {}}

막대는 **여러 개** 놓을 수 있고 **겹쳐도** 된다. 이것이 "요소요소 작은 폭죽이 터지는"
것을 만드는 방법이다 — 큰 효과 하나를 영상 전체에 거는 것이 아니라 막대 여럿을
원하는 시각에 놓는다.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from app.core import fxart

STRENGTHS = ("low", "medium", "high")
STRENGTH_LABELS = {"low": "약하게", "medium": "보통", "high": "많이"}


def _fps_text(fps: float) -> str:
    """FFmpeg 에 넣을 프레임률 문자열. 30.0 은 '30', 29.97 은 '29.97' 로 쓴다."""
    return f"{float(fps):g}"


def _by_setting(
    bars: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    """막대를 **세기와 값이 같은 것끼리** 묶는다.

    묶는 이유: 설정이 같으면 필터도 같으므로 **한 번만 만들어 여러 구간에 켠다.**
    막대 하나마다 따로 만들면 막대를 열 개 놓았을 때 화면을 열 번 다시 그려
    그만큼 느려진다.

    돌려주는 것: (세기, 값, 그 설정을 쓰는 막대들) 의 목록.
    """
    groups: dict[tuple, tuple[str, dict[str, Any], list[dict[str, Any]]]] = {}
    for bar in bars:
        params = dict(bar.get("params") or {})
        key = (bar["strength"], tuple(sorted(params.items())))
        if key not in groups:
            groups[key] = (bar["strength"], params, [])
        groups[key][2].append(bar)

    rank = {name: index for index, name in enumerate(STRENGTHS)}
    return sorted(groups.values(), key=lambda g: (rank.get(g[0], 9), sorted(g[1].items())))


def _enable(bars: list[dict[str, Any]]) -> str:
    """이 그림을 켜 둘 구간. 여러 구간이면 더한다 — 0이 아니면 켜진 것이다."""
    return "+".join(f"between(t,{b['start']:.3f},{b['end']:.3f})" for b in bars)


def _build_zoom_punch(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> str | None:
    """줌 강조 — 구간 안에서 화면이 부드럽게 커졌다가 제자리로 돌아온다.

    FFmpeg 에서 시간에 따라 배율을 바꾸는 내장 수단은 `zoompan` 이 사실상 유일하다
    (`crop` 과 `scale` 은 가로·세로에 시간식을 못 쓴다).

    실측으로 확인한 함정 둘을 반드시 막는다 (2026-08-14, sample_10s.mp4 로 측정):

      ① `fps` 를 안 주면 zoompan 이 기본값 25 를 쓴다. 30fps 영상에 걸면 프레임 수는
         300 그대로인데 **10초짜리가 12초로 늘어난다** — 소리와 어긋난다.
      ② `d`(한 프레임에 머무는 수)를 1 로 못 박지 않으면 같은 그림이 되풀이된다.
         `d=1` 로 두었을 때 1~3초 60프레임 중 59개가 서로 달랐다(대조군 30개).

    막대가 여럿이어도 **zoompan 은 한 번만** 건다. 여러 번 걸면 화면을 그 횟수만큼
    다시 그려 그만큼 느려진다. 대신 배율식 안에 구간을 차곡차곡 넣는다.
    """
    pieces: list[tuple[int, int, float]] = []
    for bar in bars:
        first = int(round(bar["start"] * fps))
        last = int(round(bar["end"] * fps))
        if last <= first:
            continue
        peak = KINDS["zoom_punch"]["strengths"][bar["strength"]]["scale"]
        pieces.append((first, last, round(peak - 1.0, 4)))

    if not pieces:
        return None

    # 구간 밖은 1배(손대지 않음). 구간 안은 0 → 최대 → 0 으로 부드럽게 오간다.
    # sin 을 쓰면 시작과 끝에서 배율이 정확히 1이라 경계에서 툭 튀지 않는다.
    expr = "1"
    for first, last, amp in reversed(pieces):
        wave = f"{amp}*sin(PI*(on-{first})/{last - first})"
        expr = f"if(between(on,{first},{last}),1+{wave},{expr})"

    return (
        f"zoompan=z='{expr}':d=1"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={int(width)}x{int(height)}:fps={_fps_text(fps)}"
    )


# ── 화면 위에 얹는 효과(비·눈)를 만드는 공통 부품 ──────────────
#
# 비도 눈도 만드는 방법은 같다. **성긴 점을 찍은 작은 그림**을 만들고, 그것을
# 세로로 세 번 이어 붙인 뒤 크게 늘리고, 시간에 따라 잘라내는 창을 위로 올려
# 아래로 떨어지게 한다. 다른 것은 늘리는 방법뿐이다 —
# 비는 세로로만 늘려 **줄기**가 되고, 눈은 가로·세로를 같은 배수로 늘려 **덩어리**가 된다.
#
# 이 방식을 고른 이유가 중요하다. 점을 흐려서 줄기를 만들면 밝기가 퍼져 사라지고,
# 사라진 밝기를 곱해서 되살리면 이번에는 흐릿한 꼬리까지 같이 올라가 온 화면에
# 안개가 낀다 (memory/ffmpeg-effect-layer-traps.md ①②). 늘리기는 밝기를 퍼뜨리지
# 않으므로 두 함정을 **아예 만나지 않는다.**


def _even_up(value: float) -> int:
    """올림한 뒤 짝수로 맞춘다. 영상 필터는 홀수 크기를 싫어한다."""
    number = int(math.ceil(value))
    return number + (number & 1)


def _dots(width: int, height: int, density: float, seed: int) -> str:
    """성긴 흰 점이 찍힌 그림 한 장. 검정은 반드시 **0** 이어야 한다.

    `noise` 는 `t` 플래그를 빼면 **프레임이 바뀌어도 같은 무늬**를 준다(실측 100% 동일).
    그래서 이 그림을 그대로 흘려보내면 '내리는' 것이 되고, `t` 를 붙이면 '깜빡이는'
    것이 된다(실측 0.9% 동일).

    두 가지를 못 박는다:

      · 문턱값을 `minval`·`maxval`(밝기 자의 양 끝)로 적는다. 숫자로 적으면 안 된다 —
        화면에서 재는 값은 0~255 인데 필터 안의 밝기는 16~235 라 **자가 다르다.**
        실제로 184 라는 문턱을 그냥 썼다가 필터 안의 최대치(177)보다 높아
        **점이 하나도 안 남은 적**이 있다. 오류는 나지 않았다.
      · 점이 아닌 자리는 `minval`(16)이 아니라 **0** 으로 둔다. screen 합성은 16을
        검정으로 보지 않아서, 16으로 두면 아무것도 없는 자리까지 밝아진다
        (실측: 온 화면 중앙값이 +17 들렸다).
    """
    return (
        f"scale={width}:{height},lutyuv=y='(minval+maxval)/2':u=128:v=128,"
        f"noise=c0s=100:c0f=u:all_seed={seed},"
        f"lutyuv=y='if(gt(val,minval+{density}*(maxval-minval)),maxval,0)'"
    )


def _tile3(tag: str) -> str:
    """같은 그림을 세로로 세 번 이어 붙인다 — 되풀이 이음매를 없애기 위해서다.

    떨어지는 것처럼 보이게 하려면 잘라내는 창을 계속 움직여야 하는데, 창이 그림
    끝에 닿으면 처음으로 돌아가야 한다. 그때 **그림 전체가 순간에 바뀌면** 비가
    한 번씩 통째로 깜빡인다. 위아래가 똑같은 그림이면 돌아가도 티가 안 난다.
    세 번인 이유는 흐림이 그림의 위아래 **가장자리**를 망가뜨리기 때문이다 —
    가운데 한 겹만 쓰면 그 자국이 화면에 들어오지 않는다.
    """
    return (f"split=3[{tag}a][{tag}b][{tag}c];"
            f"[{tag}a][{tag}b][{tag}c]vstack=inputs=3")


def _fall(height: int, speed: float) -> str:
    """잘라내는 창의 세로 자리. **위로** 올려야 보이는 그림이 아래로 떨어진다.

    반대로 창을 아래로 내리면 그림은 위로 올라간다. 처음에 이것을 거꾸로 만들어
    비가 하늘로 솟았다 (실측 -30픽셀/프레임).
    """
    return f"'{height}-mod(t*{speed}\\,{height})'"


def _thickness(base: float, params: dict[str, Any]) -> float:
    """덧씌우는 그림을 얼마나 진하게 얹을 것인가 — 사용자가 정한 진하기를 곱한다.

    빗줄기·눈송이는 이 값이 곧 **알파(투명도)** 가 된다. 1을 넘으면 가장 진한 자리는
    더 진해질 수 없지만(자의 끝), 흐림 때문에 생긴 중간 밝기의 자리들은 계속
    진해지므로 200%까지도 실제로 달라진다.
    """
    return round(base * max(0.0, float(params["opacity"]) / 100.0), 4)


def _white_alpha(chain: str, tag: str) -> str:
    """회색 그림을 **흰 그림 + 알파**로 바꾼다. 비·눈이 쓴다.

    예전에는 이 회색 그림을 밝기 면에 `screen` 으로 얹었다. 색 면을 안 건드리니
    구간 밖이 완벽히 보존되어 좋았지만, **밝아진 화소가 원래 색을 그대로 지녔다.**
    그래서 풀밭 위의 빗줄기가 **초록빛**으로 보였다 — 흰 비가 아니라 '밝아진 풀'이
    된 것이다. 진하기를 200%까지 올리면 눈에 띄게 드러났다.

    알파로 얹으면 색도 함께 흰색 쪽으로 간다:

        U_새 = U×(1-a) + 128×a = 128 + (U-128)×(1-a)

    `alphamerge` 는 둘째 입력의 밝기를 첫째 입력의 알파로 삼는다. 그래서 지금 쓰던
    회색 그림을 **한 글자도 안 고치고** 그대로 알파로 쓸 수 있다.

    흰색은 `maxval` 로 적는다. 235 처럼 숫자로 적으면 안 된다 — 필터 안의 밝기 자가
    화면에서 재는 자와 다르기 때문이다 (memory/ffmpeg-effect-layer-traps.md ③-c).
    """
    return (f"split=2[{tag}w][{tag}m];"
            f"[{tag}w]lutyuv=y=maxval:u=128:v=128,format=yuva420p[{tag}white];"
            f"[{tag}m]{chain}[{tag}mask];"
            f"[{tag}white][{tag}mask]alphamerge")


def _layer_rain(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> list[tuple[str, str]]:
    """비 — 세로로만 늘려 가느다란 줄기를 만들고 빠르게 떨어뜨린다.

    씨앗 그림의 **줄 수**가 빗줄기 길이와 개수를 함께 정한다. 화면 높이의 1/15 로
    잡으면 점 하나가 15배로 늘어나 세로 16픽셀 × 가로 1.0~1.5픽셀짜리 줄기가 된다
    (실측). 줄 수가 적어 점 개수도 알맞게 성기다.
    """
    made: list[tuple[str, str]] = []
    for index, (strength, params, group) in enumerate(_by_setting(bars)):
        spec = KINDS["rain"]["strengths"][strength]
        tag = f"rn{index}"
        rows = _even_up(height / 15)
        speed = round(900 * params["speed"] / 100.0, 1)
        made.append((
            _white_alpha(
                _dots(width, rows, spec["density"], 1234 + index)
                + "," + _tile3(tag)
                + f",scale={width}:{3 * height}:flags=neighbor"
                + ",gblur=sigma=0.8:sigmaV=3.0"      # 모서리만 살짝 눅인다
                + f",crop={width}:{height}:0:{_fall(height, speed)}"
                + f",lutyuv=y='val*{_thickness(spec['opacity'], params)}'",
                tag),
            _enable(group),
        ))
    return made


def _layer_snow(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> list[tuple[str, str]]:
    """눈 — 가로·세로를 **같은 배수**로 늘려 둥근 송이를 만들고 천천히 흔들며 내린다.

    한 겹만 쓰면 모든 송이가 같은 크기로 한 몸처럼 흔들려 어색하다. 그래서 앞뒤
    두 겹을 쓴다 — 앞은 크고 빠르고 밝게, 뒤는 작고 느리고 흐리게.

    옆으로 흔들리려면 그림이 화면보다 **넓어야** 한다. 그만큼 넓게 만들어 두고
    가운데를 잘라 낸다.
    """
    made: list[tuple[str, str]] = []
    for index, (strength, params, group) in enumerate(_by_setting(bars)):
        spec = KINDS["snow"]["strengths"][strength]
        gate = _enable(group)
        pace = params["speed"] / 100.0
        # (늘리는 배수, 떨어지는 속도, 흔들리는 폭, 흔들리는 빠르기, 씨앗, 밝기 배수)
        for depth, (grow, speed, sway, hertz, seed, dim) in enumerate((
            (5, 70, 26, 0.17, 4242, 0.55),      # 뒤 — 작고 느리고 흐리게
            (8, 115, 40, 0.23, 777, 1.00),      # 앞 — 크고 빠르고 밝게
        )):
            tag = f"sn{index}{depth}"
            rows = _even_up(height / grow)
            factor = height / rows                       # 실제 늘어나는 배수
            cols = _even_up((width + 2 * sway) / factor)
            canvas = _even_up(cols * factor)
            made.append((
                _white_alpha(
                    _dots(cols, rows, spec["density"] - 0.004 * (1 - depth), seed + index)
                    + "," + _tile3(tag)
                    + f",scale={canvas}:{3 * height}:flags=bicubic"
                    + f",crop={width}:{height}"
                      f":'{(canvas - width) // 2}+{sway}*sin(2*PI*{round(hertz * pace, 4)}*t)'"
                      f":{_fall(height, round(speed * pace, 1))}"
                    + f",lutyuv=y='val*{_thickness(spec['opacity'] * dim, params)}'",
                    tag),
                gate,
            ))
    return made


# ── 색을 바꾸는 효과 · 자리를 정하는 효과 ────────────────────


def _neutral(name: str, key: str) -> float:
    """그 값에 대해 **아무 일도 안 하는 값**.

    진하기(투명 정도)를 계산하려면 "0 이 중립"인지 "1 이 중립"인지를 알아야 한다.
    필터마다 다르다 — `eq` 의 채도·대비는 1 이 원래대로이고, `colorbalance` 의
    붉은기는 0 이 원래대로다. `colorchannelmixer` 는 **단위행렬**(자기 색은 1,
    남의 색은 0)이 원래대로다.
    """
    if name == "eq":
        return 0.0 if key == "brightness" else 1.0
    if name == "hue":
        return 1.0                                    # s=1 이 원래 색
    if name == "colorchannelmixer":
        return 1.0 if key in ("rr", "gg", "bb", "aa") else 0.0
    return 0.0                                        # colorbalance · vignette 의 a


# FFmpeg 이 받아 주는 범위. 사용자가 진하기를 끝까지 밀어도 필터가 거부하지 않도록
# 여기서 자른다 (외부 도구를 부르는 자리는 시스템 경계다).
_LOOK_RANGE = {
    "eq": (0.0, 3.0),
    "hue": (0.0, 10.0),
    "vignette": (0.0, 1.55),                          # a 의 최대는 PI/2 ≒ 1.5708
    "colorbalance": (-1.0, 1.0),
    "colorchannelmixer": (-2.0, 2.0),
}


def look_filters(kind: str, strength: str, opacity: float = 100.0) -> list[str]:
    """색감 계열의 **숫자 설명서**를 실제 FFmpeg 필터 문자열로 바꾼다.

    등록표에는 `("eq", {"saturation": 1.04})` 처럼 필터 이름과 값만 적어 둔다.
    문자열을 그대로 적어 두면 사람이 읽기는 좋지만 **진하기를 곱할 수가 없다** —
    사용자가 슬라이더로 정한 만큼 값을 키우거나 줄이려면 숫자여야 한다.

    진하기는 이렇게 계산한다:

        새 값 = 중립값 + (등록표에 적힌 값 - 중립값) × 진하기

    진하기 0% 면 아무 일도 안 하고, 100% 면 등록표 그대로, 200% 면 효과가 두 배가
    된다. **세기 3단계 사이의 비율은 그대로 보존된다** — 모든 단계에 같은 배수를
    곱하기 때문이다 (memory/effects-must-not-obscure-the-picture.md 의 "비율을
    유지한 채 사다리 전체를 옮긴다"와 같은 셈).
    """
    factor = max(0.0, float(opacity) / 100.0)
    made: list[str] = []
    for name, values in KINDS[kind]["strengths"][strength]["look"]:
        low, high = _LOOK_RANGE[name]
        parts = []
        for key, value in values.items():
            base = _neutral(name, key)
            now = min(high, max(low, base + (value - base) * factor))
            parts.append(f"{key}={round(now, 4)}")
        made.append(f"{name}=" + ":".join(parts))
    return made


def _build_look(bars: list[dict[str, Any]], width: int, height: int, fps: float) -> str:
    """등록표에 **값을 적어 둔** 색감·비네트 효과들을 만든다.

    "세기마다 정해진 모양"이 있는 것들이다. 계산으로 풀어 쓰지 않고 세기별 값을
    등록표에 직접 적는다 — 무엇이 걸리는지 한눈에 보이고, 값을 손보려면 그 줄만
    고치면 된다. 진하기 슬라이더는 `look_filters()` 가 반영한다.
    """
    kind = bars[0]["kind"]
    parts: list[str] = []
    for strength, params, group in _by_setting(bars):
        gate = _enable(group)
        for one in look_filters(kind, strength, params["opacity"]):
            parts.append(f"{one}:enable='{gate}'")
    return ",".join(parts)


def _build_color_adjust(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> str:
    """밝기·대비·채도 — 사용자가 슬라이더로 직접 정한다.

    세기는 슬라이더를 **얼마나 세게 반영할지**를 정한다. 슬라이더가 이미 있는데
    세기까지 있는 것이 겹쳐 보이지만, 세기 3단계는 모든 효과가 갖는 공통 손잡이라
    빼면 화면이 효과마다 달라진다.
    """
    parts: list[str] = []
    for strength, params, group in _by_setting(bars):
        amount = KINDS["color_adjust"]["strengths"][strength]["amount"]
        bright = round(params["brightness"] / 100.0 * amount, 4)
        contrast = round(max(0.0, 1.0 + (params["contrast"] - 100) / 100.0 * amount), 4)
        colour = round(max(0.0, 1.0 + (params["saturation"] - 100) / 100.0 * amount), 4)
        parts.append(
            f"eq=brightness={bright}:contrast={contrast}:saturation={colour}"
            f":enable='{_enable(group)}'"
        )
    return ",".join(parts)


def _even_down(value: float) -> int:
    """내림한 뒤 짝수로 맞춘다. 음수는 0으로 본다.

    **최소값을 2로 두면 안 된다.** 자리(x·y)는 0이 정상이기 때문이다. 처음에 크기와
    자리에 같은 함수를 쓰면서 최소 2를 강제했더니, 네모를 화면 맨 왼쪽에 붙여도
    x=2 가 되어 2픽셀씩 떠 있었다. 크기 쪽에서만 따로 2 아래로 안 내려가게 막는다.
    """
    number = max(0, int(value))
    return number - (number & 1)


def _rect(params: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """가운데 위치(%)와 크기(%)를 화면 안의 실제 네모로 바꾼다.

    사용자는 "가로 40% 자리에 너비 30%"처럼 **화면 비율로** 정한다. 픽셀로 정하면
    영상 크기가 바뀔 때마다 자리가 어긋난다. 네모가 화면 밖으로 나가지 않게 민다.
    """
    box_w = max(2, min(_even_down(width * params["w"] / 100.0), _even_down(width)))
    box_h = max(2, min(_even_down(height * params["h"] / 100.0), _even_down(height)))
    left = _even_down(width * params["x"] / 100.0 - box_w / 2)
    top = _even_down(height * params["y"] / 100.0 - box_h / 2)
    return (max(0, min(width - box_w, left)), max(0, min(height - box_h, top)),
            box_w, box_h)


def _build_blur_area(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> str:
    """부분 흐림 — 정한 네모만 오려서 흐린 뒤 제자리에 도로 얹는다.

    화면 전체를 흐린 뒤 마스크로 되살리는 것보다 훨씬 싸다. 흐리는 넓이가
    네모 하나로 줄기 때문이다.
    """
    parts: list[str] = []
    for index, (strength, params, group) in enumerate(_by_setting(bars)):
        left, top, box_w, box_h = _rect(params, width, height)
        # 흐림 반지름이 네모보다 크면 FFmpeg 이 거부한다. 네모에 맞춰 줄인다.
        radius = KINDS["blur_area"]["strengths"][strength]["radius"]
        radius = max(1, min(radius, min(box_w, box_h) // 4))
        tag = f"bz{index}"
        parts.append(
            f"split=2[{tag}bg][{tag}zn];"
            f"[{tag}zn]crop={box_w}:{box_h}:{left}:{top},boxblur={radius}:2[{tag}fx];"
            f"[{tag}bg][{tag}fx]overlay={left}:{top}:enable='{_enable(group)}'"
        )
    return ",".join(parts)


def _build_box_mark(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> str:
    """네모 테두리 — "여기 보세요" 표시. FFmpeg 내장 `drawbox` 라 거의 공짜다."""
    parts: list[str] = []
    for strength, params, group in _by_setting(bars):
        left, top, box_w, box_h = _rect(params, width, height)
        thick = max(2, round(height * KINDS["box_mark"]["strengths"][strength]["thick"]))
        parts.append(
            f"drawbox=x={left}:y={top}:w={box_w}:h={box_h}"
            f":color=yellow@0.95:t={thick}:enable='{_enable(group)}'"
        )
    return ",".join(parts)


def _layer_spotlight(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> list[tuple[str, str]]:
    """주변 어둡게 — **검은 그림을 알파(투명도)로** 얹는다. 가운데는 투명하게 둔다.

    그림은 시간에 따라 변하지 않으므로 **작게 그려서 늘린다** — `geq` 는 픽셀마다
    식을 계산해 느린데, 작은 자에서만 쓰면 부담이 없고 늘리면 저절로 부드러워진다.

    ⚠ 처음에는 회색 그림을 **밝기 면에만 곱했다.** 오류는 없었고 점검 804개가 전부
    통과했지만 **화면이 보라색으로 물들었다.** 밝기(Y)만 줄이고 색차(U·V)를 그대로
    두면 '밝기에 견준 색'이 그만큼 커지기 때문이다 — 빨강과 파랑의 차이는
    `1.402(V-128) + 1.772(U-128)` 이라 **Y 와 아무 상관이 없다.** 실측(색이 있는 화면):

        밝기만 곱하기 · 기본값     남은 밝기 65% · 색의 진하기 **150%**  ❌
        밝기만 곱하기 · 진하기 200% 남은 밝기 34% · 색의 진하기 **218%**  ❌
        검은 그림을 알파로 얹기     남은 밝기 71% · 색의 진하기 **101%**  ✅

    알파 합성은 색차도 함께 데려간다: `U_새 = U*(1-a) + 128*a = 128 + (U-128)*(1-a)`.
    어두워지는 만큼 색도 함께 옅어져 실제 사진처럼 보인다. 구간 밖이 원본과 한 값도
    다르지 않은 것은 그대로다(실측 0개).

    비·눈은 지금대로 밝기 면만 얹는다 — 흰 그림을 **밝히는** 쪽이라 색이 튀지 않는다.
    """
    made: list[tuple[str, str]] = []
    for strength, params, group in _by_setting(bars):
        # 진하기는 **어두워지는 정도**에 곱한다. dim 자체에 곱하면 진하기를 올릴수록
        # 밝아지는 거꾸로 된 손잡이가 된다.
        dim = KINDS["spotlight"]["strengths"][strength]["dim"]
        dim = round(max(0.0, 1.0 - (1.0 - dim) * max(0.0, params["opacity"] / 100.0)), 4)
        small_w = 160
        small_h = _even_up(small_w * height / width)
        cx = round(small_w * params["x"] / 100.0, 2)
        cy = round(small_h * params["y"] / 100.0, 2)
        radius = round(max(6.0, small_w * params["size"] / 100.0), 2)
        made.append((
            # 밝기는 16(검정), 색은 128(무채색)으로 고정하고 **알파만** 그린다.
            # 알파 = 1 - 남길 비율 이므로 가운데는 0(완전 투명)이다.
            f"scale={small_w}:{small_h},format=yuva420p,"
            f"geq=lum=16:cb=128:cr=128:"
            f"a='255*(1-({dim}+{round(1 - dim, 4)}"
            f"*exp(-1.6*pow(hypot((X-{cx})/{radius}\\,(Y-{cy})/{radius})\\,2))))',"
            f"scale={width}:{height}:flags=bicubic",
            _enable(group),
        ))
    return made


def _slider(label: str, default: float, low: float, high: float,
            step: float = 1, suffix: str = "%") -> dict[str, Any]:
    """화면에 슬라이더 하나를 그리기 위한 설명서."""
    return {"label": label, "min": low, "max": high,
            "step": step, "default": default, "suffix": suffix}


# ── 파이썬이 그린 그림을 쓰는 효과 (물방울·비눗방울·작은 폭죽) ──────
#
# 앞의 13종과 다른 점은 하나뿐이다: **그림 파일이 먼저 있어야 한다.**
# 그래서 이 갈래의 함수만 `folder`(그림을 둘 폴더)를 더 받는다.
# 필터에는 **파일 이름만** 넣는다 — FFmpeg 이 그 폴더에서 실행되기 때문이다
# (memory/ffmpeg-filter-path-escaping.md: 절대 경로를 넣으면 콜론에서 깨진다).


# 그림 파일의 0~255 를 필터 안에서 되살린다. 이것을 안 붙이면 '안 밂'(128)이
# 126 으로 들어와 온 화면이 밀린다 (아래 _art_water_drops 설명 참고).
_MAP_SCALE = "format=yuv420p,lutyuv=y='(val-minval)*255/(maxval-minval)'"


def _art_water_drops(bars: list[dict[str, Any]], width: int, height: int,
                     fps: float, folder: Path) -> list[str]:
    """물방울 맺힘 — 굴절 지도로 화면을 휘게 하고 반짝임을 얹는다.

    `displace` 는 지도의 밝기를 '얼마나 밀 것인가'로 읽는다. 방울 안쪽만 밀고
    바깥은 128(=안 밂) 그대로이므로 **방울이 없는 자리는 원본 그대로** 남는다.

    ⚠ 지도를 그대로 넘기면 **온 화면이 2픽셀씩 밀린다.** 그림 파일의 밝기는
    0~255 인데 필터 안으로 들어오면 16~235 로 눌리기 때문이다. 그래서 128 로
    그린 '안 밂'이 필터 안에서는 126 이 되어 화면 전체가 어긋난다. 실측으로
    방울 10개짜리가 **화면의 71%** 를 건드렸고, 세기를 올려도 71% 그대로였다
    (온 화면이 밀리는 것이 방울보다 훨씬 컸기 때문이다).

        지도를 통째로 128 로 채우고 재기 — 다른 값이 0이어야 정상
          그대로 넘김              663,681개  ❌
          lutyuv 로 자를 되돌림          0개  ✅

    비·눈이 문턱값에서 겪은 것과 **똑같은 함정**이다
    (memory/ffmpeg-effect-layer-traps.md ③-c). 거기서 쓴 해법을 그대로 쓴다:
    필터 안의 자(minval·maxval)로 원래 범위를 되돌린다.
    """
    parts: list[str] = []
    for index, (strength, params, group) in enumerate(_by_setting(bars)):
        spec = KINDS["water_drops"]["strengths"][strength]
        tag = fxart.stamp("water_drops", strength, params, width, height)
        art = fxart.draw_water_drops(folder, tag, width, height,
                                     spec["count"], params["size"] / 100.0)
        gate = _enable(group)
        key = f"wd{index}"
        parts.append(
            # null 로 지금까지의 흐름에 이름을 붙인다. 이름이 없으면 displace 의
            # 첫 입력으로 넘길 수 없다 (사슬 중간에서는 입력 이름을 못 적는다).
            f"null[{key}];"
            f"movie={art['x']},{_MAP_SCALE}[{key}x];"
            f"movie={art['y']},{_MAP_SCALE}[{key}y];"
            f"[{key}][{key}x][{key}y]displace=edge=smear:enable='{gate}'[{key}d];"
            f"movie={art['shine']}[{key}s];"
            f"[{key}d][{key}s]overlay=0:0:enable='{gate}'"
        )
    return parts


def _art_bubbles(bars: list[dict[str, Any]], width: int, height: int,
                 fps: float, folder: Path) -> list[str]:
    """비눗방울 — 고리 그림을 겹치고 **자리를 시간식으로** 올린다.

    비·눈처럼 잘라내는 창을 움직이지 않는다. 그러면 알파(투명)가 죽어 방울
    너머로 화면이 안 비친다. 대신 `overlay` 의 자리를 움직인다.

    그림은 세로로 두 겹이고 자리는 0 ~ -H 를 오간다. 되돌아갈 때 위아래가 같은
    그림이라 방울이 깜빡이지 않는다.

    ⚠ 자리를 **빼야** 방울이 올라간다. 화면의 한 줄 r 에 보이는 것은 그림의 (r - y)
    줄이므로, y 가 커지면 그림이 아래로 흐른다. 처음에 `-H + mod(...)` 로 적어
    **비눗방울이 가라앉았다** — 초당 72픽셀로 내려가는 것을 점검이 잡았다.
    비가 하늘로 솟았던 것과 같은 종류의 실수다 (`_fall` 설명 참고).
    """
    parts: list[str] = []
    for index, (strength, params, group) in enumerate(_by_setting(bars)):
        spec = KINDS["bubbles"]["strengths"][strength]
        tag = fxart.stamp("bubbles", strength, params, width, height)
        sway = max(8, int(min(width, height) * 0.035))
        name = fxart.draw_bubbles(folder, tag, width, height, spec["count"],
                                  params["size"] / 100.0 * spec["swell"], sway)
        pace = params["speed"] / 100.0
        rise = round(spec["rise"] * pace, 1)
        hertz = round(0.11 * pace, 4)
        gate = _enable(group)
        key = f"bb{index}"
        parts.append(
            f"null[{key}];movie={name}[{key}i];"
            f"[{key}][{key}i]overlay="
            f"x='-{sway}+{sway}*sin(2*PI*{hertz}*t)'"
            f":y='-mod(t*{rise}\\,{height})'"
            f":enable='{gate}'"
        )
    return parts


def _art_fireworks(bars: list[dict[str, Any]], width: int, height: int,
                   fps: float, folder: Path) -> list[str]:
    """작은 폭죽 — 장면을 이어 붙인 그림을 **넘겨 가며** 보여 준다.

    막대마다 따로 얹는다. 폭죽은 **막대가 시작할 때 터져야** 하는데, 설정이 같은
    막대끼리 묶어 한 번에 얹으면 시작 시각이 하나뿐이라 나머지는 터지다 만 장면부터
    보이게 된다. 그림 파일은 설정이 같으면 같은 것을 다시 쓴다.

    `loop` 로 만든 흐름은 끝이 없으므로 `shortest=1` 을 반드시 붙인다. 안 붙이면
    렌더가 끝나지 않는다 (memory/ffmpeg-effect-layer-traps.md ④).
    """
    parts: list[str] = []
    slot = 0
    for strength, params, group in _by_setting(bars):
        spec = KINDS["fireworks"]["strengths"][strength]
        cell = max(48, _even_down(min(width, height) * params["size"] / 100.0))
        tag = fxart.stamp("fireworks", strength, {**params, "cell": cell}, width, height)
        name = fxart.draw_fireworks(folder, tag, cell, spec["sparks"], spec["glow"])
        left = _even_down(min(max(0.0, width * params["x"] / 100.0 - cell / 2),
                              max(0.0, width - cell)))
        top = _even_down(min(max(0.0, height * params["y"] / 100.0 - cell / 2),
                             max(0.0, height - cell)))
        for bar in group:
            key = f"fw{slot}"
            slot += 1
            frame = (f"{cell}*floor(mod((t-{bar['start']:.3f})*{_fps_text(fps)}"
                     f"\\,{fxart.BURST_FRAMES}))")
            parts.append(
                f"null[{key}];"
                f"movie={name},loop=loop=-1:size=1,setpts=N/({_fps_text(fps)}*TB),"
                f"crop={cell}:{cell}:0:'{frame}'[{key}i];"
                f"[{key}][{key}i]overlay=x={left}:y={top}"
                f":enable='{_enable([bar])}':shortest=1"
            )
    return parts


_SPEED = _slider("떨어지는 속도", 100, 30, 250, 5)
_PLACE = {"x": _slider("가로 자리", 50, 0, 100),
          "y": _slider("세로 자리", 50, 0, 100)}
_SIZE = {"w": _slider("너비", 35, 5, 100),
         "h": _slider("높이", 35, 5, 100)}

# 진하기(투명 정도) — 화면 전체를 덮는 효과에 붙인다.
#
# 세기 3단계만으로는 사용자가 원하는 만큼을 못 고른다. 14절에서 값을 순하게
# 낮췄기 때문에 더 진하게 쓰고 싶은 사람도 있고, 더 옅게 쓰고 싶은 사람도 있다.
# 기본 100% 는 **낮춘 값 그대로**다 — 아무것도 안 만진 사용자는 화면을 가리지 않는
# 순한 값을 그대로 받는다. 200% 까지 열어 두어 원하는 사람은 예전의 진한 느낌까지
# 갈 수 있게 한다. **사용자가 직접 정한 값에는 상한을 걸지 않는다**
# (memory/effects-must-not-obscure-the-picture.md — 다만 제품이 사용자 값을
# 더 부풀리는 것은 금지다. 그래서 진하기는 세기와 곱해질 뿐 따로 부풀지 않는다).
_OPACITY = _slider("진하기", 100, 20, 200, 5)


# ── 효과 등록표 ────────────────────────────────────────────
#
# 효과를 새로 붙일 때 손댈 곳은 **여기 한 곳**이다.
#   label     : 화면에 보여 줄 한국어 이름
#   hint      : 무엇에 쓰는 것인지 한 줄 설명
#   order     : 필터를 거는 순서. 작을수록 먼저. 화면 모양을 바꾸는 것이 먼저고
#               위에 무언가를 그리는 것이 나중이다
#   params    : 효과마다 다른 값의 기본값. 여기 없는 열쇠는 저장하지 않는다
#   strengths : 세기 3단계. 값은 **실제로 구별되게** 벌려야 한다
#               (memory/options-must-actually-differ.md)
#   build     : 막대 목록을 **사슬 필터** 하나로 바꾸는 함수 (화면 자체를 주무르는 효과)
#   layer     : 막대 목록을 **덧씌울 그림들**로 바꾸는 함수 (화면 위에 무언가 그리는 효과)
#               돌려주는 것은 (필터사슬, 켜는구간) 짝의 목록이다
KINDS: dict[str, dict[str, Any]] = {
    "zoom_punch": {
        "label": "줌 강조",
        "hint": "화면이 확 커졌다가 제자리로 돌아옵니다. 말의 강조점에 씁니다.",
        "order": 10,
        "params": {},
        # 화면이 커지는 정도는 (배율 - 1) 에 비례한다. 0.15 / 0.35 / 0.60 이므로
        # 단계 사이가 2.33배 · 1.71배 벌어진다 (가짜 선택지 기준 1.3배를 넘는다).
        "strengths": {
            "low": {"scale": 1.15},
            "medium": {"scale": 1.35},
            "high": {"scale": 1.60},
        },
        "build": _build_zoom_punch,
    },
    "rain": {
        "label": "비",
        "hint": "가느다란 빗줄기가 내립니다. 차분하거나 쓸쓸한 장면에 씁니다.",
        "order": 20,
        "params": {"speed": _SPEED, "opacity": _OPACITY},
        # density = 점으로 남길 문턱값(밝기 범위의 몇 %). **낮을수록 점이 많다.**
        # opacity = 레이어를 얼마나 진하게 얹을 것인가.
        # 둘을 함께 움직여야 단계가 벌어진다 — 덕킹에서 값 하나만 움직였다가
        # 이름만 다른 가짜 선택지를 만든 적이 있다 (options-must-actually-differ).
        #
        # ⚠ 2026-08-15 에 **낮췄다.** 예전 값(0.715/0.703/0.681 · 0.55/0.80/1.00)은
        # '많이'가 화면의 34.9%를 밝히고 화면의 결을 193%로 늘렸다 — 원본보다 두 배
        # 어수선해져 시선이 내용이 아니라 빗줄기로 갔다.
        # (memory/effects-must-not-obscure-the-picture.md)
        # 한 번에 못 맞췄다: 처음 낮춘 값(0.728/0.716/0.697 · 0.40/0.58/0.78)은 이번엔
        # **'약하게'가 아무 일도 안 하게** 만들었다(평균 밀림 0.0). 가짜 선택지를 피하려던
        # 기준을 스스로 어긴 것이라 다시 올렸다. 위아래 두 기준은 함께 재야 맞는다.
        # ⚠ density 는 **절벽처럼** 동작한다. 0.715 에서는 점이 남고 0.724 에서는
        # 하나도 안 남는다(실측). 그래서 개수는 좁게 움직이고 진하기로 단계를 벌린다.
        #
        # 2026-08-15 저녁에 합성을 **알파**로 바꿨지만 값은 그대로 두었다. 평균 밀림은
        # 6.05 → 3.54 로 줄었어도 **남은 결은 136% → 132% 로 거의 같다** — 화면이
        # 어수선해지는 정도는 그대로라는 뜻이다. 값을 올리면 결이 상한 140%를 넘는다.
        "strengths": {
            "low": {"density": 0.715, "opacity": 0.38},
            "medium": {"density": 0.708, "opacity": 0.52},
            "high": {"density": 0.702, "opacity": 0.70},
        },
        "layer": _layer_rain,
    },
    "snow": {
        "label": "눈",
        "hint": "둥근 눈송이가 좌우로 흔들리며 천천히 내립니다.",
        "order": 21,
        "params": {"speed": _SPEED, "opacity": _OPACITY},
        # 비와 같은 이유로 2026-08-15 에 낮췄다 (옛 값 0.723/0.717/0.705 · 0.55/0.80/1.00
        # 은 '많이'가 화면의 24.4%를 밝혔다).
        #
        # ⚠ 같은 날 저녁에 합성을 **알파**로 바꾸면서 진하기를 올렸다
        # (0.46/0.60/0.74 → 0.62/0.78/0.94). 알파는 눈송이를 순백으로 바꾸는데,
        # 예전 `screen` 은 배경 밝기에 비례해 밝혔기 때문에 같은 값에서 세기가 약해진다.
        # 그대로 두었더니 **'약하게'의 평균 밀림이 0.30 으로 바닥(0.3)에 딱 걸렸다.**
        # 올린 뒤 0.50 / 2.16 / 7.01 이고 남은 결은 113% 다 (상한 140%).
        # 비는 올리지 않았다 — 비는 결이 132%로 이미 상한에 가깝고, 값을 올리면
        # 화면이 예전보다 더 어수선해진다.
        "strengths": {
            "low": {"density": 0.723, "opacity": 0.62},
            "medium": {"density": 0.717, "opacity": 0.78},
            "high": {"density": 0.708, "opacity": 0.94},
        },
        "layer": _layer_snow,
    },
    "water_drops": {
        "label": "물방울 맺힘",
        "hint": "유리에 물방울이 맺힌 것처럼 곳곳이 살짝 휩니다. 비 오는 날 느낌에 씁니다.",
        "order": 24,
        "params": {"size": _slider("방울 크기", 100, 40, 180, 5)},
        # count = 방울 개수. 화면을 유리로 덮어 버리면 영상이 아니라 유리를 보게 되므로
        # 개수를 아껴 쓴다 (memory/effects-must-not-obscure-the-picture.md).
        # 방울을 크게 잡았으므로 개수는 줄인다. 작고 많은 것보다 크고 성긴 편이
        # 물방울로 읽히고, 화면도 덜 가린다.
        # 2026-08-15 에 방울 지름을 0.81배로 줄이면서(fxart.py) 개수를 1.3배 올렸다.
        # 방울이 작아지면 덮는 면적이 줄어 **세기 사다리가 통째로 내려앉기** 때문이다.
        "strengths": {
            "low": {"count": 12},
            "medium": {"count": 25},
            "high": {"count": 44},
        },
        "art": _art_water_drops,
    },
    "bubbles": {
        "label": "비눗방울",
        "hint": "작은 비눗방울이 천천히 이리저리 떠오릅니다. 밝고 산뜻한 장면에 씁니다.",
        "order": 25,
        "params": {"speed": _slider("떠오르는 속도", 100, 30, 250, 5),
                   "size": _slider("방울 크기", 100, 40, 180, 5)},
        # rise = 초당 몇 픽셀 떠오르는가. 사용자가 정한 사양이 "천천히"다.
        # 방울이 겹치면 덮는 면적이 더 안 늘어난다. 그래서 개수만으로는 '많이'가
        # '보통'과 1.27배밖에 안 벌어졌다(가짜 선택지 문턱은 1.3배). 개수와 함께
        # **크기**도 키워서 벌렸다 (options-must-actually-differ.md).
        "strengths": {
            "low": {"count": 11, "rise": 46, "swell": 0.85},
            "medium": {"count": 26, "rise": 58, "swell": 1.00},
            "high": {"count": 58, "rise": 70, "swell": 1.25},
        },
        "art": _art_bubbles,
    },
    "fireworks": {
        "label": "작은 폭죽",
        "hint": "정한 자리에서 작은 폭죽이 한 번 터집니다. 축하하거나 짚어 줄 때 씁니다.",
        "order": 26,
        # 2026-08-15 에 기본 크기를 38 → **22** 로 내리고 하한도 15 → 10 으로 넓혔다
        # (사용자: "폭죽도 아주 작게"). 칸이 작아지면 알갱이도 같이 작아지므로
        # fxart.py 의 알갱이 굵기(칸/28 → 칸/20)를 **함께** 고쳤다.
        "params": {**_PLACE, "size": _slider("터지는 크기", 22, 10, 70)},
        # sparks = 불꽃 알갱이 수, glow = 밝기. 정한 자리에만 걸리므로 화면 전체를
        # 덮지 않는다 — 그래서 '가림' 상한이 아니라 **자리와 크기**로 다스린다.
        "strengths": {
            "low": {"sparks": 28, "glow": 0.62},
            "medium": {"sparks": 60, "glow": 0.82},
            "high": {"sparks": 125, "glow": 1.00},
        },
        "art": _art_fireworks,
    },
    "blur_area": {
        "label": "부분 흐림",
        "hint": "정한 네모 안만 뭉갭니다. 얼굴이나 개인정보를 가릴 때 씁니다.",
        "order": 30,
        "params": {**_PLACE, **_SIZE},
        "strengths": {
            "low": {"radius": 6},
            "medium": {"radius": 14},
            "high": {"radius": 26},
        },
        "build": _build_blur_area,
    },
    "spotlight": {
        "label": "주변 어둡게",
        "hint": "정한 곳만 밝게 두고 둘레를 어둡게 합니다. 한 곳을 보게 할 때 씁니다.",
        "order": 40,
        "params": {**_PLACE, "size": _slider("밝은 부분 크기", 35, 8, 90),
                   "opacity": _OPACITY},
        # dim = 바깥에 남길 밝기 비율. 작을수록 어둡다.
        #
        # ⚠ 2026-08-15 에 크게 올렸다(=덜 어둡게). 옛 값 0.55/0.35/0.18 은 **가장 약한
        # 단계조차** 화면의 94.5%를 건드리고 밝기를 65%로 떨어뜨렸고, '많이'는 38%까지
        # 떨어뜨려 화면의 결도 44.8%만 남겼다. 시선을 모으려고 만든 효과가 정작 볼
        # 것을 지우고 있었다. (memory/effects-must-not-obscure-the-picture.md)
        #
        # ⚠ 같은 날 저녁에 합성 방식을 **알파**로 바꾸면서 값을 한 번 더 잡았다
        # (0.84/0.72/0.56 → 0.86/0.73/0.60). 두 기준이 알파에서는 서로 다르게 움직인다:
        #   · 화면 전체 평균 밝기 — 알파가 **더 밝게** 나온다(검정 바닥이 16이라서)
        #   · 둘레(테두리) 밝기   — 알파가 **더 어둡게** 나온다(가운데를 완전히 그대로
        #     두므로 대비가 크다)
        # 사용자가 실제로 느끼는 것은 **둘레가 얼마나 어두운가**이므로 그쪽(≥62%)에
        # 맞췄다. 처음에 화면 평균 66%에 맞춰 0.49 로 내렸더니 둘레가 52%까지
        # 떨어져 점검이 잡았다. 어두워지는 정도의 간격은 1.93배 · 1.48배다.
        "strengths": {
            "low": {"dim": 0.86},
            "medium": {"dim": 0.73},
            "high": {"dim": 0.60},
        },
        "layer": _layer_spotlight,
    },
    "vignette": {
        "label": "가장자리 어둡게",
        "hint": "네 귀퉁이를 부드럽게 어둡게 해 가운데로 시선을 모읍니다.",
        "order": 45,
        "params": {"opacity": _OPACITY},
        # a 가 클수록 어둡다. 2026-08-15 에 낮췄다 — 옛 값 PI/6·PI/4·PI/3(0.5236·
        # 0.7854·1.0472)은 '많이'에서 밝기를 44.1%까지 떨어뜨렸다.
        # 값을 라디안 숫자로 적는다. PI/10 처럼 식으로 적으면 진하기를 곱할 수 없다.
        "strengths": {
            "low": {"look": [("vignette", {"a": 0.3142})]},          # PI/10
            "medium": {"look": [("vignette", {"a": 0.4833})]},       # PI/6.5
            "high": {"look": [("vignette", {"a": 0.6981})]},         # PI/4.5
        },
        "build": _build_look,
    },
    "color_adjust": {
        "label": "밝기·대비·채도",
        "hint": "화면의 밝기와 또렷함, 색의 진하기를 직접 조절합니다.",
        "order": 60,
        "params": {
            "brightness": _slider("밝기", 0, -100, 100, 1, ""),
            "contrast": _slider("대비(또렷함)", 100, 0, 200),
            "saturation": _slider("채도(색의 진하기)", 100, 0, 200),
        },
        # amount = 슬라이더를 얼마나 세게 반영할지.
        # 2026-08-15 에 0.6/1.0/1.5 에서 낮췄다 — '많이'가 사용자가 정한 값을 1.5배로
        # 부풀려 밝기 168%까지 날려 버렸다. 슬라이더로 이미 세기를 정하는 효과이므로
        # 여기서 더 부풀릴 이유가 없다.
        "strengths": {
            "low": {"amount": 0.5},
            "medium": {"amount": 0.8},
            "high": {"amount": 1.15},
        },
        "build": _build_color_adjust,
    },
    "warm": {
        "label": "따뜻하게",
        "hint": "붉은기를 올려 노을처럼 따뜻한 색으로 바꿉니다.",
        "order": 70,
        "params": {"opacity": _OPACITY},
        # eq 를 **앞에** 둔다. 뒤에 두면 구간 밖까지 화소값이 ±2 밀린다 — 색을 다루는
        # 필터(colorbalance)는 RGB 로, eq 는 YUV 로 일하기 때문에 사이에 변환이 끼는데,
        # 그 변환은 효과가 꺼져 있어도 일어난다. 순서만 바꾸면 차이가 0이 된다(실측).
        # ⚠ `colorbalance` 는 그림자(`rs`)·중간톤(`rm`)·밝은톤(`rh`)을 **따로** 받는다.
        # 처음에 그림자만 지정했더니 밝은 사진에서는 손댈 자리가 없어 **아무 일도
        # 일어나지 않았다.** 중립 회색에 걸어 재 보니 따뜻하게가 +1.0, 차갑게가 0.0 —
        # 이름만 있는 가짜 선택지였다. 세 톤을 모두 지정해 +11 / +25 / +43 으로 벌렸다.
        # 2026-08-15 에 전 단계를 0.7배로 낮췄다. 비율을 그대로 곱했으므로 단계 간격
        # (2.27배 · 1.72배)은 유지된다 — 가짜 선택지가 되지 않는다.
        "strengths": {
            "low": {"look": [
                ("eq", {"saturation": 1.04}),
                ("colorbalance", {"rs": 0.04, "rm": 0.05, "rh": 0.02,
                                  "bs": -0.03, "bm": -0.05, "bh": -0.02})]},
            "medium": {"look": [
                ("eq", {"saturation": 1.08}),
                ("colorbalance", {"rs": 0.07, "rm": 0.10, "rh": 0.05,
                                  "bs": -0.06, "bm": -0.10, "bh": -0.05})]},
            "high": {"look": [
                ("eq", {"saturation": 1.15}),
                ("colorbalance", {"rs": 0.12, "rm": 0.17, "rh": 0.08,
                                  "bs": -0.10, "bm": -0.17, "bh": -0.08})]},
        },
        "build": _build_look,
    },
    "cool": {
        "label": "차갑게",
        "hint": "푸른기를 올려 새벽처럼 차분하고 서늘한 색으로 바꿉니다.",
        "order": 71,
        "params": {"opacity": _OPACITY},
        # 따뜻하게와 같은 이유로 세 톤을 모두 지정한다. 따뜻하게와 짝을 맞춰
        # 2026-08-15 에 0.7배로 낮췄다.
        "strengths": {
            "low": {"look": [
                ("colorbalance", {"rs": -0.03, "rm": -0.04, "rh": -0.02,
                                  "bs": 0.04, "bm": 0.06, "bh": 0.03})]},
            "medium": {"look": [
                ("colorbalance", {"rs": -0.06, "rm": -0.08, "rh": -0.04,
                                  "bs": 0.07, "bm": 0.11, "bh": 0.06})]},
            "high": {"look": [
                ("colorbalance", {"rs": -0.10, "rm": -0.14, "rh": -0.07,
                                  "bs": 0.12, "bm": 0.19, "bh": 0.09})]},
        },
        "build": _build_look,
    },
    "vivid": {
        "label": "선명하게",
        "hint": "색을 진하게, 명암을 또렷하게 만듭니다.",
        "order": 72,
        "params": {"opacity": _OPACITY},
        # 2026-08-15 에 낮췄다 (옛 값 1.20/1.45/1.75 · 1.07/1.18/1.30).
        # 1을 넘는 몫을 0.72배로 줄였으므로 단계 간격은 그대로다.
        "strengths": {
            "low": {"look": [("eq", {"saturation": 1.14, "contrast": 1.05})]},
            "medium": {"look": [("eq", {"saturation": 1.32, "contrast": 1.13})]},
            "high": {"look": [("eq", {"saturation": 1.54, "contrast": 1.22})]},
        },
        "build": _build_look,
    },
    "vintage": {
        "label": "빈티지",
        "hint": "빛바랜 옛날 사진처럼 누런 기가 도는 색으로 바꿉니다.",
        "order": 73,
        "params": {"opacity": _OPACITY},
        # 원래 색과 세피아를 섞은 비율이다. 2026-08-15 에 0.45/0.70/1.00 에서
        # **0.20 / 0.33 / 0.50** 으로 낮췄다 — 옛 '많이'는 세피아를 100% 섞어 원래 색을
        # 통째로 덮었다(화면의 99.4%가 바뀜). 섞는 식은 M = (1-f)·원래색 + f·세피아 다.
        # 따뜻하게와 같은 이유로 eq 를 **앞에** 둔다.
        "strengths": {
            "low": {"look": [
                ("eq", {"contrast": 1.02}),
                ("colorchannelmixer", {"rr": 0.879, "rg": 0.154, "rb": 0.038,
                                       "gr": 0.070, "gg": 0.937, "gb": 0.034,
                                       "br": 0.054, "bg": 0.107, "bb": 0.826})]},
            "medium": {"look": [
                ("eq", {"contrast": 1.03}),
                ("colorchannelmixer", {"rr": 0.800, "rg": 0.254, "rb": 0.062,
                                       "gr": 0.115, "gg": 0.896, "gb": 0.055,
                                       "br": 0.090, "bg": 0.176, "bb": 0.713})]},
            "high": {"look": [
                ("eq", {"contrast": 1.05}),
                ("colorchannelmixer", {"rr": 0.697, "rg": 0.385, "rb": 0.095,
                                       "gr": 0.175, "gg": 0.843, "gb": 0.084,
                                       "br": 0.136, "bg": 0.267, "bb": 0.566})]},
        },
        "build": _build_look,
    },
    "mono": {
        "label": "흑백",
        "hint": "색을 빼 흑백으로 만듭니다. 많이로 하면 명암이 더 강해집니다.",
        "order": 74,
        "params": {"opacity": _OPACITY},
        # 흑백은 결(디테일)을 지우지 않으므로 '가림'의 문제가 아니다. 다만 '많이'의
        # 대비 1.25 는 어두운 곳을 뭉개 내용을 잃게 했다 — 2026-08-15 에 1.12 로 낮추고
        # '약하게'도 색을 조금 더 남겼다.
        # 진하기를 100% 아래로 내리면 색이 조금 남고, 100% 위로는 s 가 0에서 멈춘다
        # (색은 더 뺄 수 없다). 대신 대비가 계속 올라간다.
        "strengths": {
            "low": {"look": [("hue", {"s": 0.45})]},
            "medium": {"look": [("hue", {"s": 0.0})]},
            "high": {"look": [("hue", {"s": 0.0}), ("eq", {"contrast": 1.12})]},
        },
        "build": _build_look,
    },
    "box_mark": {
        "label": "네모 테두리",
        "hint": "노란 네모로 한 곳을 짚어 줍니다. \"여기 보세요\" 표시입니다.",
        # 맨 마지막에 그린다 — 색감 프리셋이 표시까지 물들이면 안 되기 때문이다.
        "order": 90,
        "params": {**_PLACE, **_SIZE},
        # 화면 높이에 대한 비율. 720에서 3 / 6 / 10 픽셀이 된다.
        "strengths": {
            "low": {"thick": 0.004},
            "medium": {"thick": 0.008},
            "high": {"thick": 0.014},
        },
        "build": _build_box_mark,
    },
}


def kind_list() -> list[dict[str, Any]]:
    """화면에 보여 줄 효과 종류 목록 (만드는 함수는 빼고 넘긴다).

    `params` 를 **막대 하나짜리 설명서**로 넘긴다. 화면은 이 설명서만 보고 슬라이더를
    그리므로, 새 효과에 값을 붙여도 화면 코드를 고칠 필요가 없다.
    """
    return [
        {
            "kind": name,
            "label": spec["label"],
            "hint": spec["hint"],
            "params": [{"key": key, **detail} for key, detail in spec["params"].items()],
            "strengths": [
                {"value": s, "label": STRENGTH_LABELS[s]} for s in STRENGTHS
            ],
        }
        for name, spec in sorted(KINDS.items(), key=lambda kv: kv[1]["order"])
    ]


def defaults_for(kind: str) -> dict[str, float]:
    """그 효과의 값 기본값. 화면이 막대를 새로 만들 때 쓴다."""
    return {key: detail["default"] for key, detail in KINDS.get(kind, {}).get("params", {}).items()}


def _clean_params(kind: str, raw: Any) -> dict[str, Any]:
    """등록표에 적힌 값만 남기고 **각자의 범위** 안으로 다듬는다.

    범위를 값마다 따로 두는 이유: 속도는 30~250%, 위치는 0~100%, 밝기는 -100~100 처럼
    자가 제각각이다. 예전처럼 전부 0~100 으로 자르면 속도를 100 위로 못 올린다.
    """
    specs = KINDS[kind]["params"]
    given = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, detail in specs.items():
        fallback = float(detail["default"])
        try:
            number = float(given.get(key, fallback))
        except (TypeError, ValueError):
            number = fallback
        if not math.isfinite(number):
            number = fallback
        out[key] = round(max(float(detail["min"]), min(float(detail["max"]), number)), 2)
    return out


def normalize(items: Any, duration: float | None = None) -> list[dict[str, Any]]:
    """사용자가 보낸 효과 목록을 다듬는다. 시스템 경계에서 한 번만 거른다.

    버리는 것: 등록표에 없는 종류 · 끝이 시작보다 앞서거나 같은 것 ·
    영상이 끝난 뒤에 있는 것.
    다듬는 것: 0초보다 앞선 시작 · 영상 길이를 넘는 끝 · 모르는 세기 이름 · 이름표.
    """
    cleaned: list[dict[str, Any]] = []
    taken: set[str] = set()

    for raw in (items or []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in KINDS:
            continue

        try:
            start = float(raw.get("start", 0.0))
            end = float(raw.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue

        start = max(0.0, start)
        if duration is not None and duration > 0:
            if start >= float(duration):
                continue
            end = min(end, float(duration))
        if end <= start:
            continue

        strength = str(raw.get("strength") or "")
        if strength not in STRENGTHS:
            strength = "medium"

        given_id = str(raw.get("id") or "").strip()
        if not given_id or given_id in taken:
            number = len(taken) + 1
            given_id = f"fx-{number}"
            while given_id in taken:
                number += 1
                given_id = f"fx-{number}"
        taken.add(given_id)

        cleaned.append({
            "id": given_id,
            "kind": kind,
            "start": round(start, 3),
            "end": round(end, 3),
            "strength": strength,
            "params": _clean_params(kind, raw.get("params")),
        })

    # 화면의 막대 순서와 저장 순서를 맞춘다. 겹치는 막대는 버리지 않는다.
    cleaned.sort(key=lambda b: (b["start"], b["id"]))
    return cleaned


def _compose(layers: list[tuple[str, str]]) -> str:
    """덧씌울 그림들을 원본 위에 차례로 얹는 필터그래프를 만든다.

    원본을 그림 수 + 1 갈래로 나눠, 한 갈래는 바탕으로 두고 나머지 갈래마다
    그림을 만든 뒤 차례로 합성한다. 그림을 **원본에서 갈라 만드는** 이유는
    `color=` 같은 생성 필터가 **끝이 없는 스트림**이라 렌더가 영원히 안 끝나기
    때문이다 (memory/ffmpeg-effect-layer-traps.md ④ — 30초 영상이 6분 40초가
    지나도 안 끝났다). 원본에서 갈라 오면 길이가 원본과 같아 그 함정을 아예 만나지
    않는다.

    얹는 방법은 **알파(투명도) 합성 하나뿐**이다. 그림마다 알파를 그려 오면
    `overlay` 한 줄로 끝난다.

    ⚠ 예전에는 `blend` 로 **밝기(Y) 면만** 섞고 색(U·V) 면은 원본을 그대로 두었다.
    색 면까지 섞으면 화면이 뿌예지는 것을 피하려는 것이었고(같은 문서 ③), 구간 밖이
    한 값도 안 달라지는 장점이 있었다. 그런데 **색을 안 건드리는 것이 곧 결함이었다** —
    밝기만 바꾸면 '밝기에 견준 색'이 변해서, 어둡게 하면 화면이 보라색이 되고
    밝히면 빗줄기가 배경색을 머금는다(같은 문서 ③-f). 알파 합성은 색차도 함께
    데려가면서 **구간 밖 완전 일치도 그대로 지킨다**(실측 0개). 그래서 `blend` 경로는
    통째로 걷어 냈다.
    """
    count = len(layers)
    lines = [f"split={count + 1}[fxbg]" + "".join(f"[fxin{i}]" for i in range(count))]
    for index, (made, _gate) in enumerate(layers):
        lines.append(f"[fxin{index}]{made}[fxlay{index}]")

    source = "fxbg"
    for index, (_made, gate) in enumerate(layers):
        step = f"[{source}][fxlay{index}]overlay=0:0"
        if gate:
            step += f":enable='{gate}'"
        if index < count - 1:
            source = f"fxmix{index}"
            step += f"[{source}]"
        lines.append(step)

    return ";".join(lines)


def needs_art(items: list[dict[str, Any]]) -> bool:
    """이 효과 목록에 **그림 파일이 필요한 효과**가 들어 있는가."""
    return any(KINDS.get(b.get("kind", ""), {}).get("art") for b in (items or []))


def build_filter(
    items: list[dict[str, Any]], width: int, height: int, fps: float,
    folder: str | Path | None = None,
) -> str | None:
    """효과 목록 전체를 FFmpeg 영상 필터 문자열 하나로 만든다.

    효과가 하나도 없으면 None 을 돌려준다 — 그러면 지금까지와 똑같은 경로로 간다.
    효과가 없는 프로젝트가 느려지거나 달라지는 일이 없어야 한다.

    거는 자리는 **화면비·확대 뒤, 자막 앞**이다. 자막이 맨 마지막이 아니면 글자가
    효과에 가려 읽기 어려워진다.

    `folder` 는 물방울·비눗방울·작은 폭죽이 쓸 **그림을 둘 폴더**다. FFmpeg 이 바로
    그 폴더에서 실행되므로 필터에는 파일 이름만 들어간다.

    ⚠ 그림이 필요한 효과가 있는데 `folder` 를 안 주면 **일부러 터뜨린다.** 조용히
    건너뛰면 "효과를 걸었는데 아무 일도 안 일어나는" 결과가 되는데, 이 저장소에서
    나온 결함 대부분이 바로 그런 '오류 없이 틀린 결과'였다.
    """
    if not items or not (width > 0 and height > 0 and fps > 0):
        return None
    if needs_art(items) and folder is None:
        raise ValueError(
            "물방울·비눗방울·작은 폭죽은 그림 파일이 필요합니다. "
            "build_filter(..., folder=그림을_둘_폴더) 로 폴더를 알려 주세요."
        )

    parts: list[str] = []
    layers: list[tuple[str, str]] = []

    for name, spec in sorted(KINDS.items(), key=lambda kv: kv[1]["order"]):
        bars = [b for b in items if b.get("kind") == name]
        if not bars:
            continue
        if spec.get("build"):
            made = spec["build"](bars, int(width), int(height), float(fps))
            if made:
                parts.append(made)
        if spec.get("layer"):
            layers.extend(spec["layer"](bars, int(width), int(height), float(fps)))
        if spec.get("art"):
            # 그림을 쓰는 효과는 **먼저 얹혀 있던 레이어를 마무리한 뒤**에 온다.
            # 순서를 지키지 않으면 비 위에 물방울이 와야 하는데 뒤바뀐다.
            if layers:
                parts.append(_compose(layers))
                layers = []
            parts.extend(spec["art"](bars, int(width), int(height), float(fps),
                                     Path(folder)))

    if layers:
        parts.append(_compose(layers))

    return ",".join(parts) if parts else None
