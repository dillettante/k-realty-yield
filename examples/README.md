# examples

예제는 `tests/test_worked_examples.py`에 있다.
**그 파일이 예제이자 회귀 테스트다** — 전제와 기대값이 한 자리에 있어야
계산이 바뀌었을 때 어디서 어긋났는지 바로 드러나기 때문이다.

```bash
python3 tests/test_worked_examples.py
```

기대값은 전부 손계산으로 따로 구한 것이고, 코드 출력을 그대로 굳힌 것이
아니다 — 그러면 틀린 값도 통과한다.
