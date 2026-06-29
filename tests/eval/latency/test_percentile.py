from eval.latency.run import _percentile, _summ


def test_percentile_endpoints():
    values = [10, 20, 30, 40, 50]
    assert _percentile(values, 0) == 10
    assert _percentile(values, 100) == 50
    assert _percentile(values, 50) == 30


def test_percentile_interpolates():
    # p95 of 1..100 lies between 95 and 96.
    values = list(range(1, 101))
    assert 95.0 <= _percentile(values, 95) <= 96.0


def test_summ_shapes():
    s = _summ([5.0, 15.0, 25.0])
    assert s["n"] == 3
    assert s["mean"] == 15.0
