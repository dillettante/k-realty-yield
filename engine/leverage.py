"""레버리지 — 항등식과 민감도.

『돈공부』 1.7이 세운 항등식을 그대로 옮긴다. 3.A.3 §판정 4가 그 부동산 사례다.

    자기자본수익률 = 자산수익률 + (자산배율 − 1) × (자산수익률 − 조달비용)
    ROE           = ROA        + (L − 1)        × (ROA − r)

이 식의 요점은 하나다 — **대출은 물건의 수익을 키우지 않는다.**
자산수익률과 조달비용의 **차이에 지렛대를 걸 뿐**이고, 차이가 음수가 되면
같은 배수로 반대로 돈다.

설계 원칙(DISCLAIMER §1-3): **점추정을 내지 않는다.**
금리는 하나의 값이 아니라 표로 낸다 — 부호가 뒤집히는 지점을 사용자가 봐야 한다.
"""

from dataclasses import dataclass


@dataclass
class LeverageRow:
    """민감도표의 한 줄. 책 §판정 4의 표 한 행에 대응한다."""

    rate: float          # 조달비용(대출금리)
    interest: float      # 연 이자
    cash_flow: float     # 실질 현금흐름 = 자산 순수입 − 이자
    roe: float           # 자기자본수익률
    roa: float           # 자산수익률 — 이 칸은 움직이지 않는다


def asset_multiple(asset: float, equity: float) -> float:
    """자산배율 L = 자산 ÷ 자기자본."""
    return asset / equity if equity else float("inf")


def equity_ratio(asset: float, equity: float) -> float:
    """자기자본 비율 m = 자기자본 ÷ 자산. 배율의 역수다."""
    return equity / asset if asset else 0.0


def roe(roa: float, multiple: float, funding_rate: float) -> float:
    """항등식 그대로. 자산군을 타지 않는다(1.7).

    전세가율 90% 아파트와 1920년대 증거금 10% 주식이 이 한 줄에 함께 놓인다.
    """
    return roa + (multiple - 1) * (roa - funding_rate)


def sign_flip_point(roa: float) -> float:
    """부호 전환점 — 자산수익률 = 조달비용인 지점.

    여기서는 배율이 몇이든 ROE = ROA다. 레버리지가 아무것도 하지 않는다.

    ⚠⚠ 손익분기 금리와 다르고 **이보다 먼저 온다**(1.7 §판정 3).
    그 사이 구간에서 투자자는 **돈을 벌면서 레버리지 때문에 손해를 본다.**
    """
    return roa


def wipeout_drop(asset: float, equity: float) -> float:
    """자기자본 소진 하락률 — 값이 이만큼 내리면 자기자본이 0이 된다.

    자기자본 비율 m과 같은 값이고 배율의 역수다.
    전세가율 90%면 10%, 증거금률 5%인 지수선물이면 5%, 코인 선물 125배면 0.8%.
    """
    return equity_ratio(asset, equity)


def critical_recovery(multiple: float) -> float:
    """임계 회수율 = 1 ÷ (자산배율 − 1).

    추가로 넣어야 할 돈이 애초 넣은 돈과 같아지는 부채 회수 비율.
    ⚠ 3.A.4의 「임계 하락률」과 식은 같으나 재는 대상이 다르다(1.7 §3-2).
    """
    return 1 / (multiple - 1) if multiple > 1 else float("inf")


def weighted_funding_rate(debts: list[tuple[float, float]]) -> float:
    """조달비용 가중평균 — 이자 총액 ÷ 부채 총액.

    ⚠⚠ 이 규칙을 안 쓰면 책의 표가 재현되지 않는다(1.7 §3-7).
    무이자 보증금이 섞이면 표면 금리보다 **낮아진다**. 전세는 r = 0이라
    부호가 뒤집히지 않는다.

    debts: [(금액, 이율)] — 보증금은 (금액, 0.0)으로 넣는다.
    """
    total = sum(amount for amount, _ in debts)
    if not total:
        return 0.0
    interest = sum(amount * rate for amount, rate in debts)
    return interest / total


def rate_sensitivity(
    asset: float,
    equity: float,
    roa: float,
    rates: list[float],
    loan: float | None = None,
) -> list[LeverageRow]:
    """금리 민감도표 — 이 도구가 점추정 대신 내놓는 것.

    책 §판정 4의 표를 그대로 만든다. 자산수익률 칸이 **한 번도 안 움직이는 것**이
    이 표의 요점이다.
    """
    if loan is None:
        loan = asset - equity
    asset_income = asset * roa
    rows = []
    for r in rates:
        interest = loan * r
        cash = asset_income - interest
        rows.append(LeverageRow(
            rate=r,
            interest=interest,
            cash_flow=cash,
            roe=cash / equity if equity else 0.0,
            roa=roa,
        ))
    return rows
