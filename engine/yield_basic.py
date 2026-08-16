"""다섯 셈법과 단계 분해 — 임대수익률.

**새로 설계한 식은 없다.** 국내 부동산 실무서들이 쓰는 자를 그대로 옮기고,
서로 다른 자에 이름을 붙여 나란히 놓았을 뿐이다.

  · 「수익률」이라는 한 낱말이 **다섯 가지 셈법**을 가리킨다 — 책마다 분모가 다르다
  · 표면 5%짜리에서 비용을 차례로 빼면 실제로 남는 것은 **절반쯤**이다
  · **공실을 0으로 두지 않는다** — 낙차가 취득 부대비용 전부보다 크다

설계 원칙 두 가지(DISCLAIMER §1):
  · 단일 답을 주지 않는다 — 다섯 셈법을 **동시에** 낸다.
  · 값을 지어내지 않는다 — 모르는 항목은 0이고, 0이라는 사실이 결과에 남는다.

금액 단위는 원(int). 비율은 소수(0.046 = 4.6%).
외부 의존 없음(stdlib only).
"""

from dataclasses import dataclass, field

MAN = 10_000  # 만원. 국내 실무서·중개 자료가 만원 단위라 대조할 때 쓴다.


@dataclass
class Property:
    """물건 하나. 사용자가 주는 값만 담는다."""

    price: int                    # 취득가 (매매가·낙찰가·분양가)
    deposit: int = 0              # 보증금
    monthly_rent: int = 0         # 월세

    # 취득 부대비용 — 분모에 더해진다
    acquisition_tax: int = 0      # 취득세(부가 세목 포함)
    broker_fee_buy: int = 0       # 매매 중개보수
    registration_fee: int = 0     # 등기·법무 (L6 — 법령에 값이 없다)
    other_acquisition: int = 0    # 그 밖(명도비용 등 — 경매는 여기로)

    # 보유 중 비용 — 분자에서 빠진다 (연액)
    vacancy_months: float = 0.0   # 공실 개월수
    holding_cost_yearly: int = 0  # 재산세·관리비·수선비 (L6 포함)
    relet_fee_yearly: int = 0     # 재계약 중개보수를 연으로 안분한 값

    # 세금
    rent_tax_rate: float = 0.0    # 임대소득 한계세율(지방소득세 포함)

    # 대출 — 레버리지 계산에 쓴다(leverage.py)
    loan: int = 0
    loan_rate: float = 0.0

    @property
    def yearly_rent(self) -> int:
        return self.monthly_rent * 12

    @property
    def acquisition_costs(self) -> int:
        """취득 부대비용 합계. 분모를 키운다."""
        return (self.acquisition_tax + self.broker_fee_buy
                + self.registration_fee + self.other_acquisition)

    @property
    def equity(self) -> int:
        """실제로 넣은 자기자본 = 취득가 + 부대비용 − 보증금 − 대출."""
        return self.price + self.acquisition_costs - self.deposit - self.loan


@dataclass
class Step:
    """단계 분해의 한 줄."""

    label: str
    income: float      # 연 순수입
    equity: float      # 투입 자기자본
    rate: float        # 수익률 (소수)
    drop: float        # 앞 단계 대비 낙차 (%p, 소수)


def surface_yield(p: Property) -> float:
    """표면수익률 — 안민석의 자. 연 월세 ÷ (취득가 − 보증금).

    비용을 하나도 빼지 않는다. 중개업소·분양 자료가 말하는 수익률이 대개 이것이다.
    ⚠ 실측한 국내 재테크서 45권에 **「표면수익률」이라는 낱말 자체가 0회**다.
      이름 없이 쓰이므로 독자는 자기가 어느 자를 보는지 모른다.
    """
    base = p.price - p.deposit
    return p.yearly_rent / base if base else 0.0


def net_yield_steps(p: Property) -> list[Step]:
    """표면 → 실질로 가는 단계 분해.

    ⚠⚠ **빼는 순서가 각 칸의 크기를 바꾼다**(합계는 순서와 무관).
    세금을 맨 앞에 놓으면 그 칸이 0.99%p에서 1.32%p로 커진다. 그래서
    낙차를 인용할 때는 **순서를 함께 밝혀야 한다.**
    여기서는 지출이 실제로 발생하는 차례를 따른다 —
    부대비용 → 공실 → 보유운영비 → 재계약비 → 세금.
    """
    steps: list[Step] = []
    income = float(p.yearly_rent)
    equity = float(p.price - p.deposit)

    def add(label: str) -> None:
        rate = income / equity if equity else 0.0
        prev = steps[-1].rate if steps else rate
        steps.append(Step(label, income, equity, rate, prev - rate))

    add("Ⓞ 문헌의 자")                       # 표면

    equity += p.acquisition_costs             # 분모가 커진다
    add("① 취득 부대비용")

    income -= p.monthly_rent * p.vacancy_months
    add("② 공실")

    income -= p.holding_cost_yearly
    add("③ 보유·운영비")

    income -= p.relet_fee_yearly
    add("④ 재계약 중개보수")

    income -= income * p.rent_tax_rate        # 세금은 남은 소득에만 붙는다
    add("⑤ 임대소득세")

    return steps


def net_yield(p: Property) -> float:
    """실질수익률 — 위 단계를 다 거친 값.

    ⚠ 물가는 빼지 않았다. 이 값은 **명목**이다.
    """
    return net_yield_steps(p)[-1].rate


def roi_leveraged(p: Property) -> float:
    """투자수익률(ROI) — 이고은의 자.

    (연 월세 − 대출이자) ÷ (자산가격 − 대출 − 보증금).
    ⚠ 실측한 45권에서 **이자를 뺀 유일한 부동산 수익률 계산**이다.
    """
    invested = p.price - p.loan - p.deposit
    if not invested:
        return 0.0
    return (p.yearly_rent - p.loan * p.loan_rate) / invested


def noi(p: Property) -> float:
    """순영업소득(NOI) — 안민석 103쪽의 자. 비율이 아니라 금액이다.

    유효조소득 − 영업경비. 공실과 운영비를 뺀 뒤의 연 현금흐름.
    ⚠ 한국부동산원 상업용부동산 임대동향조사가 이 값을 분기마다 공표한다.
    """
    effective = p.yearly_rent - p.monthly_rent * p.vacancy_months
    return effective - p.holding_cost_yearly


def five_measures(p: Property) -> dict[str, float | None]:
    """다섯 셈법을 **동시에** 낸다 — 이 도구의 첫 화면.

    「중개업소가 말한 5%」가 어느 칸인지 사용자가 알아야 하기 때문이다.
    ⚠ 시세차익 계열 둘(송희창·너나위)은 **매도 시세를 전제**해야 성립한다.
    이 도구는 장래 가격을 다루지 않으므로 None으로 두고, 쓰려면 사용자가
    시세를 「가정」으로 명시해야 한다(DISCLAIMER §1).
    """
    return {
        "표면수익률(안민석)": surface_yield(p),
        "실질수익률(단계 분해)": net_yield(p),
        "투자수익률 ROI(이고은)": roi_leveraged(p),
        "순영업소득 NOI(안민석 103쪽)": noi(p),   # ⚠ 금액이다. 비율 아님
        "시세차익형(송희창·너나위)": None,          # 매도 시세 필요
    }
