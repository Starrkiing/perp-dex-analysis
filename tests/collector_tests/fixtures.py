"""SYNTHETIC OFFLINE FIXTURES. Shapes mirror real public responses observed 2026-11-01; numbers are
test values only and must never be read as market data."""
HL = [{"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "MATIC", "isDelisted": True}]},
      [{"dayNtlVlm": "1000", "markPx": "10", "openInterest": "5"},
       {"dayNtlVlm": "500", "markPx": "2", "openInterest": "10"},
       {"dayNtlVlm": "999999", "markPx": "1", "openInterest": "999999"}]]
EXT = {"status": "OK", "data": [
    {"name": "BTC-USD", "type": "PERPETUAL", "active": True, "status": "ACTIVE",
     "marketStats": {"dailyVolume": "300", "openInterest": "40"}},
    {"name": "BTC-USD", "type": "PERPETUAL", "active": True, "status": "ACTIVE",
     "marketStats": {"dailyVolume": "300", "openInterest": "40"}},  # duplicate listing
    {"name": "OLD-USD", "type": "PERPETUAL", "active": False, "status": "DELISTED",
     "marketStats": {"dailyVolume": "77", "openInterest": "77"}}]}
LIGHTER = {"code": 200, "order_book_details": [
    {"market_id": 1, "market_type": "perp", "status": "active", "daily_quote_token_volume": 100, "open_interest_usd": "20"},
    {"market_id": 2, "market_type": "perp", "status": "inactive", "daily_quote_token_volume": 9, "open_interest_usd": "9"},
    {"market_id": 3, "market_type": "spot", "status": "active", "daily_quote_token_volume": 9, "open_interest_usd": "9"}],
    "spot_order_book_details": [{"market_id": 4}]}
PACIFICA = {"success": True, "data": [{"symbol": "SOL", "mark": "2", "open_interest": "3", "volume_24h": "50"}]}
ASTER = [{"symbol": "BTCUSDT", "quoteVolume": "10"}, {"symbol": "BTCUSDT", "quoteVolume": "10"},
         {"symbol": "ETHUSDC", "quoteVolume": "5"}]
GMX = {"markets": [{"marketToken": "0xa", "isListed": True, "openInterestLong": str(3 * 10**30),
                    "openInterestShort": str(2 * 10**30)},
                   {"marketToken": "0xb", "isListed": False, "openInterestLong": str(10**33), "openInterestShort": "0"}]}
DYDX = {"markets": {"BTC-USD": {"status": "ACTIVE", "volume24H": "0", "oraclePrice": "100", "openInterest": "2"},
                    "X-USD": {"status": "FINAL_SETTLEMENT", "volume24H": "5", "oraclePrice": "1", "openInterest": "1"}}}
VARIATIONAL = {"total_volume_24h": "10", "open_interest": "20", "tvl": "30", "num_markets": 4}
GRVT = {"result": [{"instrument": "BTC_USDT_Perp", "kind": "PERPETUAL"}, {"instrument": "BTC_USDT_Perp", "kind": "PERPETUAL"},
                   {"instrument": "BTC_Call", "kind": "CALL"}]}
DAY = 86400
T0 = 1792540800  # 2026-10-21T00:00:00Z
LLAMA_EXT_FEES = {"chains": ["Starknet"], "totalDataChart": [[T0, 58342], [T0 + DAY, 28629], [T0 + 2 * DAY, 0],
                                                             [T0 + 3 * DAY, 0]]}
LLAMA_HL_FEES = {"chains": ["Hyperliquid L1"], "totalDataChart": [[T0, 100], [T0 + DAY, 0], [T0 + 2 * DAY, 300]]}
CG = [{"id": "hyperliquid", "current_price": 10.0, "circulating_supply": 100.0, "total_supply": 1000.0,
       "fully_diluted_valuation": 10000.0, "market_cap": 1000.0}]
