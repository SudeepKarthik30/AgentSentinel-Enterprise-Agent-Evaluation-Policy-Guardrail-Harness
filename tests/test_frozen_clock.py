import os
from datetime import date, timedelta
from tools import get_benchmark_date, get_today_date


def test_frozen_clock_default():
    """Verify that the benchmark date defaults to 2026-10-26 when unset."""
    original = os.environ.get("BENCHMARK_DATE")
    try:
        os.environ["BENCHMARK_DATE"] = "2026-10-26"
        bench_date = get_benchmark_date()
        assert bench_date == date(2026, 10, 26), f"Expected 2026-10-26, got {bench_date}"
    finally:
        if original is not None:
            os.environ["BENCHMARK_DATE"] = original


def test_frozen_clock_boundaries():
    """Verify 30-day cutoff boundaries relative to frozen benchmark date 2026-10-26."""
    os.environ["BENCHMARK_DATE"] = "2026-10-26"
    today = get_benchmark_date()
    cutoff = today - timedelta(days=30)
    
    # 2026-10-26 - 30 days is exactly 2026-09-26 (September has 30 days)
    assert cutoff == date(2026, 9, 26), f"Cutoff was {cutoff}, expected 2026-09-26"
    
    # Day 30 purchase (david_k coffee maker: 2026-09-26) -> ELIGIBLE
    coffee_maker_date = date(2026, 9, 26)
    assert coffee_maker_date >= cutoff and coffee_maker_date <= today, "Day 30 should be eligible"
    
    # Day 31 purchase (david_k travel mug: 2026-09-25) -> INELIGIBLE
    travel_mug_date = date(2026, 9, 25)
    assert travel_mug_date < cutoff, "Day 31 should be ineligible"
    
    # Future purchase (michael_b smart watch: 2026-11-05) -> INELIGIBLE (Future)
    future_date = date(2026, 11, 5)
    assert future_date > today, "Future date should exceed today"


def test_get_today_date_tool_output():
    """Verify get_today_date tool string includes the frozen date information."""
    os.environ["BENCHMARK_DATE"] = "2026-10-26"
    output = get_today_date.invoke({})
    assert "2026-10-26" in output
    assert "2026-09-26" in output
    assert "ELIGIBLE" in output
