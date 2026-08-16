"""한국부동산원 R-ONE 수집기 — 공실률·순영업소득·투자수익률.

『돈공부』 3.A.3 §판정 6이 짚은 자리다 —
**안민석이 103쪽에서 쓴 「순영업소득」을 정부 통계가 분기마다 공표하고 있다.**
그러면 판정이 「문헌이 잴 수 없는 것을 뺐다」가 아니라 **「있는 자를 안 썼다」**로 좁혀진다.

⚠⚠ **ECOS와 달리 시험키가 없다. 키가 반드시 필요하다.**
    발급: https://www.reb.or.kr/r-one (무료)
    실측 2026-08-16 — 키 없이 호출하면 ERROR-290을 돌려준다.

⚠ **표 ID(STATBL_ID)를 코드에 박지 않았다.**
    키가 없어 목록을 조회할 수 없었고, **확인하지 못한 값을 적지 않는 것**이
    이 프로젝트의 규약이다. 대신 실행 시 목록 API에서 키워드로 찾는다.
    한 번 찾으면 `cache/reb_tables.json`에 남아 다음부터는 바로 쓴다.

⚠⚠ **저작권 주의** — 한국부동산원은 「공공기관」이라 저작권법 제24조의2 제1항의
    자유이용 대상이 **아니다**(자유이용은 국가·지방자치단체 한정, 공공기관은 제2항의
    시책 대상일 뿐). 그래서 이 repo는 **수집물을 배포하지 않는다.**
    이용자가 자기 키로 받고, 이용조건은 기관 것을 따른다. DISCLAIMER.md §5.

    REB_API_KEY=xxx python3 data/collect_reb.py
    REB_API_KEY=xxx python3 data/collect_reb.py --list 임대동향

의존 없음(stdlib only).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.reb.or.kr/r-one/openapi"
OUT_DIR = Path(__file__).resolve().parent.parent / "cache"

# 찾을 통계 — ⚠ 이름으로 찾는다. ID를 추측해 박지 않는다.
#
# ⚠⚠ 2026-08-16 실측으로 키워드를 고쳤다.
#    처음엔 "상업용부동산"으로 잡았는데 **R-ONE에 그런 이름의 표가 0건**이고,
#    실제 이름은 "임대동향 ..._오피스/중대형 상가/소규모 상가/집합 상가"였다.
#    ID를 안 박고 이름으로 찾게 한 설계가 여기서 값을 했다.
#
# 유형(property_type)을 붙여 부른다 — 오피스텔과 상가는 다른 물건이다.
PROPERTY_TYPES = ("오피스", "중대형 상가", "소규모 상가", "집합 상가")

TARGETS = {
    "noi": {
        "keywords": ["임대동향", "순영업소득"],
        "want": "순영업소득(분기·유형별)",
        "why": "3.A.3 §판정 6 — 문헌이 「구하기 어렵다」던 값을 기관이 분기마다 공표한다",
    },
    "income_yield": {
        "keywords": ["임대동향", "소득수익률"],
        "want": "소득수익률(분기/연간)",
        "why": "⚠ 어느 비용까지 뺀 값인지 조사 개요 확인 필요(§판정 6 미해결)",
    },
    "vacancy": {
        "keywords": ["임대동향", "공실률"],
        "want": "공실률(분기·유형별)",
        "why": "3.A.3 §판정 3 — 공실을 0으로 두지 않는다",
    },
    "officetel_conversion": {
        "keywords": ["오피스텔", "전월세전환율"],
        "want": "오피스텔 전월세 전환율(월간)",
        "why": "보증금·월세 환산의 시장 기준선",
    },
}

def _key() -> str:
    k = os.environ.get("REB_API_KEY", "").strip()
    if not k:
        raise SystemExit(
            "REB_API_KEY가 없습니다.\n"
            "  ⚠ R-ONE은 ECOS와 달리 시험키가 없습니다 — 키가 반드시 필요합니다.\n"
            "  발급(무료): https://www.reb.or.kr/r-one\n"
            "  키 없이도 계산 엔진은 돕니다. 공실률·순영업소득만 직접 입력하세요."
        )
    return k


def _call(path: str, **params) -> dict:
    """R-ONE은 오류도 HTTP 200으로 준다 — ECOS와 같은 함정이다."""
    params = {"KEY": _key(), "Type": "json", **params}
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        payload = json.load(r)
    if isinstance(payload, dict) and "RESULT" in payload:
        res = payload["RESULT"]
        raise RuntimeError(f"{res.get('CODE')}: {res.get('MESSAGE', '')[:80]}")
    return payload


def _rows(payload: dict) -> list[dict]:
    """R-ONE 응답은 [{head:[...]}, {row:[...]}] 구조다(실측 2026-08-16)."""
    out: list[dict] = []
    for block in payload.values() if isinstance(payload, dict) else []:
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict) and "row" in item:
                    out.extend(item["row"])
    return out


def list_tables(keyword: str = "") -> list[dict]:
    """통계표 목록. 키워드로 거른다 — ID를 모르니 이름으로 찾는다."""
    rows_all: list[dict] = []
    for page in range(1, 9):              # 738개 · 100씩
        payload = _call("SttsApiTbl.do", pIndex=page, pSize=100)
        got = _rows(payload)
        if not got:
            break
        rows_all.extend(got)
    rows = rows_all
    if keyword:
        rows = [r for r in rows if keyword in str(r.get("STATBL_NM", ""))]
    return rows


def find_target(name: str) -> list[dict]:
    """TARGETS의 키워드를 **전부** 포함하는 표를 찾는다."""
    kws = TARGETS[name]["keywords"]
    hits = list_tables(kws[0])
    return [r for r in hits if all(k in str(r.get("STATBL_NM", "")) for k in kws)]


def fetch_table(statbl_id: str, cycle: str = "QY", n: int = 100) -> list[dict]:
    """통계표 데이터. cycle: MM(월) · QY(분기) · YY(연)."""
    payload = _call("SttsApiTblData.do", STATBL_ID=statbl_id,
                    DTACYCLE_CD=cycle, pIndex=1, pSize=n)
    return _rows(payload)


def collect() -> dict:
    """대상 통계를 찾아 받는다. 못 찾으면 **못 찾았다고 적는다.**"""
    import datetime as dt

    snap = {
        "collected_at": dt.date.today().isoformat(),
        "source": "한국부동산원 R-ONE",
        "license_note": "공공기관 저작물 — 자유이용 대상 아님. 이용조건은 기관 것을 따를 것",
        "tables": {}, "warnings": [],
    }
    for name, spec in TARGETS.items():
        try:
            found = find_target(name)
            if not found:
                snap["warnings"].append(
                    f"{name}: '{' + '.join(spec['keywords'])}'로 표를 찾지 못했습니다. "
                    f"--list 로 목록을 확인하세요."
                )
                continue
            # 유형별로 표가 갈린다 — 최신 것 하나씩 잡는다
            picked = {}
            for t in found:
                nm = str(t.get("STATBL_NM", ""))
                for pt in PROPERTY_TYPES:
                    if nm.endswith("_" + pt) and pt not in picked:
                        picked[pt] = t
            if not picked:
                picked = {"전체": found[0]}
            snap["tables"][name] = {
                "want": spec["want"], "why": spec["why"], "by_type": {},
            }
            for pt, t in picked.items():
                tid = t.get("STATBL_ID")
                cyc = "MM" if str(t.get("DTACYCLE_CD", "")).startswith("MM") else "QY"
                snap["tables"][name]["by_type"][pt] = {
                    "statbl_id": tid, "name": t.get("STATBL_NM"),
                    "cycle": cyc, "rows": fetch_table(tid, cyc, n=40),
                }
        except Exception as e:
            snap["warnings"].append(f"{name}: {e}")
    return snap


def main(argv: list[str]) -> int:
    if "--list" in argv:
        kw = argv[argv.index("--list") + 1] if len(argv) > argv.index("--list") + 1 else ""
        for r in list_tables(kw)[:40]:
            print(f"  {r.get('STATBL_ID'):<18} {str(r.get('STATBL_NM'))[:56]}")
        return 0

    snap = collect()
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "reb.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"R-ONE 수집 — {snap['collected_at']}")
    for name, t in snap["tables"].items():
        print(f"  ■ {name} — {t['want']}")
        for pt, d in t.get("by_type", {}).items():
            print(f"     {pt:<12} {len(d['rows']):>4}행  [{d['statbl_id']}]  {d['name'][:40]}")
    for w in snap["warnings"]:
        print(f"  ⚠ {w}")
    print(f"\n→ {path}  (⚠ .gitignore — 재배포하지 않는다)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
