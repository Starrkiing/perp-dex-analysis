"""Offline tests: schema/units, missingness, duplicates, malformed payload, endpoint failure, partial day,
market grouping, rate-limit/backoff. No test touches the network (enforced by the no_network fixture)."""
import csv
import json
import socket
from datetime import datetime, timezone

import pytest

from collectors import SCHEMA_VERSION
from collectors.common import (CONTRACT_COLUMNS, Observation, append, fetch, fetch_json, exclude_incomplete_day,
                               dedupe, null_obs)
from collectors import venues as V
from collectors.history import parse_llama_series
from collectors.tokens import parse_coingecko
from collectors.annotations import turnover_indicator, incentive_annotations
from collectors.run import collect_venue
from . import fixtures as F

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*a, **k):
        raise RuntimeError("network access attempted in offline test")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def ctx(v):
    return V.Ctx(v, "https://example.invalid/" + v, "2026-10-24T15:00:00Z", "2026-10-24", "ab" * 32, 200)


def by_metric(obs):
    return {o.metric: o for o in obs}


# ------------------------------------------------------------------ schema / units
def test_contract_columns_exact():
    assert CONTRACT_COLUMNS == ["date_utc", "venue", "metric", "value", "unit", "period", "source_uri",
                                "fetched_at_utc", "coverage_status", "schema_version"]


@pytest.mark.parametrize("parser,payload,venue", [
    (V.parse_hyperliquid, F.HL, "hyperliquid"), (V.parse_extended, F.EXT, "extended"),
    (V.parse_lighter, F.LIGHTER, "lighter"), (V.parse_pacifica, F.PACIFICA, "pacifica"),
    (V.parse_aster, F.ASTER, "aster"), (V.parse_gmx, F.GMX, "gmx"), (V.parse_dydx, F.DYDX, "dydx"),
    (V.parse_variational, F.VARIATIONAL, "variational"), (V.parse_grvt, F.GRVT, "grvt")])
def test_every_venue_emits_full_metric_set_with_units(parser, payload, venue):
    obs = parser(payload, ctx(venue))
    assert [o.metric for o in obs] == V.SNAPSHOT_METRICS
    for o in obs:
        o.validate()
        assert o.schema_version == SCHEMA_VERSION and o.unit == V.UNITS[o.metric] and o.raw_sha256


def test_hyperliquid_units_oi_is_coins_times_mark():
    m = by_metric(V.parse_hyperliquid(F.HL, ctx("hyperliquid")))
    assert m[V.OI].value == 10 * 5 + 2 * 10 and m[V.VOL].value == 1500 and m[V.NMKT].value == 2


def test_gmx_30_decimal_usd():
    assert by_metric(V.parse_gmx(F.GMX, ctx("gmx")))[V.OI].value == 5.0


def test_validation_rejects_bad_records():
    with pytest.raises(ValueError):
        Observation("2026-10-24", "x", "m", 0.0, "USD", "point_in_time", "s", "t", "observed").validate()
    with pytest.raises(ValueError):
        Observation("2026-10-24", "x", "m", None, "USD", "point_in_time", "s", "t", "not_reported").validate()
    with pytest.raises(ValueError):
        Observation("2026-10-24", "x", "m", 1.0, "", "point_in_time", "s", "t", "observed").validate()
    with pytest.raises(ValueError):
        Observation("2026-10-24", "x", "m", 1.0, "USD", "weekly", "s", "t", "observed").validate()


# ------------------------------------------------------------------ missingness: null != zero != failed
def test_missing_metrics_are_null_with_reason_never_zero():
    m = by_metric(V.parse_gmx(F.GMX, ctx("gmx")))
    assert m[V.VOL].value is None and m[V.VOL].coverage_status == "not_reported" and m[V.VOL].null_reason
    assert m[V.TVL].coverage_status == "not_implemented"
    avg = m[V.OI_AVG]
    assert avg.value is None and "NOT substituted" in avg.null_reason  # current OI never masquerades as average


def test_reported_zero_is_status_zero():
    assert by_metric(V.parse_dydx(F.DYDX, ctx("dydx")))[V.VOL].coverage_status == "zero"


def test_unit_unverified_flag():
    m = by_metric(V.parse_pacifica(F.PACIFICA, ctx("pacifica")))
    assert m[V.VOL].coverage_status == "unit_unverified" and m[V.OI].value == 6.0


def test_tokens_without_listing_are_null_not_fabricated():
    obs = parse_coingecko(F.CG, "https://example.invalid/cg", "t", "2026-10-24")
    ext = [o for o in obs if o.venue == "extended"]
    assert ext and all(o.value is None and o.coverage_status in ("not_reported", "not_implemented") for o in ext)
    hl = {o.metric: o.value for o in obs if o.venue == "hyperliquid"}
    assert hl["token_fdv_usd"] == 10000.0 and hl["token_unlocks_next_30d"] is None


# ------------------------------------------------------------------ market grouping
def test_grouping_excludes_spot_inactive_delisted_and_dupes():
    assert by_metric(V.parse_lighter(F.LIGHTER, ctx("lighter")))[V.VOL].value == 100
    e = by_metric(V.parse_extended(F.EXT, ctx("extended")))
    assert e[V.VOL].value == 300 and e[V.NMKT].value == 1
    a = by_metric(V.parse_aster(F.ASTER, ctx("aster")))
    assert a[V.VOL].value == 10 and a[V.NMKT].value == 1
    assert by_metric(V.parse_grvt(F.GRVT, ctx("grvt")))[V.NMKT].value == 1
    d = by_metric(V.parse_dydx(F.DYDX, ctx("dydx")))
    assert d[V.NMKT].value == 1 and d[V.OI].value == 200


# ------------------------------------------------------------------ malformed payload / endpoint failure
@pytest.mark.parametrize("parser", [V.parse_hyperliquid, V.parse_extended, V.parse_lighter, V.parse_pacifica,
                                    V.parse_aster, V.parse_gmx, V.parse_dydx, V.parse_variational, V.parse_grvt])
def test_malformed_payload_raises(parser):
    with pytest.raises(V.MalformedPayload):
        parser({"unexpected": True} if parser is not V.parse_aster else {"x": 1}, ctx("x"))


def fake_transport(responses):
    calls = []

    def t(url, data, headers, timeout):
        calls.append(url)
        r = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r
    t.calls = calls
    return t


def venue(name):
    return next(v for v in V.VENUES if v.name == name)


def test_endpoint_failure_yields_fetch_failed_rows():
    t = fake_transport([(503, b"down")])
    obs, log = collect_venue(venue("hyperliquid"), NOW, None, transport=t, sleep=lambda s: None)
    assert len(t.calls) == 3 and log["http_status"] == 503
    assert all(o.coverage_status == "fetch_failed" and o.value is None for o in obs)


def test_html_response_is_fetch_failed_not_zero():
    t = fake_transport([(200, b"<!DOCTYPE html><html></html>")])
    obs, log = collect_venue(venue("edgex"), NOW, None, transport=t, sleep=lambda s: None)
    assert all(o.coverage_status == "fetch_failed" for o in obs)
    obs, log = collect_venue(venue("lighter"), NOW, None, transport=t, sleep=lambda s: None)
    assert all(o.coverage_status == "fetch_failed" for o in obs) and "non-JSON" in log["error"]


def test_malformed_json_via_collector_is_fetch_failed():
    t = fake_transport([(200, json.dumps({"status": "OK", "data": "oops"}).encode())])
    obs, log = collect_venue(venue("extended"), NOW, None, transport=t, sleep=lambda s: None)
    assert all(o.coverage_status == "fetch_failed" for o in obs) and "malformed" in log["error"]


def test_network_exception_handled():
    t = fake_transport([OSError("unreachable")])
    r = fetch("https://example.invalid", transport=t, sleep=lambda s: None)
    assert r.body is None and r.status is None and "OSError" in r.error and r.attempts == 3


# ------------------------------------------------------------------ rate limit / backoff
def test_rate_limit_backoff_bounded_and_recovers():
    slept = []
    t = fake_transport([(429, b""), (429, b""), (200, b"[1]")])
    r, payload, err = fetch_json("https://example.invalid", transport=t, sleep=slept.append,
                                 base_backoff=1.0, max_backoff=8.0)
    assert payload == [1] and r.attempts == 3 and slept == [1.0, 2.0]


def test_backoff_capped_and_attempts_bounded():
    slept = []
    t = fake_transport([(429, b"")])
    r = fetch("https://example.invalid", transport=t, sleep=slept.append, max_attempts=5, base_backoff=4, max_backoff=8)
    assert r.attempts == 5 and len(t.calls) == 5 and max(slept) == 8 and r.body is None


def test_non_retryable_status_not_retried():
    t = fake_transport([(404, b"")])
    r = fetch("https://example.invalid", transport=t, sleep=lambda s: None)
    assert len(t.calls) == 1 and r.status == 404


# ------------------------------------------------------------------ partial day & history
def test_partial_current_utc_day_excluded():
    obs = parse_llama_series(F.LLAMA_HL_FEES, "hyperliquid", "fees_usd", "u", "t",
                             datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
    assert [o.date_utc for o in obs] == ["2026-10-21", "2026-10-22"]
    assert obs[1].coverage_status == "zero"


def test_exclude_incomplete_day_helper_keeps_snapshots():
    snap = null_obs("x", "m", "USD", "point_in_time", "s", "t", "2026-10-24", "not_reported", "r")
    day = null_obs("x", "m", "USD", "completed_utc_day", "s", "t", "2026-10-24", "not_reported", "r")
    assert exclude_incomplete_day([snap, day], NOW) == [snap]


def test_extended_post_arc_zero_flagged_as_coverage_gap():
    obs = parse_llama_series(F.LLAMA_EXT_FEES, "extended", "fees_usd", "u", "t", NOW + (NOW - NOW))
    st = {o.date_utc: o.coverage_status for o in obs}
    assert st == {"2026-10-21": "observed", "2026-10-22": "observed", "2026-10-23": "zero_suspected_gap"}


def test_malformed_history_raises():
    with pytest.raises(ValueError):
        parse_llama_series({"totalDataChart": [[1, 2, 3]]}, "x", "fees_usd", "u", "t", NOW)


# ------------------------------------------------------------------ duplicates & append-only
def test_dedupe_and_append_only(tmp_path):
    hist = parse_llama_series(F.LLAMA_HL_FEES, "hyperliquid", "fees_usd", "u", "2026-10-24T15:00:00Z", NOW)
    assert append(hist + hist, tmp_path) == 3
    jl = (tmp_path / "observations.jsonl").read_text()
    # re-run with a later fetch time: completed days are immutable -> nothing new appended, file only grows
    later = parse_llama_series(F.LLAMA_HL_FEES, "hyperliquid", "fees_usd", "u", "2026-10-25T15:00:00Z", NOW)
    assert append(later, tmp_path) == 0
    assert (tmp_path / "observations.jsonl").read_text() == jl
    snaps = V.parse_dydx(F.DYDX, ctx("dydx"))
    assert append(snaps, tmp_path) == 5
    assert (tmp_path / "observations.jsonl").read_text().startswith(jl)
    rows = list(csv.DictReader(open(tmp_path / "observations.csv")))
    assert len(rows) == 8 and list(rows[0])[:10] == CONTRACT_COLUMNS
    nulls = [r for r in rows if r["value"] == ""]
    assert nulls and all(r["null_reason"] for r in nulls)
    assert len(dedupe(snaps + snaps)) == 5


# ------------------------------------------------------------------ annotations
def test_turnover_indicator_and_incentives():
    snap = V.parse_hyperliquid(F.HL, ctx("hyperliquid")) + V.parse_gmx(F.GMX, ctx("gmx"))
    t = {o.venue: o for o in turnover_indicator(snap, "t", "2026-10-24")}
    assert t["hyperliquid"].value == pytest.approx(1500 / 70) and t["gmx"].value is None
    inc = incentive_annotations("t", "2026-10-24")
    assert all(o.source_uri.startswith("https://") for o in inc)


def test_cli_refuses_without_live():
    from collectors.run import main
    with pytest.raises(SystemExit):
        main([])
