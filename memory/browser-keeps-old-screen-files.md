화면 파일(app.js·style.css)에 `Cache-Control` 표시가 없으면 **브라우저는 서버에 묻지도 않고 옛 파일을 며칠씩 쓴다.** 새 판을 설치해도 사용자 눈에는 아무것도 안 바뀐다. 서버는 `no-cache` 를 붙이고, index.html 은 `app.js?v=…` 처럼 **주소를 한 번 바꿔** 이미 쌓인 옛 기억을 버리게 한다.

무슨 일이 있었나 (2026-11-04, 타임라인 손질 작업):
점검 32개가 다 통과한 뒤 크롬으로 눈 확인을 하려는데 손잡이가 여전히 7px 이었다.
페이지 안에서 `typeof startBarDrag` 가 `undefined`. 오전에 받아 둔 **옛 app.js** 를 쓰고 있었다.
서버 머리글에 `Cache-Control` 이 없고 `Last-Modified` 만 있었다.

    python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8766/app.js').headers.get('Cache-Control'))"
    → None

표시가 없으면 브라우저는 "마지막으로 고친 날부터 지금까지 시간의 10%" 동안 파일을 그냥 쓴다.
8월에 설치하고 11월에 열었다면 **8일 넘게** 옛 화면이 나온다. 서비스 워커가 "서버 먼저"
방식이어도 소용없다. 서비스 워커의 `fetch()` 도 이 브라우저 기억을 거친다.

서버 기록으로 본 크롬의 행동: **페이지(index.html)는 매번 서버에 확인했고(304), 그 안의 app.js 는
확인 없이 옛것을 썼다.** 그래서 index.html 이 새 주소(`?v=20261104`)를 부르면 반드시 새 파일이 온다.

고친 것:
- `app/server.py` 의 `NoCacheStaticFiles`: 화면 파일 전부에 `Cache-Control: no-cache`.
  바뀌지 않았으면 서버가 304 만 돌려주니 느려지지 않는다
- `app/static/index.html`: `/style.css?v=20261104`, `/app.js?v=20261104`. **한 번만** 바꾸면 된다.
  이제 서버가 표시를 붙이므로 다음 판부터는 그대로 둬도 새 파일이 간다
- `app/static/sw.js`: `CACHE` v3, 받을 때 `{cache: "no-cache"}`, 설치할 때 `{cache: "reload"}`

## 하지 말 것: 서비스 워커 활성화 안에서 화면을 새로 고치게 하기

처음에는 `activate` 안에서 `clients.matchAll()` → `client.navigate()` 로 열린 화면을 새로
고치고 그 끝을 `await` 했다. **크롬 탭이 통째로 멈췄다** (확장 도구가 "아직 이동 중"이라며 접근 불가).
활성화가 끝나기 전에는 화면 요청이 새 워커에 오지 않는데, 활성화가 그 요청을 기다렸기 때문이다.
서로를 기다린다. 서버 기록에 새로 고침 요청이 끝내 안 왔다. 탭을 닫으니 풀렸다.

확인하는 법:
- `tests/timeline_ui_test.py` 0번이 머리글을 본다
- 사람 눈으로는 **강력 새로고침(Ctrl+F5) 없이** 보통으로 열어서 새 기능이 보이는지 본다.
  Ctrl+F5 를 누르면 이 문제가 가려진다

중요한 이유: Playwright 점검은 매번 빈 브라우저로 시작하므로 이 문제를 **절대 못 잡는다.**
"점검 통과"와 "사용자 화면이 바뀜" 사이에 이런 틈이 있다 ([[eyes-catch-what-gauges-miss]]).
