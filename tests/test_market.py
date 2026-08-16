"""Phase 3 완료 기준 — 키 없이도 돌고, 있으면 기본값이 시장값으로 바뀐다.

핵심은 「수집물이 없을 때 무엇을 하는가」다.
**추정하지 않고 None을 돌려주며, 그 사실이 경고에 남는다.**
"""

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.market import (  # noqa: E402
    Market, funding_rate_default, load, suggested_rate_band,
)


def test_수집물이_없어도_죽지_않는다() -> None:
    """키 없는 사용자가 이 경로를 탄다. 예외가 나면 안 된다."""
    with tempfile.TemporaryDirectory() as d:
        m = load(d)
        assert isinstance(m, Market)
        assert m.mortgage_rate is None
        assert m.warnings and "직접 입력" in " ".join(m.warnings)


def test_값이_없으면_추정하지_않는다() -> None:
    """⚠ 이 도구의 규약 — 그럴듯한 기본값을 지어내지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        m = load(d)
        rate, why = funding_rate_default(m)
        assert rate is None
        assert "직접 입력" in why
        assert suggested_rate_band(m) is None
        assert "mortgage_rate" in m.missing


def test_수집물이_있으면_기본값이_된다() -> None:
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "series": {
            "mortgage_rate": {"latest": {"time": "202606", "value": 4.36, "unit": "연리%"}},
            "base_rate": {"latest": {"time": "202607", "value": 2.75, "unit": "연리%"}},
        },
        "derived": {"jeonse_conversion_cap": {
            "value": 4.75, "basis": "주택임대차보호법 제7조의2", "note": "기준금리 2.75% + 2%p"}},
        "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "ecos.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        m = load(d)
        assert m.mortgage_rate.value == 4.36
        rate, why = funding_rate_default(m)
        assert abs(rate - 0.0436) < 1e-9
        assert "기준선" in why           # 개인 금리가 아님을 항상 말한다


def test_전월세_전환율_상한이_유도된다() -> None:
    """⭐ 데이터 레이어와 법령 레이어가 만나는 자리.

    법도 시행령도 안 고치고 금융통화위원회가 값을 움직인다.
    """
    from data.collect_ecos import conversion_rate_cap
    assert conversion_rate_cap(2.75) == 4.75
    assert conversion_rate_cap(3.50) == 5.50


def test_점추정_대신_구간을_낸다() -> None:
    """DISCLAIMER §1-3 — 단일 답을 주지 않는다."""
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "series": {"mortgage_rate": {"latest": {"time": "202606", "value": 4.36, "unit": "%"}}},
        "derived": {}, "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "ecos.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        band = suggested_rate_band(load(d))
        assert band and len(band) == 5
        assert band[0] < band[2] < band[-1]      # 기준선 좌우로 벌어진다


def test_낡은_수집물은_경고한다() -> None:
    snap = {
        "collected_at": (dt.date.today() - dt.timedelta(days=90)).isoformat(),
        "series": {"mortgage_rate": {"latest": {"time": "202601", "value": 4.0, "unit": "%"}}},
        "derived": {}, "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "ecos.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        m = load(d)
        assert m.mortgage_rate.is_stale()
        assert any("다시 받으세요" in w for w in m.warnings)


def _ecos_stub(d: str) -> None:
    (Path(d) / "ecos.json").write_text(json.dumps({
        "collected_at": dt.date.today().isoformat(),
        "series": {}, "derived": {}, "warnings": [],
    }, ensure_ascii=False), encoding="utf-8")


def test_REB_수집물이_없어도_죽지_않는다() -> None:
    """R-ONE은 키가 필수라 대부분의 이용자에게 이 파일이 없다."""
    with tempfile.TemporaryDirectory() as d:
        _ecos_stub(d)
        m = load(d, property_type="오피스")   # reb.json 없음
        assert m.vacancy_rate is None and m.noi_yield is None


def _reb_row(region: str, item: str, val: str, time: str = "202403") -> dict:
    """R-ONE 실측 구조(2026-08-16) — CLS_NM=지역 · ITM_NM=지표 · DTA_VAL=값."""
    return {"CLS_NM": region, "ITM_NM": item, "DTA_VAL": val,
            "WRTTIME_IDTFR_ID": time, "UI_NM": "%"}


def test_REB_수집물이_있으면_공실률이_기본값이_된다() -> None:
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "tables": {
            "vacancy": {"by_type": {"오피스": {"rows": [
                _reb_row("전국", "공실률", "9.8"),
                _reb_row("서울", "공실률", "5.1"),          # 전국이 아니면 안 뽑힌다
            ]}}},
            "income_yield": {"by_type": {"오피스": {"rows": [
                _reb_row("전체", "소득수익률", "1.02", "20262Q"),   # ⚠ 이 표는 「전체」
            ]}}},
        },
        "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        _ecos_stub(d)
        (Path(d) / "reb.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        m = load(d, property_type="오피스")              # ⚠ 유형을 넘겨야 실린다
        assert m.vacancy_rate.value == 9.8              # 전국을 골랐다
        assert "평균" in m.vacancy_rate.note             # 개별 물건과 다름을 항상 말한다
        assert m.noi_yield.value == 1.02                # 「전체」도 잡는다
        assert "비용까지 뺀 값" in m.noi_yield.note       # 미해결 항목을 숨기지 않는다


def test_순영업소득_표가_금액이_아니면_경고한다() -> None:
    """⚠⚠ 실측 발견 — R-ONE 「순영업소득」 표의 항목은 「임대수입(%)」이다.

    안민석 103쪽의 순영업소득(유효조소득 − 영업경비, **금액**)과 같은 것인지
    확인되지 않았다. 도구가 그 값을 쓰면서 이 사실을 숨기면 안 된다.
    """
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "tables": {"noi": {"by_type": {"오피스": {"rows": [
            _reb_row("전국", "임대수입(%)", "98.9"),
        ]}}}},
        "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        _ecos_stub(d)
        (Path(d) / "reb.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        m = load(d, property_type="오피스")
        assert any("금액이 아닙니다" in w for w in m.warnings)


def test_공실률을_개월로_환산한다() -> None:
    from engine.market import vacancy_months_default
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "tables": {"vacancy": {"by_type": {"오피스": {"rows": [
            _reb_row("전국", "공실률", "8.61"),
        ]}}}},
        "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        _ecos_stub(d)
        (Path(d) / "reb.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        months, why = vacancy_months_default(load(d, property_type="오피스"))
        assert abs(months - 1.03) < 0.01               # 8.61% → 연 1.03개월
        assert "평균" in why

        # 값이 없으면 0으로 두라고 하지 않는다
        with tempfile.TemporaryDirectory() as d2:
            _ecos_stub(d2)
            months2, why2 = vacancy_months_default(load(d2, property_type="오피스"))
            assert months2 is None and "0으로 두지 마십시오" in why2



def test_오피스텔에_오피스_값을_쓰지_않는다() -> None:
    """⚠⚠ 이름이 비슷해 조용히 섞이면 사용자가 틀린 공실률로 계산한다.

    「오피스」는 업무용 빌딩이고 「오피스텔」은 다른 물건이다.
    R-ONE 임대동향조사에 **오피스텔은 조사 대상이 아니다**(2026-08-16 실측).
    """
    from engine.market import vacancy_months_default
    snap = {
        "collected_at": dt.date.today().isoformat(),
        "tables": {"vacancy": {"by_type": {"오피스": {"rows": [
            _reb_row("전국", "공실률", "8.61"),
        ]}}}},
        "warnings": [],
    }
    with tempfile.TemporaryDirectory() as d:
        _ecos_stub(d)
        (Path(d) / "reb.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

        # 오피스텔 — 값을 싣지 않고 경고한다
        m = load(d, property_type="오피스텔")
        assert m.vacancy_rate is None, "오피스텔에 오피스 공실률이 실렸다"
        assert any("조사 대상이 아닙니다" in w for w in m.warnings)
        months, why = vacancy_months_default(m)
        assert months is None and "틀립니다" in why

        # 아파트도 마찬가지
        assert load(d, property_type="아파트").vacancy_rate is None

        # 유형을 안 밝혀도 싣지 않는다 — 조용히 넘어가지 않는다
        m3 = load(d, property_type="")
        assert m3.vacancy_rate is None
        assert any("싣지 않았습니다" in w for w in m3.warnings)

        # 오피스는 정상 적용
        m4 = load(d, property_type="오피스")
        assert m4.vacancy_rate.value == 8.61
        assert "[오피스]" in vacancy_months_default(m4)[1]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✅ {name}")
            except AssertionError as e:
                fails += 1
                print(f"  ❌ {name}\n     {e}")
    print(f"\n{'통과' if not fails else f'실패 {fails}건'}")
    sys.exit(1 if fails else 0)
