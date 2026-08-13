소개 사이트(`landing/`)는 **git push 로 자동 배포되지 않는다.** Vercel 명령줄 도구로 직접 올려야 하고, `--prod` 를 붙이는 자리에 따라 운영이 아니라 미리보기에만 올라간다.

무슨 일이 있었나 (2026-08-13, v0.3.0 배포):
인수인계 문서 v1.0 에 **"소개 사이트(Vercel)는 `landing/` 폴더가 자동 배포된다 —
`git push` 하면 `landing/guide.html` 이 따라 올라간다"** 고 적혀 있었다. 그대로 믿고
`git push` 만 한 뒤 사이트를 열어 보니 **옛 설명서 그대로**였다.

    로컬 landing/guide.html      21,477 바이트 (8장 화면비 있음)
    사이트가 주는 /guide         16,156 바이트 (8장 없음)

`vercel ls moviefit-studio` 로 확인하니 **가장 최근 배포가 23시간 전**이었고, 지난 배포들의
소요 시간이 전부 **1초**였다. 깃 연동 빌드라면 20~40초가 걸린다(같은 계정의 다른 프로젝트가
그렇다). 1초는 **이미 만들어진 파일을 그대로 올리는 명령줄 배포**의 지문이다.

실제 구조: `landing/` 안에 `.vercel/project.json` 이 있다. 즉 **저장소 전체가 아니라
`landing/` 폴더 하나가 Vercel 프로젝트로 연결**되어 있고, 깃 연동은 걸려 있지 않다.

올리는 방법:

    vercel deploy --prod --cwd landing

`--cwd` 를 앞에 두면(`vercel --cwd landing --prod --yes`) **미리보기 주소로만 올라간다.**
CLI 가 마지막에 "Promote to production: vercel deploy --prod --cwd landing" 이라고
알려 주는데, 이 줄을 놓치면 올렸다고 믿고 끝낸다. 운영에 올라가면 출력에
`Production  https://...` 와 `Aliased  https://moviefit-studio.vercel.app` 두 줄이 같이 나온다.

확인하는 방법 (이것 없이 완료라고 말하지 말 것):

    python -c "import urllib.request; t=urllib.request.urlopen('https://moviefit-studio.vercel.app/guide').read().decode('utf-8'); print(len(t))"
    # 로컬 landing/guide.html 의 글자 수와 같아야 한다

첫 페이지의 내려받기 단추는 `releases/latest/download/MovieFitStudio-Setup.exe` 를 가리키므로
**버전을 손으로 고칠 필요가 없다.** 릴리스를 만들면 자동으로 새것을 가리킨다
(`gh api repos/.../releases/latest` 의 `tag_name` 으로 확인).

왜 중요한가: 배포는 "명령이 성공했다"가 아니라 **"사용자가 여는 주소에서 새것이 보인다"**
로만 확인된다. 이번에는 명령을 아예 실행하지 않았는데도 문서를 믿고 넘어갈 뻔했다.
[[test-must-target-the-right-server]] 와 같은 뿌리다 — 그쪽은 검사할 서버를 착각하는 것,
이쪽은 배포됐다고 착각하는 것이다.
