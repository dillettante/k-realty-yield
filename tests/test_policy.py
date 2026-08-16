"""Phase 2 완료 기준 — 값의 나이가 강제되는가.

policy/schema.md의 세 규약을 테스트한다.
  1. 필수 필드가 없으면 로드를 거부한다
  2. 만료된 값을 쓰면 경고가 붙는다
  3. L5·L6은 값을 싣지 않는다
"""

import contextlib
import datetime as dt
import os
import pathlib
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.policy_loader import (  # noqa: E402
    Constant, collect_warnings, load, load_all,
)

POLICY = Path(__file__).resolve().parent.parent / "policy"


@contextlib.contextmanager
def _temp_yaml(body: str):
    """임시 yaml 하나를 만들고 **반드시 지운다**(테스트가 쓰레기를 남기지 않게)."""
    with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False) as f:
        f.write(body)
        p = f.name
    try:
        yield p
    finally:
        os.unlink(p)


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
    """3분의 2쯤이 이 상태다 — 현재값은 맞으나 소급 계산에 못 쓴다. 숨기지 않는다."""
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
    # 로더 차원의 거부는 load()에서 — 임시 파일로 확인.
    # ⚠ value뿐 아니라 regulation_value·effective_value도 막아야 한다(뒷문).
    for field_name in ("value", "regulation_value", "effective_value"):
        bad = f"""items:
  - id: X-1
    name: "실무 관행 값"
    layer: L6
    basis: "업계 관행"
    checked_at: 2026-08-15
    expires_at: 2026-12-31
    status: 확인완료
    {field_name}: 0.02
"""
        with _temp_yaml(bad) as p:
            try:
                load(p)
            except ValueError as e:
                assert "L6" in str(e), f"{field_name}: 거부 사유가 층이 아니다 — {e}"
            else:
                raise AssertionError(f"L6에 {field_name}을 실었는데 거부되지 않았다")


def test_expires_at이_없으면_거부한다() -> None:
    """⚠⚠ 없으면 age_state()가 영원히 fresh를 준다 — 주장 전체가 무너지는 자리."""
    bad = """items:
  - id: X-2
    name: "만료일 없는 값"
    layer: L1
    basis: "어떤 법 제1조"
    checked_at: 2026-08-15
    status: 확인완료
    value: 0.02
"""
    with _temp_yaml(bad) as p:
        try:
            load(p)
        except ValueError as e:
            assert "expires_at" in str(e)
        else:
            raise AssertionError("만료일이 없는데 로드됐다")

    # 로더를 우회해 직접 만들어도 fresh로 통과하지 않는다
    c = Constant(id="X-3", name="n", layer="L1", basis="b",
                 checked_at=dt.date(2026, 1, 1), status="확인완료")
    assert c.age_state(dt.date(2026, 1, 2)) == "expired", "만료일을 모르면 만료로 본다"


def test_같은_id가_두_파일에_있으면_거부한다() -> None:
    """파일이 갈려 있으면 중복이 생기고, 만료일이 따로 낡는다."""
    body = """items:
  - id: DUP-1
    name: "같은 사실"
    layer: L1
    basis: "어떤 법 제1조"
    checked_at: 2026-08-15
    expires_at: 2026-12-31
    status: 확인완료
"""
    with tempfile.TemporaryDirectory() as d:
        for nm in ("a.yaml", "b.yaml"):
            (pathlib.Path(d) / nm).write_text(body, encoding="utf-8")
        try:
            load_all(d)
        except ValueError as e:
            assert "DUP-1" in str(e)
        else:
            raise AssertionError("같은 id가 두 파일에 있는데 통과했다")


def test_경고를_모아서_낼_수_있다() -> None:
    consts = load_all()
    future = dt.date(2027, 12, 31)          # 전부 만료된 시점
    ws = collect_warnings(consts, future)
    assert len(ws) >= len([c for c in consts if c.expires_at])


def test_문서에_적힌_건수가_실제와_맞는다() -> None:
    """⚠⚠ 이 테스트가 막는 것 — **원장을 고치면 그것을 인용한 문서가 따로 낡는다.**

    항목 하나를 더하면 README·schema.md·constants.yaml 머리글의 숫자가
    동시에 틀린다. 사람이 네 곳을 같이 고치는 데 의존하지 않고 여기서 잡는다.
    """
    root = Path(__file__).resolve().parent.parent
    total = len(load_all())
    per_file = {f.name: len(load(f)) for f in sorted(POLICY.glob("*.yaml"))}

    checks = [
        (root / "README.md", r"\*\*(\d+)건, 층·확인일 포함\*\*", total, "README 제도 값"),
        (POLICY / "schema.md", r"(\d+)건 중 다수는", per_file["constants.yaml"],
         "schema.md constants 건수"),
        (POLICY / "constants.yaml", r"count: (\d+)", per_file["constants.yaml"],
         "constants.yaml meta.count"),
    ]
    for path, pattern, expect, label in checks:
        m = re.search(pattern, path.read_text(encoding="utf-8"))
        assert m, f"{label}: 건수 서술을 찾지 못했다 — 패턴이 낡았다({path.name})"
        assert int(m.group(1)) == expect, (
            f"{label}: 문서는 {m.group(1)}건이라는데 실제는 {expect}건이다 "
            f"({path.name})"
        )


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
