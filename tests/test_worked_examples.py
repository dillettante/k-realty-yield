"""손으로 검산한 예제 — 엔진이 맞게 도는지 지키는 회귀 테스트.

**전제와 기대값이 한 자리에 있다.** 그래서 이 파일이 예제이자 테스트다 —
계산이 바뀌면 어느 전제에서 어떻게 어긋났는지가 바로 드러난다.

기대값은 전부 **손계산으로 따로 구한 것**이고, 코드 출력을 그대로 굳힌 것이
아니다(그러면 틀린 값도 통과한다).

⚠ 허용 오차는 칸마다 다르다 — 수익률·ROE 같은 핵심 칸은 `TOL`(0.01%p),
파생 비율은 ±1%p, 금액 칸은 ±5,000원. 각 assert 옆에 적어 두었다.

    python3 -m pytest tests/ -q            (pytest 있으면)
    python3 tests/test_worked_examples.py  (없으면 — 이 파일 단독 실행)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.leverage import (  # noqa: E402
    asset_multiple, critical_recovery, equity_ratio, rate_sensitivity, roe,
    sign_flip_point, weighted_funding_rate, wipeout_drop,
)
from engine.yield_basic import (  # noqa: E402
    MAN, Property, net_yield, net_yield_steps, roi_leveraged, surface_yield,
)

TOL = 0.0001  # 0.01%p


def _oficetel() -> Property:
    """예제 전제 — 서울 업무용 오피스텔.

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

    # 낙차 — ⚠ 손계산 결과 ④는 0.23%p가 아니라 0.22%p다.
    # 근거: 3.9687% − 3.7454% = 0.2232%p. 0.23으로 적으면
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
        # 표면은 공실만 반영하고 부대비용은 안 넣는다(「표면 기준」 칸)
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

    # ⚠⚠ 두 지점은 다르고, 부호 전환이 **먼저** 온다.
    #    그 사이 구간에서 투자자는 돈을 벌면서 레버리지 때문에 손해를 본다.
    #
    #    ⚠ 축이 둘이라 헷갈린다 — 이 표는 **대출금리** 축이고,
    #      인자 없는 sign_flip_point()는 **가중 조달비용** 축이다.
    #      무이자 보증금 1,000만이 섞여 있어 두 값이 0.5%p 어긋난다.
    assert abs(sign_flip_point(0.04) - 0.04) < TOL                  # 가중 조달비용 축
    flip = sign_flip_point(0.04, loan=loan, free_debt=deposit)      # 대출금리 축
    assert abs(flip - 0.045) < TOL, f"부호 전환점 {flip:.4%} ≠ 4.5%"

    at_flip = [r for r in rows if abs(r.rate - flip) < TOL][0]
    assert abs(at_flip.roe - at_flip.roa) < TOL, "부호 전환점에서는 ROE = ROA다"

    zero = [r for r in rows if abs(r.roe) < TOL][0]                 # 손익분기
    assert abs(zero.rate - 0.050) < TOL
    assert flip < zero.rate, "부호 전환이 손익분기보다 먼저 와야 한다"

    # 자기자본 소진 하락률 = 자기자본 비율 = 10%
    assert abs(wipeout_drop(asset, equity) - 0.10) < TOL
    assert abs(equity_ratio(asset, equity) - 0.10) < TOL
    assert abs(asset_multiple(asset, equity) - 10.0) < TOL
    # 임계 회수율 = 1/(L−1) = 1/9
    assert abs(critical_recovery(10.0) - 1 / 9) < TOL


def test_레버리지_항등식이_민감도표와_같은_값을_낸다() -> None:
    """⚠⚠ `roe()`에 **대출금리를 그대로 넣으면 틀린다.**

    무이자 보증금이 섞이면 조달비용은 가중평균이라 표면 금리보다 낮다.
    이 예제에서 대출금리 3.5%를 그대로 넣으면 8.5%, 가중평균 3.111%를
    넣으면 12.0%다 — 3.5%p 어긋난다. 이 테스트가 그 함정을 지킨다.
    """
    asset, loan, deposit = 100_000_000, 80_000_000, 10_000_000
    equity = asset - loan - deposit
    L = asset_multiple(asset, equity)

    rw = weighted_funding_rate([(loan, 0.035), (deposit, 0.0)])
    assert abs(rw - 0.035 * loan / (loan + deposit)) < TOL
    assert abs(rw - 0.031111) < 1e-5, f"가중 조달비용 {rw:.4%}"

    assert abs(roe(0.04, L, rw) - 0.12) < TOL              # ✅ 손계산 12.0%
    assert abs(roe(0.04, L, 0.035) - 0.085) < TOL          # ❌ 대출금리를 그대로 넣으면

    # 항등식과 민감도표가 모든 행에서 일치해야 한다
    for row in rate_sensitivity(asset=asset, equity=equity, roa=0.04,
                                rates=[0.035, 0.045, 0.050, 0.060], loan=loan):
        rw_row = weighted_funding_rate([(loan, row.rate), (deposit, 0.0)])
        assert abs(roe(0.04, L, rw_row) - row.roe) < TOL, f"금리 {row.rate:.1%}"


def test_전월세_전환율_상한은_두_상한_중_낮은_쪽이다() -> None:
    """⚠⚠ 조문은 「다음 각 호 중 **낮은 비율**」이다 — 상한이 둘이다.

    기준금리만 더하면 금리가 높을 때 법정 상한을 넘긴 값을 낸다.
    그리고 **주택과 상가는 식 자체가 다르다** — 더하기 vs 곱하기.
    """
    from data.collect_ecos import conversion_rate_cap as cap

    # 주택: min(10%, 기준금리 + 2%p) — 주임법 §7-2 · 시행령 §9
    assert abs(cap(2.75, "주택") - 4.75) < 0.001        # 연동분이 낮다
    assert abs(cap(9.00, "주택") - 10.00) < 0.001       # ⭐ 상한이 이긴다

    # 상가: min(12%, 기준금리 × 4.5배) — 상임법 §12 · 시행령 §5
    assert abs(cap(2.00, "상가") - 9.00) < 0.001        # 연동분이 낮다
    assert abs(cap(2.75, "상가") - 12.00) < 0.001       # ⭐ 상한이 이긴다

    # 현 기준금리에서 둘의 간격 — 하나만 쓰면 상가에서 7.25%p 틀린다
    assert abs(cap(2.75, "상가") - cap(2.75, "주택") - 7.25) < 0.001

    try:
        cap(2.75, "오피스텔")
    except ValueError:
        pass
    else:
        raise AssertionError("모르는 유형은 조용히 주택으로 계산하면 안 된다")


def test_ROI_이고은_원문재현() -> None:
    """이고은의 자를 원문 전제 그대로 재현한다.

    ⚠ 남의 자를 확장하기 전에 **원문값을 먼저 맞춰 보는 것**이 순서다.
    안 맞으면 확장이 아니라 다른 계산을 하고 있는 것이다.
    """
    p = Property(price=100_000_000, deposit=10_000_000, monthly_rent=0,
                 loan=80_000_000, loan_rate=0.035)
    p.monthly_rent = int(100_000_000 * 0.04 / 12)      # ROA 4% → 연 400만
    assert abs(roi_leveraged(p) - 0.12) < 0.001


def test_다섯셈법이_서로_다른_값을_낸다() -> None:
    """요점 — 같은 물건인데 자가 다르면 값이 갈린다."""
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
