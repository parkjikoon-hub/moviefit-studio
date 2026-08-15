"""화면 효과가 쓰는 **그림**을 파이썬이 그린다 (물방울·비눗방울·작은 폭죽).

왜 이 파일이 따로 있는가:

앞의 13종은 FFmpeg 내장 필터만으로 만들어졌다. 남은 셋은 그럴 수 없다 —
물방울은 **굴절 지도**가, 비눗방울은 **고리 모양**이, 폭죽은 **입자 운동**이
필요한데, 이것들을 필터 수식으로 적으면 감당할 수 없이 길어진다. 파이썬이
그림으로 그려 두고 FFmpeg 이 읽게 하는 편이 짧고 정확하다.

## 어떻게 FFmpeg 에 넘기는가 — `-i` 를 늘리지 않는다

인수인계 문서는 "그림을 겹치려면 `-i` 를 더 붙이고 `-filter_complex` 로 옮겨야
하며, 그때 소리 흐름과 자막 필터가 살아남는지 다시 재야 한다"고 적었다.
**실측해 보니 그럴 필요가 없었다.** FFmpeg 의 `movie` 소스 필터는 필터그래프
**안에서** 파일을 연다. 그래서 지금의 `-vf` 한 줄 구조를 한 군데도 안 건드린다.

확인한 것 (전부 실측):

    movie= 로 그림을 불러 -vf 안에서 쓴다                     됨
    displace · overlay 둘 다 enable 을 받는다                 구간 밖 다른 값 0개
    movie= + displace + 자막(ass) + 소리 복사를 한 명령으로   전부 살아남음
    정지 그림을 loop+setpts 로 흘려보내면 crop 의 시간식이 산다 0.3초에 렌더 끝남

마지막 줄이 중요하다. `color=` 같은 생성 필터는 **끝이 없어서** 렌더가 영원히
안 끝나는데(memory/ffmpeg-effect-layer-traps.md ④), `loop` 로 만든 흐름은
`overlay=...:shortest=1` 과 함께 쓰면 원본이 끝날 때 같이 끝난다.

## 경로에 관한 규칙 — 파일 이름만 넘긴다

필터 문자열에 윈도우 절대 경로를 넣으면 콜론과 특수문자 때문에 깨진다
(memory/ffmpeg-filter-path-escaping.md). 자막이 이미 쓰고 있는 방법을 그대로
따른다: FFmpeg 을 **그림이 있는 폴더에서 실행**하고 필터에는 **파일 이름만** 준다.
그래서 이 파일이 만드는 이름에는 `,` `;` `[` `]` `'` `:` 가 하나도 없다.

## 왜 설정마다 이름이 다른가

같은 효과라도 세기·값이 다르면 그림이 달라야 한다. 이름에 설정을 요약한 짧은
지문을 붙여, 설정이 같으면 **같은 파일을 다시 쓰고** 다르면 따로 만든다.
비를 만들 때 속도가 다른 막대가 그림 한 장을 같이 써서 한쪽 속도가 조용히
무시된 적이 있다 — 그 실수를 이름 단계에서 막는다.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# 폭죽 한 판의 길이. 짧아야 '작은 폭죽'이 된다.
BURST_FRAMES = 30


def stamp(kind: str, strength: str, params: dict[str, Any],
          width: int, height: int) -> str:
    """설정 하나를 짧은 지문으로 만든다. 파일 이름에 쓰므로 영문·숫자만 나온다."""
    seed = repr((kind, strength, sorted(params.items()), int(width), int(height)))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _seed_of(tag: str) -> np.random.Generator:
    """지문에서 난수 씨앗을 만든다. 같은 설정이면 **언제나 같은 그림**이 나온다."""
    return np.random.default_rng(int(tag, 16) % (2 ** 32))


def _grid(width: int, height: int):
    return np.mgrid[0:height, 0:width].astype(np.float32)


# ══════════════════════════════════════════════════════════════
# 물방울 맺힘 — 굴절 지도 두 장 + 반짝임 한 장
# ══════════════════════════════════════════════════════════════
#
# 물방울은 그림을 **덧붙이는** 것이 아니라 원본 화면을 방울 모양대로 **휘게**
# 만드는 것이다. 그래서 소재 영상을 사 올 필요가 없고, 오히려 그편이 낫다 —
# 소재는 원본이 무엇이든 같은 그림이지만 굴절은 **그 영상의 실제 화면**이
# 방울에 비친다.
#
# `displace` 는 지도의 밝기를 '얼마나 밀 것인가'로 읽는다. 128 이 '안 밂'이고
# 거기서 멀어질수록 많이 민다. 방울 안쪽만 렌즈처럼 밀고 바깥은 128 그대로 둔다.


def draw_water_drops(folder: Path, tag: str, width: int, height: int,
                     count: int, scale: float) -> dict[str, str]:
    """굴절 지도 두 장과 반짝임 한 장을 그린다.

    count 는 방울 개수, scale 은 방울 크기 배수다. 화면을 가리지 않으려면
    **방울이 화면의 일부만 덮어야** 한다 — 온 화면을 방울로 채우면 영상이
    아니라 유리를 보게 된다 (memory/effects-must-not-obscure-the-picture.md).
    """
    rng = _seed_of(tag)
    yy, xx = _grid(width, height)
    xmap = np.full((height, width), 128.0, np.float32)
    ymap = np.full((height, width), 128.0, np.float32)
    shine = np.zeros((height, width, 4), np.float32)

    # 방울 크기. 처음에 min/26 으로 잡았더니 **화면에서 거의 안 보였다** —
    # 굴절만으로는 물방울로 읽히지 않는다. 눈으로 확인하고서야 드러났다.
    # 그래서 min/17 로 키웠는데 이번에는 사용자가 "좀 작게" 라고 했다.
    # 2026-08-15 에 **min/21** 로 줄였다 — 안 보였던 26 과 컸던 17 의 사이 값이고,
    # 지름이 0.81배가 된다. 덮는 면적이 0.66배로 줄므로 등록표의 개수를 1.3배
    # 올려 세기 사다리를 유지한다.
    base = min(width, height) / 21.0 * scale
    for _ in range(count):
        cx = float(rng.uniform(0, width))
        cy = float(rng.uniform(0, height))
        rad = float(base * rng.uniform(0.45, 1.35))
        if rad < 3.0:
            continue

        dx, dy = xx - cx, yy - cy
        dist = np.sqrt(dx * dx + dy * dy)
        inside = dist < rad
        if not inside.any():
            continue

        # 렌즈: 가운데는 그대로 두고 가장자리로 갈수록 바깥 그림을 당겨 온다.
        # 세제곱을 쓰면 가운데가 넓고 평평해져 진짜 물방울처럼 보인다.
        norm = np.clip(dist / rad, 0, 1)
        pull = (norm ** 3) * (rad * 0.78)
        safe = np.maximum(dist, 1e-6)
        xmap += np.where(inside, dx / safe * pull, 0.0)
        ymap += np.where(inside, dy / safe * pull, 0.0)

        # 반짝임 — 왼쪽 위에 밝은 점. **이것이 방울을 방울로 만든다.**
        hx, hy = cx - rad * 0.36, cy - rad * 0.36
        spot = np.sqrt((xx - hx) ** 2 + (yy - hy) ** 2)
        glow = np.clip(1.0 - spot / max(2.0, rad * 0.34), 0, 1) ** 1.5
        for chan in range(3):
            shine[..., chan] = np.maximum(shine[..., chan], glow * 255.0)
        shine[..., 3] = np.maximum(shine[..., 3], glow * 225.0)

        # 테두리 — 위쪽은 어둡고 아래쪽은 밝다. 빛이 방울을 통과해 아래로 모이기
        # 때문이고, 이 두 줄이 있어야 방울이 유리처럼 도드라진다.
        ring = np.clip(1.0 - np.abs(dist - rad * 0.92) / max(1.6, rad * 0.16), 0, 1)
        upper, lower = ring * (dy <= 0), ring * (dy > 0)
        for chan in range(3):
            shine[..., chan] = np.maximum(shine[..., chan], lower * 235.0)
        shine[..., 3] = np.maximum(shine[..., 3], lower * 120.0)
        shine[..., 3] = np.maximum(shine[..., 3], upper * 105.0)   # 위쪽은 검게 남는다

    names = {"x": f"fx_{tag}_dx.png", "y": f"fx_{tag}_dy.png", "shine": f"fx_{tag}_ds.png"}
    for arr, key in ((xmap, "x"), (ymap, "y")):
        flat = np.clip(arr, 0, 255).astype(np.uint8)
        Image.fromarray(np.dstack([flat] * 3)).save(folder / names[key])
    Image.fromarray(np.clip(shine, 0, 255).astype(np.uint8)).save(folder / names["shine"])
    return names


# ══════════════════════════════════════════════════════════════
# 비눗방울 — 세로로 두 번 쌓은 고리 그림
# ══════════════════════════════════════════════════════════════
#
# 사용자가 정한 사양: **천천히 · 이리저리 · 작게.**
#
# 떠오르게 만드는 방법은 비·눈과 다르다. 비·눈은 잘라내는 창을 움직였지만
# 비눗방울은 `overlay` 의 **자리**를 시간식으로 움직인다. 그래야 알파(투명)가
# 살아 방울 너머로 화면이 비친다.
#
# 그림을 세로로 **두 번** 쌓는 이유: 자리를 -H 에서 0 까지 움직이다가 되돌아갈 때
# 그림이 통째로 바뀌면 방울이 한 번씩 깜빡인다. 위아래가 같은 그림이면 티가 안 난다.


def draw_bubbles(folder: Path, tag: str, width: int, height: int,
                 count: int, scale: float, sway: int) -> str:
    """비눗방울 고리를 그린 그림 한 장 (세로로 두 겹).

    가로로도 흔들리므로 그림이 화면보다 `2*sway` 만큼 넓어야 한다.
    """
    rng = _seed_of(tag)
    span = width + 2 * sway
    yy, xx = _grid(span, height)
    tile = np.zeros((height, span, 4), np.float32)

    # 2026-08-15 에 42 → 50 으로 줄였다 (사용자: "비눗방울 원도 조금만 더 작게").
    # 지름이 0.84배가 된다. **"조금만"이라고 했으므로 물방울보다 덜 줄인다.**
    # 개수는 그대로 둔다 — 비눗방울은 셋 중 존재감이 가장 컸다(화면의 9.8%).
    base = min(width, height) / 50.0 * scale
    for _ in range(count):
        cx = float(rng.uniform(0, span))
        cy = float(rng.uniform(0, height))
        rad = float(base * rng.uniform(0.5, 1.5))
        if rad < 2.5:
            continue

        # 세로로 되풀이되어야 하므로 위아래로 감싸 그린다 (이음매 없애기)
        for wrap in (-height, 0, height):
            dist = np.sqrt((xx - cx) ** 2 + (yy - (cy + wrap)) ** 2)
            # 고리 — 테두리만 밝고 속은 거의 비어 있다. 속이 차 있으면 화면을 가린다.
            edge = np.clip(1.0 - np.abs(dist - rad) / max(1.6, rad * 0.26), 0, 1) ** 1.4
            # 비눗방울 특유의 무지개기 — 위쪽은 푸르고 아래쪽은 붉게
            tint = np.clip((yy - (cy + wrap)) / max(1.0, rad), -1, 1)
            tile[..., 0] = np.maximum(tile[..., 0], edge * (200 + 55 * tint))
            tile[..., 1] = np.maximum(tile[..., 1], edge * 225)
            tile[..., 2] = np.maximum(tile[..., 2], edge * (255 - 45 * tint))
            tile[..., 3] = np.maximum(tile[..., 3], edge * 205)
            # 왼쪽 위 반짝임 — 이것이 있어야 유리구슬이 아니라 비눗방울로 읽힌다
            hx, hy = cx - rad * 0.38, (cy + wrap) - rad * 0.38
            shine = np.clip(1.0 - np.sqrt((xx - hx) ** 2 + (yy - hy) ** 2)
                            / max(1.4, rad * 0.22), 0, 1) ** 1.6
            for chan in range(3):
                tile[..., chan] = np.maximum(tile[..., chan], shine * 255)
            tile[..., 3] = np.maximum(tile[..., 3], shine * 225)
            # 아주 옅은 속 — 있는 듯 없는 듯해야 뒤가 보인다
            body = (dist < rad) * 0.10
            tile[..., 3] = np.maximum(tile[..., 3], body * 255)

    name = f"fx_{tag}_bb.png"
    Image.fromarray(np.clip(np.vstack([tile, tile]), 0, 255).astype(np.uint8)).save(
        folder / name)
    return name


# ══════════════════════════════════════════════════════════════
# 작은 폭죽 — 장면을 세로로 이어 붙인 한 장 (넘겨 가며 보여 준다)
# ══════════════════════════════════════════════════════════════
#
# 폭죽은 시간에 따라 변한다. 그래서 장면 여러 장을 세로로 이어 붙여 놓고
# FFmpeg 이 `crop` 으로 시각에 맞는 칸을 잘라 쓴다 — 만화책 넘기기와 같다.
#
# 화면 전체가 아니라 **작은 칸 하나**에만 그린다. 그래야 '요소요소 작은 폭죽'이
# 되고, 화면을 가리지 않는다. 자리는 사용자가 정한다.


def draw_fireworks(folder: Path, tag: str, cell: int,
                   sparks: int, brightness: float) -> str:
    """폭죽 한 판을 장면 BURST_FRAMES 개로 그려 세로로 이어 붙인다."""
    rng = _seed_of(tag)
    sheet = np.zeros((cell * BURST_FRAMES, cell, 4), np.uint8)
    gy, gx = _grid(cell, cell)

    # 입자마다 방향·빠르기·색·수명이 다르다. 다 같으면 폭죽이 아니라 원이 된다.
    angle = rng.uniform(0, 2 * math.pi, sparks)
    speed = rng.uniform(0.35, 1.0, sparks) ** 0.6
    life = rng.uniform(0.55, 1.0, sparks)
    warm = rng.uniform(0.0, 1.0, sparks)

    reach = cell * 0.42
    # 알갱이 하나의 굵기. 화면 크기를 따라가야 4K 에서 점처럼 사라지지 않는다.
    # 처음에 2.6픽셀로 고정했더니 720p 화면에서 밝은 화소가 **698개**뿐이라
    # 사실상 보이지 않았다 (실측).
    #
    # ⚠ 2026-08-15 에 폭죽 칸을 아주 작게(기본 38% → 22%) 줄이면서 나누는 수도
    # 28 → 20 으로 함께 줄였다. **칸만 줄이면 알갱이가 다시 점으로 사라진다** —
    # `cell / 28` 은 칸을 따라 작아지기 때문이다. 위에서 겪은 실수를 되풀이하지
    # 않으려고 둘을 같이 움직인다.
    grain = max(2.6, cell / 20.0)

    def place(frame, px, py, power, idx):
        dist = np.sqrt((gx - px) ** 2 + (gy - py) ** 2)
        core = np.clip(1.0 - dist / grain, 0, 1)
        halo = np.clip(1.0 - dist / (grain * 3.2), 0, 1) ** 2 * 0.45   # 은은한 번짐
        glow = np.clip(core + halo, 0, 1) * power
        frame[..., 0] = np.maximum(frame[..., 0], glow * 255)
        frame[..., 1] = np.maximum(frame[..., 1], glow * (255 - 70 * warm[idx]))
        frame[..., 2] = np.maximum(frame[..., 2], glow * (150 + 90 * (1 - warm[idx])))
        frame[..., 3] = np.maximum(frame[..., 3], glow * 255)

    def fly(idx: int, age: float) -> tuple[float, float]:
        """자리 = 시작점 + 뻗어 나간 거리 + 중력. 뒤로 갈수록 느려진다(공기 저항)."""
        travel = (1.0 - math.exp(-3.2 * age)) / (1.0 - math.exp(-3.2))
        return (cell / 2 + math.cos(angle[idx]) * speed[idx] * reach * travel,
                cell / 2 + math.sin(angle[idx]) * speed[idx] * reach * travel
                + 0.42 * reach * age * age)

    for step in range(BURST_FRAMES):
        age = step / (BURST_FRAMES - 1)
        frame = np.zeros((cell, cell, 4), np.float32)
        for idx in range(sparks):
            if age > life[idx]:
                continue
            fade = max(0.0, 1.0 - (age / life[idx]) ** 1.7)
            twinkle = 0.65 + 0.35 * math.sin(step * 2.1 + idx)
            power = fade * twinkle * brightness
            if power <= 0.01:
                continue
            px, py = fly(idx, age)
            place(frame, px, py, power, idx)
            # 짧은 꼬리 — 점만 찍으면 '떠 있는 점'이지 날아가는 불꽃으로 안 보인다
            for back, dim in ((0.035, 0.55), (0.070, 0.25)):
                if age - back <= 0:
                    break
                tx, ty = fly(idx, age - back)
                place(frame, tx, ty, power * dim, idx)
        sheet[step * cell:(step + 1) * cell] = np.clip(frame, 0, 255).astype(np.uint8)

    name = f"fx_{tag}_fw.png"
    Image.fromarray(sheet).save(folder / name)
    return name
