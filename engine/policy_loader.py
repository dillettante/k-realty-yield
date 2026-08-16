"""policy/ 로더 — 값의 나이를 강제한다.

이 모듈이 이 repo의 차별점이다. 계산은 어디에나 있지만
**「이 숫자가 언제 것인지」를 결과에 끌고 다니는 계산기**는 드물다.

세 가지를 강제한다(policy/schema.md).
  1. 필수 필드가 없으면 **로드를 거부한다.**
  2. 만료된 값을 쓰면 **경고가 붙는다.** 계산은 막지 않는다 —
     막으면 사용자가 더 낡은 계산기로 가기 때문이다.
  3. `L5`·`L6`은 값을 싣지 않는다. 사용자 입력으로만 받는다.

의존 없음. PyYAML을 쓰지 않고 필요한 만큼만 파싱한다
(power-plan-db의 "stdlib only" 관행).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent.parent / "policy"

# ⚠⚠ expires_at이 여기 있어야 하는 이유 —
#    없으면 age_state()가 그 값을 **영원히 「fresh」로 본다.**
#    「값의 나이를 준다」는 이 repo의 주장이 통째로 선택 사항이 된다.
REQUIRED = ("id", "name", "layer", "basis", "checked_at", "expires_at", "status")
GRACE_DAYS = 30          # 만료 후 이 기간까지는 경고만, 넘으면 강조
NO_VALUE_LAYERS = ("L5", "L6")


@dataclass
class Constant:
    """제도 값 하나. 값보다 메타데이터가 많은 것이 정상이다."""

    id: str
    name: str
    layer: str
    basis: str
    checked_at: dt.date
    status: str
    rule: str = ""
    section: str = ""
    value: float | None = None
    effective_from: dt.date | None = None
    expires_at: dt.date | None = None
    regulation_value: float | None = None   # L4 — 규정집의 값
    effective_value: float | None = None    # L4 — 실제 적용값
    source: str | None = None
    source_url: str | None = None
    note: str = ""

    def age_state(self, today: dt.date | None = None) -> str:
        """`fresh` / `stale` / `expired` 중 하나."""
        today = today or dt.date.today()
        if self.expires_at is None:
            # 로더가 막지만, 직접 만든 Constant는 여기로 온다.
            # ⚠ 「모르면 신선하다」가 아니라 「모르면 만료」다 — 조용히 통과시키지 않는다.
            return "expired"
        if today <= self.expires_at:
            return "fresh"
        if (today - self.expires_at).days <= GRACE_DAYS:
            return "stale"
        return "expired"

    def warnings(self, today: dt.date | None = None) -> list[str]:
        """이 값을 쓸 때 결과에 붙어야 할 경고. 빈 리스트면 조용하다."""
        out: list[str] = []
        state = self.age_state(today)
        if state == "stale":
            out.append(
                f"[{self.id}] {self.name} — {self.checked_at} 확인분이고 "
                f"{self.expires_at}에 만료됐습니다. 출처에서 재확인하세요."
            )
        elif state == "expired":
            out.append(
                f"[{self.id}] ⚠ {self.name} — {self.expires_at} 만료 후 "
                f"{GRACE_DAYS}일이 지났습니다. **직접 입력하십시오.**"
            )
        # L4는 규정값과 실제값이 다를 수 있다 — 다르면 반드시 알린다
        if (self.regulation_value is not None
                and self.effective_value is not None
                and self.regulation_value != self.effective_value):
            out.append(
                f"[{self.id}] ⚠⚠ 규정값 {self.regulation_value:.0%} ≠ "
                f"실제 적용값 {self.effective_value:.0%} — 조문만 보면 틀립니다."
            )
        if self.status == "확인필요":
            out.append(f"[{self.id}] ⚠ 근거를 확인하지 못한 항목입니다. 직접 확인하세요.")
        if self.status == "개정예정":
            out.append(f"[{self.id}] 개정이 예정돼 있습니다. 사용 전 재확인하세요.")
        if self.effective_from is None and self.status == "시행일확인":
            out.append(
                f"[{self.id}] 시행일 미확인 — 현재값은 맞으나 **소급 계산에 쓸 수 없습니다.**"
            )
        return out

    def usable_value(self) -> float | None:
        """계산에 쓸 수 있는 값. 없으면 None이고, 그러면 사용자에게 되묻는다."""
        if self.layer in NO_VALUE_LAYERS:
            return None                      # 규약상 값을 싣지 않는다
        if self.effective_value is not None:  # L4는 실제값이 우선
            return self.effective_value
        return self.value


# ---------------------------------------------------------------- 파싱

def _scalar(raw: str):
    """YAML 스칼라 최소 해석 — null·숫자·따옴표 문자열·날짜."""
    v = raw.strip()
    if v.startswith("#") or v == "" or v == "null":
        return None
    v = re.sub(r"\s+#.*$", "", v).strip()          # 줄 끝 주석
    if v in ("null", ""):
        return None
    if v[:1] in "\"'" and v[-1:] in "\"'":
        return v[1:-1]
    if v == ">":                                    # 접힌 블록은 다음 줄들이 채운다
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return dt.date.fromisoformat(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _parse_items(text: str) -> list[dict]:
    """`- key: value` 목록만 뽑는다. 중첩 매핑은 쓰지 않으므로 이걸로 충분하다."""
    items: list[dict] = []
    cur: dict | None = None
    pending_key: str | None = None
    for line in text.splitlines():
        if re.match(r"^\s*#", line) or not line.strip():
            continue
        m = re.match(r"^\s*-\s+(\w+):\s*(.*)$", line)
        if m:                                        # 새 항목 시작
            if cur:
                items.append(cur)
            cur = {m.group(1): _scalar(m.group(2))}
            pending_key = m.group(1) if m.group(2).strip() == ">" else None
            continue
        m = re.match(r"^\s{4,}(\w+):\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = _scalar(m.group(2))
            pending_key = m.group(1) if m.group(2).strip() == ">" else None
            continue
        if pending_key and cur is not None:          # 접힌 블록 본문
            cur[pending_key] = (str(cur[pending_key]) + " " + line.strip()).strip()
    if cur:
        items.append(cur)
    return items


def load(path: Path | str) -> list[Constant]:
    """한 파일을 읽는다. 필수 필드가 없으면 **거부한다**(schema.md 규약)."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    body = raw.split("constants:", 1)[-1].split("items:", 1)[-1]
    out: list[Constant] = []
    for d in _parse_items(body):
        missing = [k for k in REQUIRED if d.get(k) in (None, "")]
        if missing:
            raise ValueError(f"{path.name} · {d.get('id', '?')}: 필수 필드 없음 {missing}")
        # L5·L6은 어느 이름으로도 값을 싣지 않는다(value만 막으면 뒷문이 남는다)
        laid = [k for k in ("value", "regulation_value", "effective_value")
                if d.get(k) is not None]
        if d["layer"] in NO_VALUE_LAYERS and laid:
            raise ValueError(
                f"{path.name} · {d['id']}: {d['layer']}에 값을 실을 수 없다 (실린 것: {laid})"
            )
        out.append(Constant(**{k: v for k, v in d.items()
                               if k in Constant.__dataclass_fields__}))
    return out


def load_all(policy_dir: Path | str = POLICY_DIR) -> list[Constant]:
    """policy/의 모든 yaml을 읽는다.

    ⚠ 파일이 갈려 있으므로 **같은 id가 두 파일에 들어가기 쉽다.** 그러면
    같은 사실이 두 번 세어지고 만료일이 따로 낡는다 — 여기서 막는다.
    """
    d = Path(policy_dir)
    out: list[Constant] = []
    seen: dict[str, str] = {}
    for f in sorted(d.glob("*.yaml")):
        for c in load(f):
            if c.id in seen:
                raise ValueError(
                    f"id 중복: {c.id} — {seen[c.id]}와 {f.name}에 모두 있다. "
                    "한 사실은 한 파일에만 둔다."
                )
            seen[c.id] = f.name
            out.append(c)
    return out


def collect_warnings(consts: list[Constant], today: dt.date | None = None) -> list[str]:
    """계산 결과에 붙일 경고를 모은다. **이 목록을 지우고 출력하지 말 것.**"""
    out: list[str] = []
    for c in consts:
        out.extend(c.warnings(today))
    return out
