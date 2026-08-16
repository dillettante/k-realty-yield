"""시장값 층 — 수집물이 있으면 기본값으로, 없으면 조용히 비운다.

Phase 3의 완료 기준이 이 모듈이다.
  · 키 없이도 엔진이 돈다 — 수집물이 없으면 `None`이고 사용자가 넣는다.
  · 키가 있으면 기본값이 시장 실측으로 바뀐다.
  · **값이 어디서 왔는지가 항상 따라다닌다**(`MarketValue.source`).

⚠⚠ 이 모듈은 「그럴듯한 기본값」을 지어내지 않는다.
수집물이 없으면 없다고 말한다 —
**없다와 못 찾았다는 다르고, 둘 다 0이 아니다.**
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "cache"
STALE_DAYS = 45          # 월간 통계라 한 달 반이면 낡았다고 본다


@dataclass
class MarketValue:
    """시장에서 받은 값 하나. 값보다 출처와 시점이 중요하다."""

    value: float
    unit: str
    as_of: str                 # 관측 시점(YYYYMM 등)
    source: str
    collected_at: dt.date
    note: str = ""

    def is_stale(self, today: dt.date | None = None) -> bool:
        today = today or dt.date.today()
        return (today - self.collected_at).days > STALE_DAYS

    def describe(self) -> str:
        return f"{self.value}{self.unit} ({self.as_of} · {self.source})"


@dataclass
class Market:
    """수집물 스냅샷. 없는 항목은 전부 None이다."""

    mortgage_rate: MarketValue | None = None       # 조달비용 기준선
    base_rate: MarketValue | None = None
    jeonse_conversion_cap: MarketValue | None = None
    vacancy_rate: MarketValue | None = None        # R-ONE (Phase 3 후속)
    noi_yield: MarketValue | None = None           # R-ONE 소득수익률
    property_type: str = ""                        # 이 값들이 어느 물건 유형의 것인가
    warnings: list[str] = None                     # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

    @property
    def available(self) -> dict[str, MarketValue]:
        return {k: v for k, v in self.__dict__.items()
                if isinstance(v, MarketValue)}

    @property
    def missing(self) -> list[str]:
        """비어 있는 항목 — 사용자가 직접 넣어야 하는 것들."""
        return [k for k, v in self.__dict__.items()
                if v is None and k not in ("warnings", "property_type")]


def _mv(row: dict, name: str, source: str, collected: str, note: str = "") -> MarketValue:
    return MarketValue(
        value=row["value"], unit=row.get("unit", "%") or "%",
        as_of=row["time"], source=source,
        collected_at=dt.date.fromisoformat(collected), note=note,
    )


def load(cache_dir: Path | str = CACHE, property_type: str = "") -> Market:
    """수집물을 읽는다. 파일이 없으면 **빈 Market**을 돌려준다(예외 아님).

    키가 없어도 엔진이 돌아야 하기 때문이다.

    ⚠⚠ `property_type`을 반드시 넘긴다. R-ONE 임대동향조사는 **오피스·상가만**
    조사하므로, 오피스텔·아파트에 「오피스」 값을 쓰면 틀린다.
    """
    d = Path(cache_dir)
    m = Market(property_type=property_type)
    f = d / "ecos.json"
    if not f.exists():
        m.warnings.append(
            "시장 데이터가 없습니다. `python3 data/collect_ecos.py`로 받거나 "
            "값을 직접 입력하세요. **없는 값을 추정하지 않습니다.**"
        )
        return m

    snap = json.loads(f.read_text(encoding="utf-8"))
    got = snap.get("collected_at")
    series = snap.get("series", {})

    if (s := series.get("mortgage_rate", {})).get("latest"):
        m.mortgage_rate = _mv(s["latest"], "mortgage_rate", "한국은행 ECOS", got,
                              "⚠ 시장 평균이다. 개인 조건에 따라 다르므로 기준선으로만 쓴다")
    if (s := series.get("base_rate", {})).get("latest"):
        m.base_rate = _mv(s["latest"], "base_rate", "한국은행 ECOS", got)

    if cap := snap.get("derived", {}).get("jeonse_conversion_cap"):
        m.jeonse_conversion_cap = MarketValue(
            value=cap["value"], unit="%", as_of=str(m.base_rate.as_of if m.base_rate else ""),
            source=cap["basis"], collected_at=dt.date.fromisoformat(got),
            note=cap.get("note", ""),
        )

    m.warnings.extend(snap.get("warnings", []))

    _load_reb(d, m, property_type)

    for k, v in m.available.items():
        if v.is_stale():
            m.warnings.append(f"[{k}] 수집일 {v.collected_at} — {STALE_DAYS}일이 지났습니다. 다시 받으세요.")
    return m


# R-ONE 실측 구조(2026-08-16): CLS_NM=지역 · ITM_NM=지표 · DTA_VAL=값 · WRTTIME_IDTFR_ID=시점
# 표가 유형별로 갈린다(오피스 / 중대형 상가 / 소규모 상가 / 집합 상가).
# ⚠ 표마다 전국을 부르는 이름이 다르다(실측): 공실률=「전국」, 소득수익률=「전체」
REGION_CANDIDATES = ("전국", "전체")


def _latest(rows: list[dict], regions: tuple[str, ...] = REGION_CANDIDATES) -> dict | None:
    """전국 기준 최신값. 표마다 이름이 달라 후보를 순서대로 본다.

    없으면 None — **지어내지 않는다.**
    """
    cand: list[dict] = []
    for region in regions:
        cand = [r for r in rows if str(r.get("CLS_NM", "")) == region
                and r.get("DTA_VAL") not in (None, "")]
        if cand:
            break
    if not cand:
        return None
    r = max(cand, key=lambda x: str(x.get("WRTTIME_IDTFR_ID", "")))
    try:
        return {"value": float(r["DTA_VAL"]), "time": str(r.get("WRTTIME_IDTFR_ID", "")),
                "item": str(r.get("ITM_NM", "")), "unit": str(r.get("UI_NM", "%")),
                "region": str(r.get("CLS_NM", ""))}
    except (TypeError, ValueError):
        return None


# ⚠⚠ R-ONE 임대동향조사가 실제로 조사하는 유형(2026-08-16 실측).
#     오피스텔·아파트·다세대는 **여기 없다.**
REB_SURVEYED = ("오피스", "중대형 상가", "소규모 상가", "집합 상가")


def reb_type_of(property_type: str) -> str | None:
    """사용자가 말한 유형을 R-ONE 조사 유형으로 옮긴다. 없으면 None."""
    t = (property_type or "").strip()
    if t in REB_SURVEYED:
        return t
    if "상가" in t:                       # 「상가」만 말했으면 되묻는다
        return None
    return None


def _load_reb(cache_dir: Path, m: Market, property_type: str = "") -> None:
    """R-ONE 수집물이 있으면 공실률·소득수익률을 기본값으로 얹는다.

    ⚠⚠ **조사 대상이 아닌 유형에는 값을 싣지 않는다.**
    「오피스」는 업무용 빌딩이고 「오피스텔」은 다른 물건이다. 이름이 비슷해
    조용히 섞이면 사용자가 틀린 공실률로 계산한다.
    """
    f = cache_dir / "reb.json"
    if not f.exists():
        return

    prop_type = reb_type_of(property_type)
    if prop_type is None:
        m.warnings.append(
            f"⚠⚠ [{property_type or '유형 미지정'}] 공실률·소득수익률을 **싣지 않았습니다.** "
            f"한국부동산원 임대동향조사의 대상은 {' · '.join(REB_SURVEYED)}뿐입니다 — "
            f"**오피스텔·아파트는 조사 대상이 아닙니다.** "
            f"「오피스」는 업무용 빌딩이라 오피스텔에 쓰면 틀립니다. **직접 입력하십시오.**"
        )
        try:
            snap = json.loads(f.read_text(encoding="utf-8"))
            m.warnings.extend(snap.get("warnings", []))
        except Exception:
            pass
        return
    snap = json.loads(f.read_text(encoding="utf-8"))
    got = snap.get("collected_at")
    tables = snap.get("tables", {})

    def pick(name: str) -> dict | None:
        """⚠⚠ 요청한 유형이 없으면 **아무것도 돌려주지 않는다.**

        예전에는 없으면 아무 유형이나(사전 순 첫 항목) 집어 왔다. 그러면
        오피스 공실률에 「중대형 상가」 딱지가 붙는다 — 조용히 틀리는 정도가
        아니라 **적극적으로 오표기한다.** 「오피스≠오피스텔」과 같은 버그다.
        """
        by = tables.get(name, {}).get("by_type", {})
        if not by:
            return None
        block = by.get(prop_type)
        if block is None:
            m.warnings.append(
                f"[{name}] 수집물에 '{prop_type}'이 없습니다(있는 유형: "
                f"{', '.join(by) or '없음'}) — **다른 유형 값으로 대신하지 않습니다.** "
                "직접 입력하십시오."
            )
            return None
        return _latest(block["rows"])

    if hit := pick("vacancy"):
        m.vacancy_rate = MarketValue(
            value=hit["value"], unit=hit["unit"], as_of=hit["time"],
            source=f"한국부동산원 임대동향조사({prop_type})",
            collected_at=dt.date.fromisoformat(got),
            note=f"{hit['region']} 평균 · ⚠ 지역·유형 평균이다. 개별 물건과 다르다",
        )
    if hit := pick("income_yield"):
        m.noi_yield = MarketValue(
            value=hit["value"], unit=hit["unit"], as_of=hit["time"],
            source=f"한국부동산원 임대동향조사({prop_type})",
            collected_at=dt.date.fromisoformat(got),
            note=("분기 소득수익률 · ⚠⚠ **어느 비용까지 뺀 값인지 조사 개요를 확인해야 한다** "
                  "(조사 개요 미확인 — 이 repo의 미해결 항목)"),
        )
    if hit := pick("noi"):
        m.warnings.append(
            f"[R-ONE 순영업소득] ⚠⚠ 공표 항목이 '{hit['item']}'이고 단위가 "
            f"'{hit['unit']}'입니다 — **금액이 아닙니다.** 안민석 103쪽의 "
            f"순영업소득(유효조소득 − 영업경비, 금액)과 같은 것인지 확인이 필요합니다."
        )
    if not tables:
        m.warnings.append("R-ONE 수집물이 비어 있습니다 — 키를 확인하거나 직접 입력하세요.")
    m.warnings.extend(snap.get("warnings", []))


def funding_rate_default(m: Market) -> tuple[float | None, str]:
    """조달비용 r의 기본값. **없으면 None을 돌려주고 사용자에게 되묻는다.**

    ⚠ 이 값을 단독으로 쓰지 말 것 — leverage.py의 민감도표가 보이듯
    금리 3.5%p 차이가 자기자본수익률을 28%p 움직인다. `leverage.rate_sensitivity`로
    **구간을 함께** 보여야 한다(DISCLAIMER §1-3).
    """
    if m.mortgage_rate is None:
        return None, "시장 금리 없음 — 직접 입력하세요"
    v = m.mortgage_rate
    return v.value / 100, f"{v.describe()} · 기준선일 뿐 개인 금리가 아닙니다"


def suggested_rate_band(m: Market, spread: float = 0.01) -> list[float] | None:
    """민감도표에 쓸 금리 구간 — 기준선 ±spread.

    점추정 대신 구간을 내는 것이 이 도구의 규약이다.
    """
    base, _ = funding_rate_default(m)
    if base is None:
        return None
    return [round(base + d, 4) for d in (-spread, -spread / 2, 0, spread / 2, spread)]


def vacancy_months_default(m: Market) -> tuple[float | None, str]:
    """공실 개월수 기본값 — 시장 공실률(%)을 연 개월로 환산한다.

    ⚠ 지역·유형 평균이다. 개별 물건의 공실은 이것과 다르다.
    """
    if m.vacancy_rate is None:
        why = "시장 공실률 없음 — 직접 입력하세요(0으로 두지 마십시오)"
        if m.property_type and reb_type_of(m.property_type) is None:
            why = (f"⚠⚠ {m.property_type}은 한국부동산원 임대동향조사 대상이 아닙니다 — "
                   f"「오피스」 값을 대신 쓰면 틀립니다. 직접 입력하십시오")
        return None, why
    v = m.vacancy_rate
    return round(v.value / 100 * 12, 2), f"[{m.property_type}] {v.describe()} 환산 · {v.note}"
