"""Independent Acting Captain regression tests for collector review, offline only."""
import json
import math
from datetime import datetime, timezone

import pytest

from collectors.common import Observation, append, obs_value
from collectors.run import collect_history, collect_tokens
from collectors.venues import Ctx, parse_extended, parse_hyperliquid
from tests.collector_tests.fixtures import EXT, HL


def test_historical_revision_appended_without_overwriting_original(tmp_path):
    base = obs_value("extended", "fees_usd", 100.0, "USD", "completed_utc_day",
                     "https://example.invalid/fees", "2026-11-01T12:00:00Z", "2026-10-30",
                     kind="aggregator_api")
    revised = obs_value("extended", "fees_usd", 105.0, "USD", "completed_utc_day",
                        base.source_uri, "2026-11-02T12:00:00Z", base.date_utc, kind="aggregator_api")
    recovered = obs_value("extended", "fees_usd", 0.0, "USD", "completed_utc_day",
                          base.source_uri, "2026-11-03T12:00:00Z", base.date_utc, kind="aggregator_api")
    assert append([base], tmp_path) == 1
    assert append([revised], tmp_path) == 1
    assert append([revised], tmp_path) == 0
    assert append([recovered], tmp_path) == 1
    rows = [json.loads(x) for x in (tmp_path/"observations.jsonl").read_text().splitlines()]
    assert [x["value"] for x in rows] == [100.0, 105.0, 0.0]
    assert [x["fetched_at_utc"] for x in rows] == [
        "2026-11-01T12:00:00Z", "2026-11-02T12:00:00Z", "2026-11-03T12:00:00Z"]


def test_provider_missing_active_market_does_not_publish_false_full_total():
    m = json.loads(json.dumps(HL))
    m[1][1].pop("dayNtlVlm")
    ctx = Ctx("hyperliquid", "https://example.invalid/info", "2026-11-01T12:00:00Z",
              "2026-11-01", None, 200)
    rows = {o.metric:o for o in parse_hyperliquid(m, ctx)}
    assert rows["perp_volume_24h_usd"].value is None
    assert rows["perp_volume_24h_usd"].coverage_status == "not_reported"
    assert rows["open_interest_usd"].value == 70.0


def test_extended_oi_not_accepted_as_verified_usd():
    ctx = Ctx("extended", "https://example.invalid/markets", "2026-11-01T12:00:00Z",
              "2026-11-01", None, 200)
    oi = {o.metric:o for o in parse_extended(EXT, ctx)}["open_interest_usd"]
    assert oi.value == 40
    assert oi.coverage_status == "unit_unverified"


def test_nonfinite_and_negative_size_rejected():
    for v in (float("nan"), float("inf"), -5., True):
        with pytest.raises(ValueError):
            Observation("2026-10-30", "x", "open_interest_usd", v, "USD",
                        "point_in_time", "src", "2026-11-01T12:00:00Z", "observed").validate()


def test_failed_historical_402_is_recorded_on_last_completed_day():
    now = datetime(2026, 11, 1, 22, 0, tzinfo=timezone.utc)
    def unavailable(url, data, headers, timeout):
        return 402, b'payment required'
    rows, logs = collect_history(now, None, history_days=2, transport=unavailable,
                                 sleep=lambda _:None)
    assert len(rows) == 40
    assert all(o.coverage_status == "not_reported" for o in rows)
    assert all(o.date_utc == "2026-10-31" for o in rows)
    assert any(o.metric == "perp_volume_usd" and o.venue=="extended" for o in rows)


def test_failed_token_fetch_keeps_explicit_failure_rows():
    now = datetime(2026, 11, 1, 22, 0, tzinfo=timezone.utc)
    def unavailable(url, data, headers, timeout):
        return 503, b'service unavailable'
    rows,log = collect_tokens(now, None, transport=unavailable, sleep=lambda _:None)
    assert len(rows) == 50
    assert all(o.coverage_status == "fetch_failed" and o.value is None for o in rows)
    assert log["http_status"] == 503
