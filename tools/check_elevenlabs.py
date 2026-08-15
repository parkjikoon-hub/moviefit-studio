"""ElevenLabs 계정 점검 — 내 키로 무엇을 할 수 있는지 직접 확인한다.

**이 도구는 키를 화면에 찍지 않고, 어디에도 저장하지 않는다.**
입력한 키는 이 프로그램이 도는 동안만 메모리에 있다가 끝나면 사라진다.

무엇을 알려 주는가:
  ① 키가 맞는가
  ② 어느 요금제인가 (무료 / 유료)
  ③ 이번 달에 글자를 얼마나 썼고 얼마나 남았는가
  ④ **목소리 라이브러리에서 고른 목소리를 실제로 쓸 수 있는가**
     ← 이것이 핵심이다. 무료 요금제는 못 쓴다고 알려져 있는데, 직접 확인한다.

사용법 (명령창에서):
    python tools/check_elevenlabs.py

    키를 물어보면 붙여넣고 Enter. 입력한 글자는 화면에 보이지 않는다.
    (키는 ElevenLabs 웹사이트 → 오른쪽 위 프로필 → API Keys 에서 만든다)

주의: ④를 확인할 때 아주 짧은 소리("안녕하세요" 5글자)를 실제로 만들어 본다.
      요금제 글자 수에서 5자가 빠진다. 그보다 정확히 아는 방법이 없다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.elevenlabs.io/v1"

# 사용자가 고른 목소리 라이브러리 ID (2026-08-14 기준, 중복 제외 19개)
WANTED = [
    "sf8Bpb1IU97NI9BHSMRf", "U1cJYS4EdbaHmfR7YzHd", "zgDzx5jLLCqEp6Fl7Kl7",
    "uyVNoMrnUku1dZyVEXwD", "7oLyBHyhxAjrctX6ZQlw", "CxErO97xpQgQXYmapDKX",
    "s07IwTCOrCDCaETjUVjx", "fAgkbajYljImBTPFR28u", "n2fbxG88jqAoaVPUy3IG",
    "dJlwSfdSqMaQjm3NSl3B", "8yL2rVx40vjDeu5pTbg6", "3MTvEr8xCMCC2mL9ujrI",
    "B8rl62CpT9zOQ7RC3Mdl", "KlstlYt9VVf3zgie2Oht", "jhRwPcHZjcfER84hHhYm",
    "1KYji6JbtyM9EQsKflMG", "5DWGv3VDkihNUcbvaonB", "uD0jH1cfRqteeku18ODi",
    "6yp5xWNuHEXOVkwW5Ghz",
]


def call(path: str, key: str, *, data: bytes | None = None, raw: bool = False):
    """API 를 부른다 → (성공여부, 결과 또는 오류설명).

    키는 헤더에만 넣고 어떤 경우에도 화면이나 오류 메시지에 넣지 않는다.
    """
    req = urllib.request.Request(f"{API}{path}", data=data)
    req.add_header("xi-api-key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
            return True, body if raw else json.loads(body.decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(text).get("detail")
            if isinstance(detail, dict):
                text = f"{detail.get('status', '')} — {detail.get('message', '')}"
            elif detail:
                text = str(detail)
        except Exception:
            pass
        return False, f"HTTP {exc.code}: {text[:200]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("=" * 66)
    print("  ElevenLabs 계정 점검")
    print("=" * 66)
    print("키를 붙여넣고 Enter 를 누르세요. 입력한 글자는 화면에 보이지 않습니다.")
    print("(키는 저장되지 않고, 이 창을 닫으면 사라집니다)\n")

    import getpass

    try:
        key = getpass.getpass("ElevenLabs API 키: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n취소했습니다.")
        return 1
    if not key:
        print("키가 비어 있습니다.")
        return 1

    # ① 키가 맞는가 + ② 요금제 + ③ 남은 글자
    print("\n[1/3] 키와 요금제를 확인합니다…")
    ok, sub = call("/user/subscription", key)
    if not ok:
        print(f"  ✗ 키를 확인하지 못했습니다.\n    {sub}")
        print("\n  키를 다시 만들어 보시거나, 앞뒤 빈칸이 섞이지 않았는지 확인해 주세요.")
        return 1

    tier = sub.get("tier", "?")
    used = sub.get("character_count", 0)
    limit = sub.get("character_limit", 0)
    paid = str(tier).lower() not in ("free", "starter_free", "")
    print(f"  ✓ 키가 맞습니다.")
    print(f"    요금제      : {tier}   ({'유료' if paid else '무료'})")
    print(f"    이번 달 사용 : {used:,} / {limit:,} 자   (남은 글자 {max(0, limit - used):,}자)")
    if limit:
        print(f"    참고        : 10분짜리 나레이션 대본이 대략 3,000자입니다"
              f" → 약 {max(0, limit - used) // 3000}편 분량")

    # ④ 내 계정에 담긴 목소리
    print("\n[2/3] 내 계정에 담긴 목소리를 봅니다…")
    ok, data = call("/voices", key)
    if not ok:
        print(f"  ✗ 목소리 목록을 받지 못했습니다.\n    {data}")
        return 1
    mine = {v["voice_id"]: v.get("name", "?") for v in data.get("voices", [])}
    print(f"  ✓ 계정에 담긴 목소리 {len(mine)}개")

    have = [v for v in WANTED if v in mine]
    missing = [v for v in WANTED if v not in mine]
    print(f"    고르신 19개 중 이미 담긴 것 : {len(have)}개")
    print(f"    아직 안 담긴 것            : {len(missing)}개")
    for v in have[:5]:
        print(f"      담김: {mine[v]}  ({v[:8]}…)")

    # ⑤ 실제로 소리가 나오는가 — 이것만이 확실한 증거다
    print("\n[3/3] 고르신 목소리로 **실제 소리**를 만들어 봅니다 (5글자만 씁니다)…")
    target = (have or missing)[0]
    where = "계정에 담긴" if target in mine else "라이브러리에만 있는"
    body = json.dumps({
        "text": "안녕하세요",
        "model_id": "eleven_multilingual_v2",
    }).encode()
    ok, res = call(f"/text-to-speech/{target}", key, data=body, raw=True)
    if ok:
        print(f"  ✓ 소리가 나왔습니다! ({where} 목소리, {len(res):,}바이트)")
        print("    → 이 요금제로 고르신 목소리를 쓸 수 있습니다. 앱에 붙이면 됩니다.")
        verdict = "사용 가능"
    else:
        print(f"  ✗ 소리가 나오지 않았습니다 ({where} 목소리)")
        print(f"    {res}")
        print("    → 요금제 제한일 가능성이 큽니다. 위 메시지를 그대로 알려 주세요.")
        verdict = "사용 불가"

    print("\n" + "=" * 66)
    print(f"  결론: 요금제 {tier} / 고르신 목소리 {verdict}")
    print("=" * 66)
    print("\n이 화면을 그대로(키는 안 보입니다) 알려 주시면 다음 단계를 정하겠습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
