from app.pricing import estimate
from app.stats import calibration, funnel, hours_histogram, market_by_skill, market_price, quantile


def test_minimum_uses_realistic_hours_and_comfort_uses_buffer(sample_analysis):
    est = estimate(sample_analysis, 1500, 200, 1.5)
    assert est.realistic_hours == 10 and est.buffered_hours == 15
    assert est.min_price == 2000
    assert est.options[-1].label == "комфортна" and est.options[-1].price == 3000
    assert est.budget_below_min
    assert all(o.price % 50 == 0 for o in est.options)


def test_estimate_adds_market_option(sample_analysis):
    est = estimate(sample_analysis, None, 200, 1.5, (6000, 11))
    assert [o.label for o in est.options] == ["мінімальна", "ринкова", "комфортна"]
    assert est.market_samples == 11 and est.budget_option is None


def test_quantile():
    assert quantile([1, 2, 3, 4, 5], 0.5) == 3
    assert quantile([10, 20], 0.25) == 12.5


def test_market_price_needs_enough_samples():
    rows = [("[22]", 1000.0 * i) for i in range(1, 12)] + [("[22]", None), ("[45]", 99999.0)]
    assert market_price(rows, {22}) == (6000, 11)
    assert market_price(rows[:5], {22}) is None
    by_skill = market_by_skill(rows, [22, 180])
    assert by_skill[0]["count"] == 12 and by_skill[0]["with_budget"] == 11
    assert by_skill[1]["count"] == 0


def test_hours_histogram_in_kyiv_time():
    hist = hours_histogram(["2026-10-29T08:30:00+00:00", "bad", None])
    assert sum(hist) == 1 and hist[10] == 1


def test_funnel_and_calibration():
    bids = [("submitted", 1000, None, None), ("won", 2000, 5, 8), ("lost", None, None, None), ("done", 3000, 10, 12)]
    f = funnel(bids)
    assert f["total"] == 4 and f["won"] == 2 and f["conversion"] == 67 and f["avg_price"] == 2000
    cal = calibration(bids)
    assert cal["count"] == 2 and cal["ratio"] == 1.33


def test_analyzer_refresh_skips_cache():
    from app.analysis import BidAnalyzer
    from app.llm import ToolResult
    from conftest import make_project, run

    class DB:
        saved = []

        async def get_analysis(self, pid):
            return {"cached": True}

        async def analyses_today(self):
            return 0

        async def save_analysis(self, *args):
            self.saved.append(args[0])

    class LLM:
        async def call_tool(self, *args):
            return ToolResult({"fresh": True}, "m", 1, 1, 0)

    analyzer = BidAnalyzer(LLM(), DB(), __import__("pathlib").Path("profile.yaml"), 5)
    assert run(analyzer.analyze(make_project(1), None)).cached
    record = run(analyzer.analyze(make_project(1), None, refresh=True))
    assert not record.cached and record.data == {"fresh": True}
