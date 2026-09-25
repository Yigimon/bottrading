"""Marktdaten-Service: Backfill historischer Kerzen und Live-Stream von Binance (öffentlich, ohne API-Key).

Speichert nur geschlossene Kerzen in Postgres, meldet neue Kerzen per Redis-Pub/Sub
und schreibt einen Heartbeat für Master-Bot und Healthcheck.
"""
import asyncio
import json
import logging
import os
import time

import httpx
import psycopg
import redis.asyncio as aioredis
import websockets

SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",")]
INTERVALS = [i.strip() for i in os.environ["INTERVALS"].split(",")]
BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "365"))
DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]

REST = "https://api.binance.com/api/v3/klines"
WS = "wss://stream.binance.com:9443/stream?streams="
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

log = logging.getLogger("market-data")

UPSERT = """
INSERT INTO candles (symbol, interval, open_time, close_time, open, high, low, close, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (symbol, interval, open_time) DO UPDATE SET
    close_time = EXCLUDED.close_time, open = EXCLUDED.open, high = EXCLUDED.high,
    low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume
"""


def now_ms() -> int:
    return int(time.time() * 1000)


async def fetch_range(http, db, symbol, interval, start_ms, end_ms=None):
    """Holt geschlossene Kerzen ab start_ms (bis end_ms, falls angegeben) und speichert sie."""
    step = INTERVAL_MS[interval]
    total = 0
    while start_ms < (end_ms or now_ms()):
        params = {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": 1000}
        if end_ms:
            params["endTime"] = end_ms
        resp = await http.get(REST, params=params)
        resp.raise_for_status()
        rows = [r for r in resp.json() if r[6] < now_ms()]  # nur geschlossene Kerzen
        if not rows:
            break
        data = [(symbol, interval, r[0], r[6], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]
        async with db.cursor() as cur:
            await cur.executemany(UPSERT, data)
        await db.commit()
        total += len(rows)
        start_ms = rows[-1][0] + step
        await asyncio.sleep(0.1)  # Rate-Limit schonen
    return total


async def backfill(http, db, symbol, interval):
    step = INTERVAL_MS[interval]
    wanted = now_ms() - BACKFILL_DAYS * 86_400_000
    async with db.cursor() as cur:
        await cur.execute("SELECT min(open_time), max(open_time) FROM candles WHERE symbol=%s AND interval=%s", (symbol, interval))
        first, last = await cur.fetchone()
    start = last + step if last else wanted
    n = await fetch_range(http, db, symbol, interval, start)
    if first and first - wanted > step * 2:  # Historie nach hinten erweitern
        n += await fetch_range(http, db, symbol, interval, wanted, first - 1)
    log.info("Backfill %s %s: %d Kerzen", symbol, interval, n)


async def fill_gaps(http, db, symbol, interval):
    """Sucht Lücken in der Kerzenreihe und lädt sie nach."""
    step = INTERVAL_MS[interval]
    async with db.cursor() as cur:
        await cur.execute(
            """SELECT open_time, nxt FROM (
                   SELECT open_time, lead(open_time) OVER (ORDER BY open_time) AS nxt
                   FROM candles WHERE symbol=%s AND interval=%s) t
               WHERE nxt - open_time > %s ORDER BY open_time""",
            (symbol, interval, step),
        )
        gaps = await cur.fetchall()
    for start, nxt in gaps:
        n = await fetch_range(http, db, symbol, interval, start + step, nxt - 1)
        # 0 Kerzen: Binance hat für die Zeit keine Daten (z. B. Wartungspause), keine echte Lücke
        log.log(logging.WARNING if n else logging.INFO, "Lücke %s %s bei %s: %d Kerzen nachgeladen", symbol, interval, start, n)


async def heartbeat(r):
    while True:
        await r.set("heartbeat:market-data", str(time.time()))
        await asyncio.sleep(10)


async def stream(http, db, r):
    streams = "/".join(f"{s.lower()}@kline_{i}" for s in SYMBOLS for i in INTERVALS)
    backoff = 1
    while True:
        try:
            async with websockets.connect(WS + streams, ping_interval=20, ping_timeout=20) as ws:
                log.info("WebSocket verbunden (%d Streams)", len(SYMBOLS) * len(INTERVALS))
                backoff = 1
                # Nach (Wieder-)Verbindung Verpasstes nachholen
                for s in SYMBOLS:
                    for i in INTERVALS:
                        await backfill(http, db, s, i)
                async for raw in ws:
                    k = json.loads(raw)["data"]["k"]
                    if not k["x"]:  # Kerze noch nicht geschlossen
                        continue
                    row = (k["s"], k["i"], k["t"], k["T"], float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"]))
                    async with db.cursor() as cur:
                        await cur.execute(UPSERT, row)
                    await db.commit()
                    await r.publish("candles", json.dumps({"symbol": k["s"], "interval": k["i"], "open_time": k["t"], "close": float(k["c"])}))
        except Exception as e:  # Verbindung neu aufbauen
            log.error("Stream-Fehler: %s (neuer Versuch in %ss)", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def gap_checker(http, db):
    while True:
        await asyncio.sleep(3600)
        for s in SYMBOLS:
            for i in INTERVALS:
                await fill_gaps(http, db, s, i)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    r =aioredis.from_url(REDIS_URL)
    async with httpx.AsyncClient(timeout=20) as http, await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
        hb = asyncio.create_task(heartbeat(r))  # sofort starten, damit der Healthcheck beim Backfill nicht anschlägt
        for s in SYMBOLS:
            for i in INTERVALS:
                await backfill(http, db, s, i)
                await fill_gaps(http, db, s, i)
        await asyncio.gather(stream(http, db, r), gap_checker(http, db), hb)


if __name__ == "__main__":
    asyncio.run(main())
