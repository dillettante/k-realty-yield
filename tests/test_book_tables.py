"""Phase 1 완료 기준 — 『돈공부』 3.A.3의 표 셋을 재현한다.

허용 오차 **0.01%p**. 이 테스트가 통과하지 않으면 엔진이 틀린 것이다.

왜 책의 표를 테스트로 쓰나 — 책의 수치는 원자료·계산식·전제가 전부 적힌
재현 가능한 값이다(`notes/수치재현대장.md` D1~D4). 그래서 회귀 테스트가
되는 동시에, 이 도구가 책의 판정을 실제로 구현했다는 증거가 된다.

    python3 -m pytest tests/ -q       (pytest 있으면)
    python3 tests/test_book_tables.py (없으면 — 이 파일 단독 실행)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.leverage import rate_sensitivity, sign_flip_point, wipeout_drop  # noqa: E402
from engine.yield_basic import (  # noqa: E402
    MAN, Property, net_yield, net_yield_steps, roi_leveraged, surface_yield,
)

TOL = 0.0001  # 0.01%p


def _oficetel() -> Property:
    """§판정 2의 전제 — 서울 업무용 오피스텔.

    매매가 2억 · 보증금 2,000만 · 월세 75만(연 900만) · 대출 없음.
    취득세 4.6%(920만) · 취득 중개보수 0.9%(180만) · 등기·법무 50만(전제값).
    보유·운영비 연 65만(재산세 30 + 관리비 15 + 수선비 20, 전제값).
    재계약 중개보수 (2,000만 + 75만×100)×0.9% = 85.5만을 2년으로 안분 → 42.75만.
    임대소득 한계세율 26.4%(지방소득세 포함).
    """
    return Property(
        price=200_000_000,
        deposit=20_000_000,
        monthly_rent=750_000,
        acquisition_tax=9_200_000,
        broker_fee_buy=1_800_000,
        registration_fee=500_000,
        vacancy_months=1.0,
        holding_cost_yearly=650_000,
        relet_fee_yearly=427_500,
        rent_tax_rate=0.264,
    )


def test_판정2_단계분해() -> None:
    """표면 5.00% → 실질 2.76%. 다섯 단계의 낙차까지 대조한다."""
    steps = net_yield_steps(_oficetel())
    expected = [0.0500, 0.0470, 0.0431, 0.0397, 0.0374, 0.0276]
    assert len(steps) == len(expected)
    for s, e in zip(steps, expected):
        assert abs(s.rate - e) < TOL, f"{s.label}: {s.rate:.4%} ≠ {e:.2%}"

    # 낙차 — ⚠ 책 초판의 ④는 0.23%p였으나 정확한 값은 0.22%p다.
    # 이 테스트가 그 오류를 잡았고(2026. 8. 16.) 책을 고쳤다.
    # 근거: 3.9687% − 3.7454% = 0.2232%p. 그리고 책 표기대로 더하면
    # 합이 2.25%p가 되어 본문의 「2.24%p가 사라지고」와 어긋났다.
    drops = [round(s.drop * 100, 2) for s in steps[1:]]
    assert drops == [0.30, 0.39, 0.34, 0.22, 0.99], drops
    assert abs(sum(s.drop for s in steps[1:]) - 0.0224) < TOL   # 본문과 일치

    # 「55%만 남는다」
    assert abs(steps[-1].rate / steps[0].rate - 0.55) < 0.01

    # 사라진 몫의 44%가 세금 — 세금 낙차 ÷ 전체 낙차
    total = steps[0].rate - steps[-1].rate
    assert abs(steps[-1].drop / total - 0.44) < 0.01


def test_판정3_공실() -> None:
    """공실 0·1·2개월. 표면과 실질을 함께 본다.

    ⚠ 공실 두 달의 낙차(0.57%p)가 취득세·중개보수·등기비를 전부 합친 것
    (0.30%p)보다 크다 — 이 절의 반직관적 결과다.
    """
    table = {0.0: (0.0500, 0.0304), 1.0: (0.0458, 0.0276), 2.0: (0.0417, 0.0247)}
    for months, (surface_e, net_e) in table.items():
        p = _oficetel()
        p.vacancy_months = months
        # 표면은 공실만 반영하고 부대비용은 안 넣는다(책의 「표면 기준」 칸)
        surface = (p.yearly_rent - p.monthly_rent * months) / (p.price - p.deposit)
        assert abs(surface - surface_e) < TOL, f"공실 {months}개월 표면"
        assert abs(net_yield(p) - net_e) < TOL, f"공실 {months}개월 실질"

    # 공실 2개월 낙차 > 취득 부대비용 낙차
    vac_drop = 0.0304 - 0.0247
    acq_drop = net_yield_steps(_oficetel())[1].drop
    assert vac_drop > acq_drop


def test_판정4_금리민감도() -> None:
    """이고은 73쪽 — 자산 1억 · ROA 4% · 보증금 1,000만 · 대출 80%.

    실투자금 1,000만. 금리만 3.5 → 7.0%로 움직인다.
    **자산수익률은 한 번도 안 움직인다.**
    """
    asset, loan, deposit = 100_000_000, 80_000_000, 10_000_000
    equity = asset - loan - deposit          # 1,000만
    assert equity == 10_000_000

    rows = rate_sensitivity(
        asset=asset, equity=equity, roa=0.04,
        rates=[0.035, 0.045, 0.050, 0.060, 0.070], loan=loan,
    )
    expected_roe = [0.120, 0.040, 0.000, -0.080, -0.160]
    expected_interest = [280, 360, 400, 480, 560]     # 만원
    expected_cash = [120, 40, 0, -80, -160]           # 만원

    for row, roe_e, int_e, cash_e in zip(rows, expected_roe, expected_interest, expected_cash):
        assert abs(row.roe - roe_e) < TOL, f"금리 {row.rate:.1%}: ROE {row.roe:.4%} ≠ {roe_e:.1%}"
        assert abs(row.interest / MAN - int_e) < 0.5
        assert abs(row.cash_flow / MAN - cash_e) < 0.5
        assert row.roa == 0.04                         # ⭐ 한 번도 안 움직인다

    # 금리 3.5%p 상승에 ROE는 28%p 움직인다
    assert abs((rows[0].roe - rows[-1].roe) - 0.28) < TOL

    # 부호 전환점 = ROA = 5.0%에서 ROE가 0
    assert abs(sign_flip_point(0.04) - 0.04) < TOL
    zero = [r for r in rows if abs(r.roe) < TOL][0]
    assert abs(zero.rate - 0.050) < TOL

    # 자기자본 소진 하락률 = 자기자본 비율 = 10%
    assert abs(wipeout_drop(asset, equity) - 0.10) < TOL


def test_ROI_이고은_원문재현() -> None:
    """확장 전에 원문값 12.0%를 먼저 재현했는지 확인한다(책의 절차 그대로)."""
    p = Property(price=100_000_000, deposit=10_000_000, monthly_rent=0,
                 loan=80_000_000, loan_rate=0.035)
    p.monthly_rent = int(100_000_000 * 0.04 / 12)      # ROA 4% → 연 400만
    assert abs(roi_leveraged(p) - 0.12) < 0.001


def test_다섯셈법이_서로_다른_값을_낸다() -> None:
    """§판정 1의 요점 — 같은 물건에서 다섯이 갈린다."""
    p = _oficetel()
    assert abs(surface_yield(p) - 0.05) < TOL
    assert abs(net_yield(p) - 0.0276) < TOL
    assert surface_yield(p) != net_yield(p)


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
