# landing/ — MovieFit Studio 소개 페이지

빌드 도구 없이 그대로 배포되는 정적 페이지입니다 (`index.html` 한 장 + `icons/`).

## Vercel 배포 방법

1. [vercel.com](https://vercel.com)에 GitHub 계정으로 로그인하고 **Add New… → Project**를 누릅니다.
2. `moviefit-studio` 저장소를 선택하고 **Import**를 누릅니다.
3. **Framework Preset**을 `Other`로 선택합니다.
4. **Root Directory**를 `landing` 으로 지정합니다 (Edit 버튼 → landing 폴더 선택).
5. **Build Command**와 **Install Command**는 비워 둡니다 (Override 끄기). **Output Directory**도 비워 두면 됩니다.
6. **Deploy**를 누르면 1분 안에 주소가 발급됩니다.

이후 `landing/` 안의 파일을 고쳐서 GitHub에 올리면 자동으로 다시 배포됩니다.
페이지 안에서 쓰는 아이콘은 `landing/icons/`에 복사해 둔 것이며, 앱 아이콘(`app/static/icons/`)을 바꾸면 이 폴더에도 다시 복사해 주세요.
