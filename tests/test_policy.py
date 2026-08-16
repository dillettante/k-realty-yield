"""Phase 2 완료 기준 — 값의 나이가 강제되는가.

policy/schema.md의 세 규약을 테스트한다.
  1. 필수 필드가 없으면 로드를 거부한다
  2. 만료된 값을 쓰면 경고가 붙는다
  3. L5·L6은 값을 싣지 않는다
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.policy_loader import (  # noqa: E402
    Constant, collect_warnings, load, load_all,
)

POLICY = Path(__file__).resolve().parent.parent / "policy"


def test_전건_로드되고_필수필드가_있다() -> None:
    consts = load_all()
    assert len(consts) >= 30, len(consts)
    for c in consts:
        assert c.id and c.name and c.layer and c.basis
        assert isinstance(c.checked_at, dt.date)
        assert c.status


def test_만료전에는_조용하다() -> None:
    consts = load(POLICY / "constants.yaml")
    l1 = [c for c in consts if c.layer == "L1"][0]
    before = l1.expires_at - dt.timedelta(days=1)
    assert l1.age_state(before) == "fresh"


def test_만료되면_경고가_붙는다() -> None:
    """Phase 2의 핵심 — 이게 안 되면 이 repo의 차별점이 없다."""
    consts = load(POLICY / "constants.yaml")
    c = [x for x in consts if x.expires_at][0]

    just_after = c.expires_at + dt.timedelta(days=1)
    assert c.age_state(just_after) == "stale"
    assert any("만료" in w for w in c.warnings(just_after))

    long_after = c.expires_at + dt.timedelta(days=40)
    assert c.age_state(long_after) == "expired"
    assert any("직접 입력" in w for w in c.warnings(long_after))


def test_L4는_만료가_30일이다() -> None:
    """행정지도는 예고가 없다 — 가장 짧은 수명."""
    ltv = load(POLICY / "ltv.yaml")
    l4 = [c for c in ltv if c.layer == "L4" and c.expires_at]
    assert l4, "L4 항목이 있어야 한다"
    for c in l4:
        assert (c.expires_at - c.checked_at).days <= 31, c.id


def test_규정값과_실제값이_다르면_반드시_알린다() -> None:
    """⚠⚠ 조문만 보면 틀리는 자리 — 경고가 없으면 이 도구는 위험하다."""
    ltv = load(POLICY / "ltv.yaml")
    gap = [c for c in ltv
           if c.regulation_value is not None and c.effective_value is not None
           and c.regulation_value != c.effective_value]
    assert gap, "규정값 ≠ 실제값인 항목이 있어야 한다(T-대출-02)"
    for c in gap:
        w = " ".join(c.warnings(c.checked_at))
        assert "규정값" in w and "실제 적용값" in w, c.id
    # 실제값이 우선한다
    c = gap[0]
    assert c.usable_value() == c.effective_value


def test_시행일_미확인은_소급계산_금지를_알린다() -> None:
    """원장 101건 중 68건이 이 상태다. 숨기지 않는다."""
    consts = load(POLICY / "constants.yaml")
    unknown = [c for c in consts if c.status == "시행일확인"]
    assert unknown, "시행일 미확인 항목이 있어야 한다"
    assert all(c.effective_from is None for c in unknown)
    assert any("소급" in w for w in unknown[0].warnings(unknown[0].checked_at))


def test_확인필요는_직접확인을_요구한다() -> None:
    ltv = load(POLICY / "ltv.yaml")
    need = [c for c in ltv if c.status == "확인필요"]
    assert need
    for c in need:
        assert any("확인" in w for w in c.warnings(c.checked_at))
        # 값이 없으므로 계산에 쓸 수 없다 → 사용자 입력
        assert c.usable_value() is None


def test_L5_L6에_값을_실으면_거부한다() -> None:
    """규약 위반은 로드 단계에서 막는다."""
    try:
        Constant(id="X", name="n", layer="L6", basis="b",
                 checked_at=dt.date.today(), status="확인완료", value=0.1)
    except TypeError:
        raise AssertionError("dataclass 생성은 되어야 한다")
    # 로더 차원의 거부는 load()에서 — 임시 파일로 확인
    import tempfile
    bad = """items:
  - id: X-1
    name: "실무 관행 값"
    layer: L6
    basis: "업계 관행"
    checked_at: 2026-08-15
    status: 확인완료
    value: 0.02
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", encoding="utf-8", delete=False) as f:
        f.write(bad)
        p = f.name
    try:
        load(p)
    except ValueError as e:
        assert "L6" in str(e)
    else:
        raise AssertionError("L6에 값을 실었는데 거부되지 않았다")


def test_경고를_모아서_낼_수_있다() -> None:
    consts = load_all()
    future = dt.date(2027, 12, 31)          # 전부 만료된 시점
    ws = collect_warnings(consts, future)
    assert len(ws) >= len([c for c in consts if c.expires_at])


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
