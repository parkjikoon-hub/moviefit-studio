"""내가 가진 대본에 **시간을 붙인다** (강제정렬, Phase 6 단계 6).

## 무엇을 하는가

이미 말소리가 든 영상이 있고, 그 영상에서 무슨 말을 하는지 **정확한 대본**을
가지고 있을 때 쓴다. 음성인식은 받아쓰기를 틀리지만 **언제 말했는지**는 꽤 잘
맞힌다. 그래서 인식 결과는 시각만 빌려 쓰고 글자는 내 대본을 쓴다.

    내 대본  ──┐
                ├─→ 글자 단위로 대조(difflib) ─→ 대본의 각 어절에 시각을 붙임
    인식 단어 ──┘                                        │
                                                          ▼
                                    subtitles.split_into_segments(그 어절 목록)
                                                ↑ 이미 있는 함수를 그대로 쓴다

여기서 만들어 내는 것은 `[{"word":…, "start":…, "end":…}]` 뿐이다. 문장 나누기,
글자수 제한, 사용자 사전은 그 뒤에 붙어 있는 기존 코드가 전부 처리한다.

## 정직하게 말해야 하는 것

대본에 "2024년"이라고 쓰고 음성인식이 "이천이십사 년"이라고 적으면 글자가 맞지
않아 짝을 찾지 못한다. 영어(AI ↔ 에이아이)도 같다. 그런 구간은 앞뒤로 짝이 맞은
지점 사이를 글자 수 비례로 나눠 채우는데, **그 줄의 시각은 짐작한 값이다.**
그래서 어절마다 `guessed` 를 달아 두고, 화면에서 그 줄만 따로 표시해 사용자가
두드려 맞추기로 고칠 수 있게 한다. "완전 자동"이라고 말해서는 안 된다.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# 대조할 때 지우는 글자 — 공백과 문장부호. 남는 것은 '소리 나는 글자'뿐이다.
_STRIP = re.compile(r"[\s.,!?~…·:;\"'`^*()\[\]{}<>/\\|_+=\-—–]+")


class AlignError(Exception):
    """대본에 시간을 붙이지 못했다. 메시지는 사용자에게 그대로 보여 줄 한국어다."""


def _normalize(text: str) -> str:
    """대조용으로 글자를 다듬는다. 한글은 그대로, 영문은 소문자로."""
    return _STRIP.sub("", str(text or "")).lower()


def split_words(script: str) -> list[str]:
    """대본을 어절(띄어쓰기 단위)로 나눈다. 줄바꿈은 어절 경계로만 쓴다."""
    return [w for w in re.split(r"\s+", str(script or "").strip()) if w]


def align_script(
    script: str,
    words: list[dict[str, Any]],
    *,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    """대본의 어절마다 시각을 붙여 돌려준다.

    인자:
        script   사용자가 붙여넣은 대본 (줄바꿈·문장부호 그대로)
        words    음성인식이 준 단어 목록 [{"word","start","end"}, …]
        duration 영상 전체 길이 (마지막 어절의 끝을 정할 때만 쓴다)

    돌려주는 값: [{"word", "start", "end", "guessed"}, …]
        guessed=True 면 **짝을 못 찾아 앞뒤 사이를 나눠 짐작한 시각**이다.
    """
    script_words = split_words(script)
    if not script_words:
        raise AlignError("대본이 비어 있습니다. 붙여넣은 글이 있는지 확인해 주세요.")
    if not words:
        raise AlignError(
            "영상에서 말소리를 찾지 못했습니다. 먼저 [자막 자동 생성]을 한 번 돌려 주세요."
        )

    # ① 양쪽을 '소리 나는 글자'만 남긴 한 줄로 펴고, 글자마다 원래 자리를 기억해 둔다.
    script_chars: list[str] = []
    script_owner: list[int] = []          # 이 글자가 몇 번째 어절의 것인가
    for index, word in enumerate(script_words):
        for ch in _normalize(word):
            script_chars.append(ch)
            script_owner.append(index)

    heard_chars: list[str] = []
    heard_owner: list[int] = []           # 이 글자가 몇 번째 인식 단어의 것인가
    for index, item in enumerate(words):
        for ch in _normalize(item.get("word", "")):
            heard_chars.append(ch)
            heard_owner.append(index)

    if not script_chars:
        raise AlignError("대본에 글자가 없습니다.")
    if not heard_chars:
        raise AlignError("음성인식 결과에 글자가 없습니다.")

    # ② 같은 부분을 찾는다. autojunk=False 를 반드시 줘야 한다 —
    #    기본값은 자주 나오는 글자를 '잡동사니'로 보고 빼 버리는데, 한글은 조사('은','는')가
    #    아주 자주 나와서 그대로 두면 대조가 통째로 어긋난다.
    matcher = difflib.SequenceMatcher(None, script_chars, heard_chars, autojunk=False)

    # ③ 대본 어절마다 "가장 먼저 짝이 맞은 인식 단어"를 찾는다.
    anchor: dict[int, int] = {}
    for s_start, h_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            s_index = script_owner[s_start + offset]
            if s_index not in anchor:
                anchor[s_index] = heard_owner[h_start + offset]

    total_seconds = float(duration or 0.0)
    if words:
        total_seconds = max(total_seconds, float(words[-1].get("end") or 0.0))

    # ④ 짝이 맞은 어절에는 그 단어의 시작 시각을, 못 맞은 구간은 앞뒤 사이를
    #    글자 수에 비례해 나눠 채운다.
    starts: list[float | None] = [None] * len(script_words)
    for index, word_index in anchor.items():
        starts[index] = float(words[word_index].get("start") or 0.0)

    # 맨 앞이 비어 있으면 0초에서 시작한 것으로 본다.
    if starts[0] is None:
        starts[0] = 0.0
    # 맨 뒤가 비어 있으면 마지막으로 아는 시각 뒤에 붙인다.
    if starts[-1] is None:
        known = [s for s in starts if s is not None]
        starts[-1] = max(known) if known else 0.0

    guessed = [False] * len(script_words)
    index = 0
    while index < len(script_words):
        if starts[index] is not None:
            index += 1
            continue
        # 비어 있는 구간 [left+1 … right-1] 을 찾는다.
        left = index - 1
        right = index
        while right < len(script_words) and starts[right] is None:
            right += 1
        span_start = float(starts[left])          # type: ignore[arg-type]
        span_end = float(starts[right]) if right < len(script_words) else total_seconds
        if span_end <= span_start:
            span_end = span_start + 0.001

        lengths = [max(1, len(_normalize(script_words[i]))) for i in range(left + 1, right)]
        total_len = sum(lengths) or 1
        clock = span_start
        for offset, i in enumerate(range(left + 1, right)):
            starts[i] = clock
            guessed[i] = True
            clock += (span_end - span_start) * lengths[offset] / total_len
        index = right

    # ⑤ 어절의 끝 시각은 '다음 어절의 시작'이다. 마지막은 영상 끝까지.
    result: list[dict[str, Any]] = []
    for i, word in enumerate(script_words):
        start = float(starts[i] or 0.0)
        if i + 1 < len(script_words):
            end = float(starts[i + 1] or start)
        else:
            end = max(total_seconds, start + 0.3)
        if end <= start:
            end = start + 0.05
        result.append({"word": word, "start": round(start, 3), "end": round(end, 3),
                       "guessed": guessed[i]})

    return result


def mark_guessed_segments(
    segments: list[dict[str, Any]], aligned: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """자막 줄마다 "짐작한 어절이 들어 있는가"를 표시한다.

    화면은 이 표시를 보고 그 줄만 다르게 그린다. 사용자는 그 줄만 두드려 맞추기로
    고치면 되고, 잘 맞은 줄은 손대지 않아도 된다.
    """
    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or 0.0)
        inside = [w for w in aligned if start - 0.001 <= float(w["start"]) < end + 0.001]
        segment["guessed"] = any(w.get("guessed") for w in inside) if inside else False
    return segments
