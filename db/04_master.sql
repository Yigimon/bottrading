-- Master-Bot, Bot-Zustand, Ereignisse, Backtest-Ergebnisse.

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS params JSONB;   -- Strategie-/Broker-Parameter für das Dashboard

CREATE TABLE IF NOT EXISTS events (
    id      BIGSERIAL PRIMARY KEY,
    ts      BIGINT NOT NULL,            -- ms UTC
    level   TEXT NOT NULL,              -- info | warn | error
    source  TEXT NOT NULL,              -- master | bots | dashboard | market-data
    wallet  TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts DESC);

-- Steuerung: 'kill' = globaler Kill-Switch, 'pause:<wallet>' = Wallet pausiert (keine neuen Einstiege)
CREATE TABLE IF NOT EXISTS control (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    reason     TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Aktueller Indikator-/Signalzustand je Wallet und Symbol (vom Bot-Service geschrieben)
CREATE TABLE IF NOT EXISTS bot_state (
    wallet     TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    updated_ts BIGINT NOT NULL,
    state      JSONB NOT NULL,
    PRIMARY KEY (wallet, symbol)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id         SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind       TEXT NOT NULL,           -- run | walkforward
    strategy   TEXT NOT NULL,
    interval   TEXT,
    params     JSONB,
    capital    NUMERIC,
    metrics    JSONB NOT NULL,
    note       TEXT
);
