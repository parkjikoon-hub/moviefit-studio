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
from typing import Any, Callable

STRENGTHS = ("low", "medium", "high")
STRENGTH_LABELS = {"low": "약하게", "medium": "보통", "high": "많이"}


def _fps_text(fps: float) -> str:
    """FFmpeg 에 넣을 프레임률 문자열. 30.0 은 '30', 29.97 은 '29.97' 로 쓴다."""
    return f"{float(fps):g}"


def _by_strength(bars: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """막대를 세기별로 묶는다. 세기가 같으면 **그림 한 장을 같이 쓴다.**

    막대 하나마다 그림을 따로 만들면 막대를 열 개 놓았을 때 화면을 열 번 다시
    그려 그만큼 느려진다. 세기는 세 가지뿐이므로 아무리 많이 놓아도 그림은
    최대 세 장이다.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for bar in bars:
        groups.setdefault(bar["strength"], []).append(bar)
    return [(name, groups[name]) for name in STRENGTHS if name in groups]


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


def _layer_rain(
    bars: list[dict[str, Any]], width: int, height: int, fps: float
) -> list[tuple[str, str]]:
    """비 — 세로로만 늘려 가느다란 줄기를 만들고 빠르게 떨어뜨린다.

    씨앗 그림의 **줄 수**가 빗줄기 길이와 개수를 함께 정한다. 화면 높이의 1/15 로
    잡으면 점 하나가 15배로 늘어나 세로 16픽셀 × 가로 1.0~1.5픽셀짜리 줄기가 된다
    (실측). 줄 수가 적어 점 개수도 알맞게 성기다.
    """
    made: list[tuple[str, str]] = []
    for index, (strength, group) in enumerate(_by_strength(bars)):
        spec = KINDS["rain"]["strengths"][strength]
        tag = f"rn{index}"
        rows = _even_up(height / 15)
        made.append((
            _dots(width, rows, spec["density"], 1234 + index)
            + "," + _tile3(tag)
            + f",scale={width}:{3 * height}:flags=neighbor"
            + ",gblur=sigma=0.8:sigmaV=3.0"          # 모서리만 살짝 눅인다
            + f",crop={width}:{height}:0:{_fall(height, 900)}"
            + f",lutyuv=y='val*{spec['opacity']}'",
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
    for index, (strength, group) in enumerate(_by_strength(bars)):
        spec = KINDS["snow"]["strengths"][strength]
        gate = _enable(group)
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
                _dots(cols, rows, spec["density"] - 0.004 * (1 - depth), seed + index)
                + "," + _tile3(tag)
                + f",scale={canvas}:{3 * height}:flags=bicubic"
                + f",crop={width}:{height}"
                  f":'{(canvas - width) // 2}+{sway}*sin(2*PI*{hertz}*t)'"
                  f":{_fall(height, speed)}"
                + f",lutyuv=y='val*{round(spec['opacity'] * dim, 4)}'",
                gate,
            ))
    return made


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
        "params": {},
        # density = 점으로 남길 문턱값(밝기 범위의 몇 %). **낮을수록 점이 많다.**
        # opacity = 레이어를 얼마나 진하게 얹을 것인가.
        # 둘을 함께 움직여야 단계가 벌어진다 — 덕킹에서 값 하나만 움직였다가
        # 이름만 다른 가짜 선택지를 만든 적이 있다 (options-must-actually-differ).
        # 실측(1280×720): 화면의 5.2% → 15.9% → 29.9% 가 밝아진다. 3.04배 · 1.88배.
        "strengths": {
            "low": {"density": 0.715, "opacity": 0.55},
            "medium": {"density": 0.703, "opacity": 0.80},
            "high": {"density": 0.681, "opacity": 1.00},
        },
        "layer": _layer_rain,
    },
    "snow": {
        "label": "눈",
        "hint": "둥근 눈송이가 좌우로 흔들리며 천천히 내립니다.",
        "order": 21,
        "params": {},
        # 실측(1280×720): 화면의 2.7% → 7.0% → 20.9%. 2.56배 · 2.99배.
        "strengths": {
            "low": {"density": 0.723, "opacity": 0.55},
            "medium": {"density": 0.717, "opacity": 0.80},
            "high": {"density": 0.705, "opacity": 1.00},
        },
        "layer": _layer_snow,
    },
}


def kind_list() -> list[dict[str, Any]]:
    """화면에 보여 줄 효과 종류 목록 (만드는 함수는 빼고 넘긴다)."""
    return [
        {
            "kind": name,
            "label": spec["label"],
            "hint": spec["hint"],
            "params": dict(spec["params"]),
            "strengths": [
                {"value": s, "label": STRENGTH_LABELS[s]} for s in STRENGTHS
            ],
        }
        for name, spec in sorted(KINDS.items(), key=lambda kv: kv[1]["order"])
    ]


def _clean_params(kind: str, raw: Any) -> dict[str, Any]:
    """등록표에 적힌 열쇠만 남기고, 숫자는 0~100 안으로 다듬는다."""
    defaults = KINDS[kind]["params"]
    given = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, fallback in defaults.items():
        value = given.get(key, fallback)
        if isinstance(fallback, (int, float)):
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float(fallback)
            if not math.isfinite(number):
                number = float(fallback)
            out[key] = round(max(0.0, min(100.0, number)), 2)
        else:
            out[key] = value
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


# 밝기(Y) 면에만 screen 합성을 걸고 색(U·V) 면은 원본을 그대로 둔다.
#
# 이것이 이 파일에서 가장 중요한 한 줄이다. 색 면까지 합성하면 색이 중립값 쪽으로
# 끌려가 **온 화면이 뿌예진다** (memory/ffmpeg-effect-layer-traps.md ③).
# 조사 때는 모든 입력을 RGB(`format=gbrp`)로 바꿔서 피했지만, 그러면 효과를 켜는
# 것만으로 **영상 전체의 색이 미세하게 변한다** — 실측으로 화소값의 31%가 달라졌고
# 최대 49까지 밀렸다. 비도 눈도 흰색이라 밝기만 올리면 충분하므로, 색 면은 아예
# 건드리지 않는 편이 낫다. 그래서 효과 구간 **바깥은 원본과 한 값도 다르지 않다.**
_LUMA_SCREEN = (
    "blend=c0_mode=screen:c1_mode=normal:c2_mode=normal"
    ":c1_opacity=0:c2_opacity=0"
)


def _compose(layers: list[tuple[str, str]]) -> str:
    """덧씌울 그림들을 원본 위에 차례로 얹는 필터그래프를 만든다.

    원본을 그림 수 + 1 갈래로 나눠, 한 갈래는 바탕으로 두고 나머지 갈래마다
    그림을 만든 뒤 차례로 합성한다. 그림을 **원본에서 갈라 만드는** 이유는
    `color=` 같은 생성 필터가 **끝이 없는 스트림**이라 렌더가 영원히 안 끝나기
    때문이다 (같은 문서 ④ — 30초 영상이 6분 40초가 지나도 안 끝났다).
    원본에서 갈라 오면 길이가 원본과 같아 그 함정을 아예 만나지 않는다.
    """
    count = len(layers)
    lines = [f"split={count + 1}[fxbg]" + "".join(f"[fxin{i}]" for i in range(count))]
    for index, (made, _gate) in enumerate(layers):
        lines.append(f"[fxin{index}]{made}[fxlay{index}]")

    source = "fxbg"
    for index, (_made, gate) in enumerate(layers):
        step = f"[{source}][fxlay{index}]{_LUMA_SCREEN}"
        if gate:
            step += f":enable='{gate}'"
        if index < count - 1:
            source = f"fxmix{index}"
            step += f"[{source}]"
        lines.append(step)

    return ";".join(lines)


def build_filter(
    items: list[dict[str, Any]], width: int, height: int, fps: float
) -> str | None:
    """효과 목록 전체를 FFmpeg 영상 필터 문자열 하나로 만든다.

    효과가 하나도 없으면 None 을 돌려준다 — 그러면 지금까지와 똑같은 경로로 간다.
    효과가 없는 프로젝트가 느려지거나 달라지는 일이 없어야 한다.

    거는 자리는 **화면비·확대 뒤, 자막 앞**이다. 자막이 맨 마지막이 아니면 글자가
    효과에 가려 읽기 어려워진다.
    """
    if not items or not (width > 0 and height > 0 and fps > 0):
        return None

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

    if layers:
        parts.append(_compose(layers))

    return ",".join(parts) if parts else None
