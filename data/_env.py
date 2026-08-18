"""`.env`에 적어 둔 API 키를 환경변수로 올린다 — 의존 없음(stdlib only).

**왜 파일에 두는가.** 키를 명령줄에 적으면(`ECOS_API_KEY=xxx python3 ...`)
셸 기록에 남는다. 소스에 적으면 커밋된다. `.env`는 **`.gitignore`에 걸려 있고
권한이 600**이라 둘 다 피한다.

⚠ **이미 셸에 있는 값은 덮지 않는다** — 그때그때 다른 키로 시험하려는
의도를 파일이 가로채면 안 된다. 셸 지정이 파일보다 세다.

⚠ 이 로더는 따옴표 벗기기와 주석 건너뛰기만 한다. 변수 치환(`$FOO`)이나
여러 줄 값은 지원하지 않는다 — 키 세 개를 담는 데 그 이상은 필요 없다.
"""

from __future__ import annotations

import os
from pathlib import Path

# 레포 루트의 .env — 이 파일이 data/ 안에 있으므로 한 단계 위다
DEFAULT = Path(__file__).resolve().parent.parent / ".env"


def load(path: Path | None = None) -> list[str]:
    """`.env`를 읽어 환경변수로 올리고, **올린 키 이름들**을 돌려준다.

    파일이 없으면 빈 목록. 키 없이도 도는 수집기(ECOS 시험키)를 막지 않는다.
    """
    p = path or DEFAULT
    if not p.exists():
        return []

    loaded = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        # 값에 붙은 따옴표를 벗긴다 — .env는 따옴표가 있어도 없어도 같은 뜻이다
        value = value.strip().strip('"').strip("'")
        if sep and name and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
