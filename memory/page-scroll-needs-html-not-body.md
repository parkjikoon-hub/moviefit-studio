긴 페이지가 안 굴러갈 때는 `body` 가 아니라 **`html` 을 풀어야 한다.** 그리고 `body` 에까지 `overflow` 를 주면 이번에는 안에 붙어 있던 띠(`position: sticky`)가 떨어진다. 한쪽을 고치면 다른 쪽이 깨지는 짝이다.

무슨 일이 있었나 (2026-08-14):
사용자가 "사용설명서에서 스크롤이 안 된다"고 알려 왔다. 그런데 **목차를 누르면 그 장으로 내려가긴 했다.**

    style.css :  html, body { height: 100%; overflow: hidden; }   ← 작업 화면이 밀리지 않게
    guide.css :  .guide-page { overflow: auto; height: auto; }    ← body 만 풀어 줌

`html` 이 막힌 채로 남아 있었다. 목차 클릭이 되는 이유는 **프로그램이 강제로 옮기는 것**이라
`overflow: hidden` 이어도 동작하기 때문이다. 사람이 굴리는 것(휠·스크롤바)만 막힌다.
이 차이 때문에 "반은 되니까 스크롤은 되는 것"으로 착각하기 쉽다.

## 두 번째 함정 — body 를 풀면 붙어 있던 띠가 떨어진다

`html` 을 풀면서 `body` 에도 `overflow: auto` 를 남겨 두었더니, 이번에는 위쪽 띠가
따라오지 않고 함께 밀려 올라갔다.

이유: `overflow` 를 준 요소는 '스크롤 상자'가 된다. `body` 가 스크롤 상자가 되었지만
실제로 구르는 것은 `html` 이므로, body 의 스크롤 상자는 한 번도 움직이지 않는다.
그 안의 `position: sticky` 는 **자기가 든 스크롤 상자**를 기준으로 붙으므로,
움직이지 않는 상자에 붙어 있다가 내용과 함께 떠내려간다.

    html        { overflow: auto;    height: auto; }   ← 여기서만 구른다
    .guide-page { overflow: visible; height: auto; }   ← body 는 막힌 것만 푼다

## 왜 중요한가

둘 다 **오류가 나지 않는다.** 콘솔에 아무것도 안 찍히고 페이지는 멀쩡히 그려진다.
그리고 자동 점검으로도 안 잡혔다 — 기존 화면 점검은 설명서가 **열리는지**와
**글자가 있는지**만 보았지, **굴러가는지**는 보지 않았기 때문이다.

그래서 점검을 이렇게 만들었다 (`scratchpad` 가 아니라 실제로 재는 방식):

- `page.mouse.wheel()` 로 굴린 뒤 `window.scrollY` 가 실제로 변하는지
- 위로도 굴러가는지 (한 방향만 되는 경우가 있다)
- 내려간 뒤에도 위쪽 띠가 화면에 남아 있는지 (`getBoundingClientRect().top`)

"열린다"와 "쓸 수 있다"는 다르다. 같은 뿌리: [[verify-ui-by-actually-clicking]]

관련: 설치본은 자기 폴더의 화면 파일 사본을 쓴다. 저장소를 고쳐도 8765 에는 반영되지
않으므로, 사용자가 "아직 안 된다"고 할 때는 **어느 서버를 보고 있는지 먼저 확인**한다
([[test-must-target-the-right-server]]). 브라우저 캐시 때문에 Ctrl+F5 도 필요하다.
