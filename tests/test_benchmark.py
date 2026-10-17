import pytest

from benchmark import empirical_percentile, rank_in_group, summarize


def test_median_of_odd_group():
    result = summarize([10.0, 20.0, 30.0])
    assert result["median"] == pytest.approx(20.0)


def test_rank_direction_lower_is_better():
    # 15 is 2nd best among [10, 15, 30] when lower is better.
    assert rank_in_group(15.0, [10.0, 15.0, 30.0], "lower_is_better") == 2


def test_rank_direction_higher_is_better():
    assert rank_in_group(15.0, [10.0, 15.0, 30.0], "higher_is_better") == 2


def test_percentile_lower_is_better():
    # value equals median -> 50th percentile
    assert empirical_percentile(20.0, [10.0, 20.0, 30.0], "lower_is_better") == pytest.approx(50.0)
    # best value -> 100th percentile when lower is better
    assert empirical_percentile(10.0, [10.0, 20.0, 30.0], "lower_is_better") == pytest.approx(100.0)


def test_percentile_higher_is_better():
    assert empirical_percentile(30.0, [10.0, 20.0, 30.0], "higher_is_better") == pytest.approx(100.0)


def test_summarize_includes_provenance_fields():
    result = summarize([10.0, 20.0, 30.0])
    assert result["count"] == 3
    assert "median" in result
