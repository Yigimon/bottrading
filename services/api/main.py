"""Dashboard-API: Wallets, Bot-Details, Strategien, Master-Bot, System und Steuerung.

Der Wallet-Zustand wird aus den gespeicherten Fills mit demselben PaperBroker berechnet wie im Bot-Service.
Schreibende Endpunkte (Pause, Kill-Switch) sind nur per POST mit Header `X-Requested-With` und passender Origin erlaubt;
das Dashboard hört ausschließlich auf localhost (SSH-Tunnel).
"""
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

from tradebot_core.metrics import daily_returns, max_drawdown, sharpe, trade_stats
from tradebot_core.models import Side
from tradebot_core.state import add_event, broker_for, latest_prices, now_ms

import lab
from catalog import STRATEGY_CATALOG
from tradebot_core.docs import INDICATORS, METRICS, PARAMS, strategy_param_docs, wallet_param_docs
from tradebot_core.indicators import ATR, EMA, RSI, Window
from tradebot_core.strategy import STRATEGIES

DATABASE_URL = os.environ["DATABASE_URL"]
R = redis.Redis.from_url(os.environ["REDIS_URL"])
SYMBOLS = os.environ["SYMBOLS"].split(",")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Tradebot Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def f(x):
    return None if x is None else float(x)


def js(x):
    """Wert aus JSONB (psycopg liefert bereits Python-Objekte) unverändert durchreichen."""
    return x


# ------------------------------------------------------------------ Grundlagen
def control_state(conn) -> dict:
    rows = conn.execute("SELECT key, value, reason, updated_at FROM control").fetchall()
    return {r["key"]: r for r in rows}


def wallet_metrics(conn, a: dict, prices: dict) -> dict:
    b = broker_for(conn, a, prices)
    snaps = conn.execute("SELECT ts, equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall()
    start, eq = float(a["start_cash"]), float(b.equity())
    times, vals = [s["ts"] for s in snaps], [float(s["equity"]) for s in snaps]
    sells = [x for x in b.fills if x.side == Side.SELL]
    ts = trade_stats([float(x.realized_pnl) for x in sells])
    positions = []
    for s, p in b.positions.items():
        px = float(b.prices[s])
        positions.append({"symbol": s, "qty": float(p.qty), "avg_cost": float(p.avg_cost), "price": px,
                          "value": float(p.qty) * px, "unrealized": float(p.qty) * px - float(p.cost),
                          "unrealized_pct": (float(p.qty) * px) / float(p.cost) - 1 if p.cost else None})
    invested = sum(p["value"] for p in positions)
    turnover = sum(float(x.qty * x.price) for x in b.fills)
    return {
        "name": a["name"], "strategy": a["strategy"], "interval": a["interval"], "start_cash": start, "equity": eq,
        "return": eq / start - 1, "cash": float(b.cash), "invested": invested, "exposure": invested / eq if eq else 0.0,
        "realized_pnl": float(b.realized_pnl), "unrealized_pnl": sum(p["unrealized"] for p in positions),
        "fees": float(b.fees_paid), "turnover": turnover, "n_fills": len(b.fills),
        "max_drawdown": max_drawdown(start, vals + [eq]), "sharpe": sharpe(start, times, vals) if len(vals) > 3 else None,
        **{k: (None if v == float("inf") else v) for k, v in ts.items()},
        "positions": positions, "since": int(a["created_at"].timestamp() * 1000), "params": a["params"],
    }


ACCOUNT_SQL = "SELECT id, name, start_cash, strategy, interval, created_at, params FROM accounts"


def params_match(run_params: dict | None, wanted: dict) -> bool:
    """Gespeicherter Backtest passt zu einer Parametrisierung, wenn alle gemeinsamen Parameter gleich sind."""
    rp = run_params or {}
    return all(float(rp[k]) == float(v) for k, v in wanted.items() if k in rp and isinstance(v, (int, float)) and not isinstance(v, bool))


# ------------------------------------------------------------------ Lesende Endpunkte
@app.get("/api/health")
def health():
    now = time.time()
    beats = {}
    for svc in ("market-data", "bots", "master"):
        v = R.get(f"heartbeat:{svc}")
        beats[svc] = round(now - float(v), 1) if v else None
    with db() as conn:
        last = conn.execute("SELECT max(close_time) AS t FROM candles WHERE interval='15m'").fetchone()["t"]
        ctrl = control_state(conn)
    candle_age = round(now - last / 1000, 1) if last else None
    ok = all(a is not None and a < 60 for a in beats.values()) and candle_age is not None and candle_age < 1500
    return {"ok": ok, "heartbeat_age_s": beats, "last_15m_candle_age_s": candle_age, "server_time": int(now * 1000),
            "kill_switch": "kill" in ctrl}


@app.get("/api/prices")
def prices():
    with db() as conn:
        return latest_prices(conn, SYMBOLS)


@app.get("/api/wallets")
def wallets():
    with db() as conn:
        prices_, ctrl = latest_prices(conn, SYMBOLS), control_state(conn)
        out = []
        for a in conn.execute(ACCOUNT_SQL + " ORDER BY name").fetchall():
            m = wallet_metrics(conn, a, prices_)
            m["paused"] = f"pause:{a['name']}" in ctrl or "kill" in ctrl
            m["pause_reason"] = (ctrl.get(f"pause:{a['name']}") or {}).get("reason")
            out.append(m)
    return out


@app.get("/api/equity")
def equity():
    """Verlauf je Wallet in Prozent zum Startkapital."""
    now, out = now_ms(), {}
    with db() as conn:
        prices_ = latest_prices(conn, SYMBOLS)
        for a in conn.execute(ACCOUNT_SQL + " ORDER BY name").fetchall():
            start = float(a["start_cash"])
            pts = [[int(a["created_at"].timestamp() * 1000), 0.0]]
            for r in conn.execute("SELECT ts, equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall():
                pts.append([r["ts"], float(r["equity"]) / start - 1])
            pts.append([now, float(broker_for(conn, a, prices_).equity()) / start - 1])
            out[a["name"]] = pts
    return out


@app.get("/api/benchmark")
def benchmark():
    """Gleichgewichtetes Buy-and-Hold aus BTC/ETH/SOL ab Start des Paper-Tradings (ohne Kosten), in Prozent."""
    with db() as conn:
        since = conn.execute("SELECT min(created_at) AS t FROM accounts").fetchone()["t"]
        rows = conn.execute("SELECT symbol, close_time, close FROM candles WHERE interval='15m' AND symbol = ANY(%s) "
                            "AND close_time >= %s ORDER BY close_time", (SYMBOLS, int(since.timestamp() * 1000))).fetchall()
    base, last, pts = {}, {}, []
    for r in rows:
        base.setdefault(r["symbol"], r["close"])
        last[r["symbol"]] = r["close"]
        if len(base) == len(SYMBOLS) and r["symbol"] == SYMBOLS[-1]:
            pts.append([r["close_time"], sum(last[s] / base[s] for s in SYMBOLS) / len(SYMBOLS) - 1])
    return pts[::4]


@app.get("/api/fills")
def fills(limit: int = 100, wallet: str | None = None):
    q = ("SELECT a.name AS wallet, f.symbol, f.side, f.qty, f.price, f.fee, f.realized_pnl, f.ts, f.bot FROM fills f "
         "JOIN accounts a ON a.id = f.account_id " + ("WHERE a.name = %s " if wallet else "") + "ORDER BY f.ts DESC, f.id DESC LIMIT %s")
    with db() as conn:
        rows = conn.execute(q, ((wallet, min(limit, 500)) if wallet else (min(limit, 500),))).fetchall()
    return [{**r, "qty": float(r["qty"]), "price": float(r["price"]), "fee": float(r["fee"]), "realized_pnl": float(r["realized_pnl"])} for r in rows]


@app.get("/api/events")
def events(limit: int = 100, wallet: str | None = None, level: str | None = None):
    where, args = [], []
    if wallet:
        where.append("wallet = %s"); args.append(wallet)
    if level:
        where.append("level = %s"); args.append(level)
    with db() as conn:
        return conn.execute("SELECT ts, level, source, wallet, message FROM events " + ("WHERE " + " AND ".join(where) + " " if where else "")
                            + "ORDER BY id DESC LIMIT %s", (*args, min(limit, 500))).fetchall()


def round_trips(fill_rows) -> list[dict]:
    """Abgeschlossene Trades (Long, Durchschnittseinstand) aus der Fill-Folge."""
    open_: dict[str, dict] = {}
    out = []
    for x in fill_rows:
        o = open_.get(x["symbol"])
        if x["side"] == "buy":
            if not o:
                o = open_[x["symbol"]] = {"symbol": x["symbol"], "opened": x["ts"], "qty": 0.0, "cost": 0.0, "fees": 0.0}
            o["qty"] += float(x["qty"]); o["cost"] += float(x["qty"] * x["price"]); o["fees"] += float(x["fee"])
        elif o:
            o["fees"] += float(x["fee"])
            out.append({"symbol": x["symbol"], "opened": o["opened"], "closed": x["ts"], "qty": float(x["qty"]),
                        "entry": o["cost"] / o["qty"], "exit": float(x["price"]), "pnl": float(x["realized_pnl"]),
                        "pnl_pct": float(x["price"]) / (o["cost"] / o["qty"]) - 1, "hold_days": (x["ts"] - o["opened"]) / 86_400_000,
                        "bot": x["bot"]})
            if float(x["qty"]) >= o["qty"] - 1e-12:
                open_.pop(x["symbol"], None)
            else:
                o["cost"] *= 1 - float(x["qty"]) / o["qty"]; o["qty"] -= float(x["qty"])
    return out


@app.get("/api/wallet/{name}")
def wallet_detail(name: str):
    with db() as conn:
        a = conn.execute(ACCOUNT_SQL + " WHERE name = %s", (name,)).fetchone()
        if not a:
            raise HTTPException(404, "Wallet unbekannt")
        prices_, ctrl = latest_prices(conn, SYMBOLS), control_state(conn)
        m = wallet_metrics(conn, a, prices_)
        snaps = conn.execute("SELECT ts, equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall()
        start = float(a["start_cash"])
        peak, dd_curve = start, []
        for s in snaps:
            peak = max(peak, float(s["equity"]))
            dd_curve.append([s["ts"], -(peak - float(s["equity"])) / peak])
        fill_rows = conn.execute("SELECT symbol, side, qty, price, fee, realized_pnl, ts, bot FROM fills WHERE account_id=%s ORDER BY ts, id", (a["id"],)).fetchall()
        states = conn.execute("SELECT symbol, updated_ts, state FROM bot_state WHERE wallet=%s ORDER BY symbol", (name,)).fetchall()
        bt = conn.execute("SELECT kind, capital, params, metrics, created_at FROM backtest_runs WHERE strategy=%s AND interval=%s "
                          "AND kind IN ('run','walkforward') ORDER BY id DESC", (a["strategy"], a["interval"])).fetchall()
        wanted = (a["params"] or {}).get("strategy_params", {})
        bt = [r for r in bt if r["kind"] != "run" or params_match(r["params"], wanted)]
        ev = conn.execute("SELECT ts, level, source, message FROM events WHERE wallet=%s ORDER BY id DESC LIMIT 50", (name,)).fetchall()
    trips = round_trips(fill_rows)
    daily = daily_returns(start, [s["ts"] for s in snaps], [float(s["equity"]) for s in snaps])
    bt_run = next((r for r in bt if r["kind"] == "run" and float(r["capital"] or 0) == start), None)
    return {
        "metrics": m, "paused": f"pause:{name}" in ctrl or "kill" in ctrl, "pause_reason": (ctrl.get(f"pause:{name}") or {}).get("reason"),
        "kill_switch": "kill" in ctrl, "drawdown_curve": dd_curve, "states": [{**s, "state": s["state"]} for s in states],
        "round_trips": trips[::-1][:100], "fills": [{**r, "qty": float(r["qty"]), "price": float(r["price"]), "fee": float(r["fee"]),
                                                    "realized_pnl": float(r["realized_pnl"])} for r in fill_rows[::-1][:100]],
        "events": ev, "days_running": (now_ms() - m["since"]) / 86_400_000, "daily_return_count": len(daily),
        "monthly": lab.monthly([s["ts"] for s in snaps], [float(s["equity"]) for s in snaps], start) if snaps else [],
        "param_docs": {"strategy": strategy_param_docs(a["strategy"]), "wallet": wallet_param_docs()},
        "backtest": None if not bt_run else {"return": bt_run["metrics"].get("return"), "max_dd": bt_run["metrics"].get("max_dd"),
                                              "sharpe": bt_run["metrics"].get("sharpe"), "trades": bt_run["metrics"].get("trades"),
                                              "win_rate": bt_run["metrics"].get("win_rate"), "profit_factor": bt_run["metrics"].get("profit_factor"),
                                              "bh_return": bt_run["metrics"].get("bh_return")},
    }


@app.get("/api/strategies")
def strategies():
    with db() as conn:
        prices_ = latest_prices(conn, SYMBOLS)
        accts = conn.execute(ACCOUNT_SQL + " ORDER BY name").fetchall()
        live = {a["name"]: wallet_metrics(conn, a, prices_) for a in accts}
        runs = conn.execute("SELECT id, kind, strategy, interval, params, capital, metrics, note, created_at FROM backtest_runs ORDER BY id").fetchall()
    out = []
    for key, info in STRATEGY_CATALOG.items():
        mine = [w for w in live.values() if w["name"].startswith(info["wallet_prefix"] + "-")]
        wanted = {**{k: v.default for k, v in __import__("inspect").signature(STRATEGIES[info["backtest_key"]].__init__).parameters.items() if k != "self"}, **info["params"]}
        rr = [r for r in runs if r["strategy"] == info["backtest_key"] and r["interval"] == info["interval"] and (r["kind"] != "run" or params_match(r["params"], wanted))]
        latest = {}
        for r in rr:  # jeweils der neueste Lauf je (Art, Intervall, Kapital)
            latest[(r["kind"], r["interval"], float(r["capital"] or 0))] = r
        def slim(m):  # Verläufe (curve) nicht in die Übersicht packen
            return {k: v for k, v in m.items() if k not in ("curve", "bh_curve")}
        out.append({
            **{k: v for k, v in info.items() if k != "backtest_key"}, "key": key, "strategy": info["backtest_key"],
            "live": [{"name": w["name"], "start_cash": w["start_cash"], "equity": w["equity"], "return": w["return"], "trades": w["trades"],
                      "max_drawdown": w["max_drawdown"], "exposure": w["exposure"]} for w in mine],
            "backtests": [{"kind": r["kind"], "interval": r["interval"], "capital": f(r["capital"]), "params": r["params"], "note": r["note"],
                           "created_at": r["created_at"].isoformat(), "metrics": slim(r["metrics"]),
                           "has_curve": "curve" in r["metrics"], "id": r["id"]} for r in latest.values()],
        })
    return out


@app.get("/api/backtest/{run_id}/curve")
def backtest_curve(run_id: int):
    with db() as conn:
        r = conn.execute("SELECT strategy, interval, capital, metrics FROM backtest_runs WHERE id=%s", (run_id,)).fetchone()
    if not r:
        raise HTTPException(404)
    m = r["metrics"]
    return {"strategy": r["strategy"], "interval": r["interval"], "capital": f(r["capital"]), "curve": m.get("curve", []),
            "benchmark": m.get("bh_curve") or []}


@app.get("/api/master")
def master():
    with db() as conn:
        rep = conn.execute("SELECT value, updated_at FROM control WHERE key='master_report'").fetchone()
        ctrl = control_state(conn)
    report = json.loads(rep["value"]) if rep else None
    return {"report": report, "age_s": round(time.time() - rep["updated_at"].timestamp(), 1) if rep else None,
            "kill_switch": "kill" in ctrl, "kill_reason": (ctrl.get("kill") or {}).get("reason"),
            "paused": {k.split(":", 1)[1]: {"reason": v["reason"], "since": v["updated_at"].isoformat()} for k, v in ctrl.items() if k.startswith("pause:")}}


@app.get("/api/system")
def system():
    now = time.time()
    with db() as conn:
        counts = conn.execute("SELECT symbol, interval, count(*) AS n, min(open_time) AS first, max(close_time) AS last FROM candles "
                              "GROUP BY 1,2 ORDER BY 1,2").fetchall()
        size = conn.execute("SELECT pg_database_size(current_database()) AS b").fetchone()["b"]
        tables = conn.execute("SELECT relname, n_live_tup AS rows FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 12").fetchall()
    hb = {}
    for svc in ("market-data", "bots", "master"):
        v = R.get(f"heartbeat:{svc}")
        hb[svc] = round(now - float(v), 1) if v else None
    return {"heartbeats": hb, "candles": [{**c, "age_s": round(now - c["last"] / 1000, 0)} for c in counts], "db_bytes": size,
            "tables": tables,
            "redis_ping": bool(R.ping()), "server_time": int(now * 1000)}


@app.get("/api/meta")
def meta():
    """Parameter-, Indikator- und Kennzahlen-Erklärungen sowie Standardwerte je Strategie."""
    import inspect
    defaults = {n: {k: v.default for k, v in inspect.signature(c.__init__).parameters.items() if k != "self"} for n, c in STRATEGIES.items()}
    return {"params": PARAMS, "indicators": {k: {"label": v[0], "what": v[1]} for k, v in INDICATORS.items()},
            "metrics": {k: {"label": v[0], "what": v[1]} for k, v in METRICS.items()}, "defaults": defaults,
            "symbols": SYMBOLS, "intervals": list(lab.INTERVALS),
            "wallet_defaults": {"position_fraction": 0.33, "fee_rate": "0.001", "slippage_bps": "5"}}


def overlays(strategy: str, params: dict, rows: list[dict]) -> dict:
    """Indikatorlinien für den Kerzenchart, mit denselben Klassen wie die Strategie."""
    out: dict[str, list] = defaultdict(list)
    if strategy == "trend":
        hi, lo, atr = Window(params.get("entry_n", 55)), Window(params.get("exit_n", 20)), ATR(params.get("atr_n", 14))
        ema = EMA(params["trend_n"]) if params.get("trend_n") else None
        for r in rows:
            t = r["time"]
            if hi.full:
                out["entry_level"].append([t, hi.max])
            if lo.full:
                out["exit_level"].append([t, lo.min])
            a = atr.update(r["high"], r["low"], r["close"])
            if a is not None:
                out["atr_stop"].append([t, r["close"] - params.get("atr_mult", 3.0) * a])
            if ema:
                e = ema.update(r["close"])
                if ema.ready:
                    out["trend_ema"].append([t, e])
            hi.push(r["high"]); lo.push(r["low"])
    elif strategy == "meanrev":
        bb, rsi, ema, k = Window(params.get("bb_n", 20)), RSI(params.get("rsi_n", 14)), EMA(params.get("trend_n", 200)), params.get("bb_k", 2.0)
        for r in rows:
            t = r["time"]
            v = rsi.update(r["close"])
            if v is not None:
                out["rsi"].append([t, v])
            bb.push(r["close"])
            if bb.full:
                out["bb_mid"].append([t, bb.mean]); out["bb_lower"].append([t, bb.mean - k * bb.std]); out["bb_upper"].append([t, bb.mean + k * bb.std])
            e = ema.update(r["close"])
            if ema.ready:
                out["trend_ema"].append([t, e])
    return out


@app.get("/api/candles")
def candles(symbol: str, interval: str = "4h", limit: int = 300, wallet: str | None = None, strategy: str | None = None):
    """OHLC-Kerzen mit Indikatorlinien und (optional) Trades einer Wallet."""
    if symbol not in SYMBOLS or interval not in ("15m", "1h", "4h", "1d"):
        raise HTTPException(400, "Symbol oder Intervall unbekannt")
    limit = max(50, min(limit, 1500))
    warm = 300
    with db() as conn:
        rows = conn.execute("SELECT open_time AS time, open, high, low, close, volume FROM (SELECT * FROM candles WHERE symbol=%s AND interval=%s "
                            "ORDER BY open_time DESC LIMIT %s) t ORDER BY open_time", (symbol, interval, limit + warm)).fetchall()
        params, marks = {}, []
        if wallet:
            a = conn.execute("SELECT id, strategy, params FROM accounts WHERE name=%s", (wallet,)).fetchone()
            if a:
                strategy = strategy or a["strategy"]
                params = (a["params"] or {}).get("strategy_params", {})
                marks = conn.execute("SELECT side, price, qty, realized_pnl, ts, bot FROM fills WHERE account_id=%s AND symbol=%s ORDER BY ts", (a["id"], symbol)).fetchall()
    ov = overlays(strategy, params, rows) if strategy in STRATEGIES else {}
    first = rows[warm]["time"] if len(rows) > warm else (rows[0]["time"] if rows else 0)
    return {"symbol": symbol, "interval": interval, "strategy": strategy, "params": params,
            "candles": [r for r in rows if r["time"] >= first],
            "overlays": {k: [p for p in v if p[0] >= first] for k, v in ov.items()},
            "trades": [{"side": m["side"], "price": float(m["price"]), "qty": float(m["qty"]), "pnl": float(m["realized_pnl"]), "ts": m["ts"], "bot": m["bot"]} for m in marks]}


@app.get("/api/analytics/backtests")
def analytics_backtests():
    """Gespeicherte Standard-Backtests mit Verlauf und Monatsrenditen (für Vergleiche ohne Neuberechnung)."""
    with db() as conn:
        rows = conn.execute("SELECT id, kind, strategy, interval, capital, params, metrics, created_at FROM backtest_runs ORDER BY id").fetchall()
    latest = {}
    for r in rows:
        latest[(r["kind"], r["strategy"], r["interval"], float(r["capital"] or 0))] = r
    out = []
    for r in latest.values():
        m = r["metrics"]
        item = {"id": r["id"], "kind": r["kind"], "strategy": r["strategy"], "interval": r["interval"], "capital": f(r["capital"]), "params": r["params"],
                "created_at": r["created_at"].isoformat(), "metrics": {k: v for k, v in m.items() if k not in ("curve", "bh_curve")}}
        if r["kind"] == "run" and m.get("curve"):
            cap = float(r["capital"])
            item["curve"], item["bh_curve"] = m["curve"], m.get("bh_curve", [])
            item["monthly"] = lab.monthly([p[0] for p in m["curve"]], [cap * (1 + p[1]) for p in m["curve"]], cap)
        out.append(item)
    return out


@app.post("/api/lab/run")
async def lab_run(request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    body = await request.json()
    try:
        return await run_in_threadpool(lab.run, body)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"Ungültige Eingabe: {e}")


@app.post("/api/lab/sweep")
async def lab_sweep(request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    body = await request.json()
    try:
        return await run_in_threadpool(lab.sweep, body)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"Ungültige Eingabe: {e}")


# ------------------------------------------------------------------ Steuerung (POST)
def guard(request: Request, x_requested_with: str | None):
    """Einfacher Schutz gegen fremde Webseiten: nur fetch() aus dem Dashboard selbst (gleiche Origin, eigener Header)."""
    origin = request.headers.get("origin")
    if x_requested_with != "tradebot-dashboard" or (origin and origin.split("://", 1)[-1] != request.headers.get("host")):
        raise HTTPException(403, "Nicht erlaubt")


def set_control(conn, key: str, reason: str | None):
    conn.execute("INSERT INTO control (key, value, reason) VALUES (%s, '1', %s) ON CONFLICT (key) DO UPDATE SET value='1', reason=EXCLUDED.reason, updated_at=now()", (key, reason))


@app.post("/api/control/pause/{name}")
def pause(name: str, request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE name=%s", (name,)).fetchone():
            raise HTTPException(404, "Wallet unbekannt")
        set_control(conn, f"pause:{name}", "Manuell im Dashboard pausiert")
        add_event(conn, "dashboard", "warn", "Manuell pausiert (keine neuen Einstiege)", name)
    return {"ok": True}


@app.post("/api/control/resume/{name}")
def resume(name: str, request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    with db() as conn:
        conn.execute("DELETE FROM control WHERE key=%s", (f"pause:{name}",))
        add_event(conn, "dashboard", "info", "Manuell freigegeben", name)
    return {"ok": True}


@app.post("/api/control/kill")
def kill(request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    with db() as conn:
        set_control(conn, "kill", "Kill-Switch im Dashboard ausgelöst")
        add_event(conn, "dashboard", "error", "KILL-SWITCH ausgelöst: alle Positionen werden geschlossen, keine neuen Einstiege")
    return {"ok": True}


@app.post("/api/control/unkill")
def unkill(request: Request, x_requested_with: str | None = Header(default=None)):
    guard(request, x_requested_with)
    with db() as conn:
        conn.execute("DELETE FROM control WHERE key='kill'")
        add_event(conn, "dashboard", "info", "Kill-Switch aufgehoben (einzelne Pausen bleiben bestehen)")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
