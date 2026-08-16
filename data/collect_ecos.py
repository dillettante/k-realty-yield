"""한국은행 ECOS 수집기 — 금리·물가.

bring-your-own-data: **수집물은 repo에 들어가지 않는다**(.gitignore).
이용자가 자기 키로 직접 받는다. 공공기관 저작물 재배포 문제를 그렇게 피한다
(저작권법 제24조의2 ①의 자유이용 대상은
국가·지자체 한정이고 공공기관은 아니다).

키 없이도 동작한다 — ECOS는 시험키 `sample`로 **10건까지** 준다.
    실측 2026-08-16: 기준금리·주택담보대출금리 둘 다 정상 응답.
키를 넣으면 제한이 풀린다. 발급: https://ecos.bok.or.kr (무료)

    python3 data/collect_ecos.py                 # 시험키, 최근 10개월
    ECOS_API_KEY=xxx python3 data/collect_ecos.py

의존 없음(stdlib only).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
OUT_DIR = Path(__file__).resolve().parent.parent / "cache"

# 실측으로 확인한 계열만 둔다(2026-08-16). 추측한 코드는 넣지 않는다.
SERIES = {
    "base_rate": {
        "name": "한국은행 기준금리",
        "stat": "722Y001", "cycle": "M", "item": "0101000",
        "note": "전월세 전환율 법정 상한이 이 값에 연동된다(주임법 §7-2·시행령 §9)",
    },
    "mortgage_rate": {
        "name": "예금은행 주택담보대출 금리(신규취급액 가중평균)",
        "stat": "121Y006", "cycle": "M", "item": "BECBLA0302",
        "note": "조달비용 r의 시장 기준선. ⚠ 개인 조건에 따라 다르다 — 기준선일 뿐이다",
    },
    "loan_avg": {
        "name": "예금은행 대출평균 금리",
        "stat": "121Y006", "cycle": "M", "item": "BECBLA01",
        "note": "보조 지표",
    },
}

SAMPLE_LIMIT = 10  # 시험키 상한


def _key() -> tuple[str, int]:
    k = os.environ.get("ECOS_API_KEY", "").strip()
    return (k, 200) if k else ("sample", SAMPLE_LIMIT)


def fetch(series: str, start: str, end: str) -> list[dict]:
    """월별 시계열을 받는다. start/end는 YYYYMM."""
    s = SERIES[series]
    key, limit = _key()
    url = f"{BASE}/{key}/json/kr/1/{limit}/{s['stat']}/{s['cycle']}/{start}/{end}/{s['item']}"
    with urllib.request.urlopen(url, timeout=30) as r:
        payload = json.load(r)
    if "RESULT" in payload:                       # ECOS는 오류도 200으로 준다
        raise RuntimeError(f"{series}: {payload['RESULT'].get('MESSAGE', '')[:80]}")
    root = payload[next(iter(payload))]
    return [
        {"time": row["TIME"], "value": float(row["DATA_VALUE"]), "unit": row.get("UNIT_NAME", "")}
        for row in root.get("row", [])
        if row.get("DATA_VALUE") not in (None, "")
    ]


# 전월세 전환율 상한 — (상한 비율, 기준금리에 적용할 값, 연산, 근거)
# ⚠⚠ 주택과 상가가 **식 자체가 다르다.** 주택은 기준금리에 더하고 상가는 곱한다.
CONVERSION_CAP = {
    "주택": (10.0, 2.0, "add",
             "주택임대차보호법 제7조의2 · 시행령 제9조(연 1할 / 기준금리 + 2%p)"),
    "상가": (12.0, 4.5, "mul",
             "상가건물 임대차보호법 제12조 · 시행령 제5조(연 1할2푼 / 기준금리 × 4.5배)"),
}


def conversion_rate_cap(base_rate: float, kind: str = "주택") -> float:
    """⭐ 전월세 전환율 법정 상한. 단위는 % (기준금리 2.75 → 2.75).

    데이터 레이어와 법령 레이어가 만나는 유일한 자리다.
    **법도 시행령도 안 고치고 금융통화위원회가 값을 움직인다.**

    ⚠⚠ 조문은 두 호 **중 낮은 비율**이라고 못 박는다 — 상한이 둘이고 작은 쪽이 이긴다.
    기준금리만 보고 계산하면 금리가 높을 때 법정 상한을 넘긴 값을 낸다.
    (주택은 기준금리 8% 초과, 상가는 2.667% 초과 구간에서 갈린다.)

    ⚠⚠ 그리고 **주택과 상가는 식이 다르다.** 상가는 더하기가 아니라 **곱하기**다.
    기준금리 2.75%면 주택 4.75% · 상가 12.0%로 **7.25%p 벌어진다.**
    유형을 안 가리고 하나만 쓰면 상가에서 크게 틀린다.

    근거: 위 `CONVERSION_CAP` · policy/constants.yaml T-임대-05·T-임대-05-상가
    """
    if kind not in CONVERSION_CAP:
        raise ValueError(f"kind는 {list(CONVERSION_CAP)} 중 하나여야 한다 — 받은 값: {kind!r}")
    ceiling, factor, op, _ = CONVERSION_CAP[kind]
    linked = base_rate + factor if op == "add" else base_rate * factor
    return min(ceiling, linked)


def collect(months: int = 10) -> dict:
    """전 계열을 받아 하나의 스냅샷으로."""
    today = dt.date.today()
    end = today.strftime("%Y%m")
    start_y, start_m = divmod((today.year * 12 + today.month - 1) - months, 12)
    start = f"{start_y}{start_m + 1:02d}"

    key, _ = _key()
    snap = {
        "collected_at": today.isoformat(),
        "source": "한국은행 ECOS",
        "key_type": "sample(시험키·10건 제한)" if key == "sample" else "user",
        "series": {},
        "derived": {},
        "warnings": [],
    }
    for name in SERIES:
        try:
            rows = fetch(name, start, end)
            snap["series"][name] = {
                "name": SERIES[name]["name"], "note": SERIES[name]["note"],
                "latest": rows[-1] if rows else None, "rows": rows,
            }
        except Exception as e:                     # 한 계열이 죽어도 나머지는 받는다
            snap["warnings"].append(f"{name}: {e}")

    base = snap["series"].get("base_rate", {}).get("latest")
    if base:
        # 주택·상가를 함께 낸다 — 식이 달라서 하나만 내면 다른 쪽이 크게 틀린다
        for kind, (ceiling, factor, op, basis) in CONVERSION_CAP.items():
            linked = base["value"] + factor if op == "add" else base["value"] * factor
            snap["derived"][f"conversion_cap_{kind}"] = {
                "value": conversion_rate_cap(base["value"], kind),
                "basis": basis,
                "layer": "L2+외부지표",
                "binding": "상한" if ceiling <= linked else "기준금리 연동분",
                "note": (f"기준금리 {base['value']}%({base['time']}) 연동분 {linked:.2f}% "
                         f"vs 상한 {ceiling}% → 낮은 쪽"),
            }
    if key == "sample":
        snap["warnings"].append(
            f"시험키로 받았습니다 — 요청당 10건 제한이라 {months}개월치만 받았습니다. "
            "ECOS_API_KEY를 넣으면 더 긴 구간을 받을 수 있습니다"
            "(collect(months=…)로 창을 넓히십시오)."
        )
    return snap


def main() -> int:
    snap = collect()
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "ecos.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"ECOS 수집 — {snap['collected_at']} · 키: {snap['key_type']}")
    for name, s in snap["series"].items():
        latest = s["latest"]
        if latest:
            print(f"  {s['name'][:34]:<36} {latest['time']}  {latest['value']}%")
    caps = {k: v for k, v in snap["derived"].items() if k.startswith("conversion_cap_")}
    if caps:
        print("\n  ⭐ 전월세 전환율 법정 상한 — ⚠ 주택과 상가는 식이 다르다")
        for k, cap in caps.items():
            print(f"     {k.split('_')[-1]}  {cap['value']:.2f}%  ({cap['binding']})")
            print(f"        {cap['note']}")
            print(f"        {cap['basis']}")
    for w in snap["warnings"]:
        print(f"  ⚠ {w}")
    print(f"\n→ {path}  (⚠ .gitignore — repo에 올리지 않는다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
