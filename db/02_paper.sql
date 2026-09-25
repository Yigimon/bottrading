-- Paper-Trading: Konten, Trades, Equity-Verlauf. Geldbeträge als NUMERIC (kein Rundungsfehler).
CREATE TABLE IF NOT EXISTS accounts (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    start_cash  NUMERIC NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'USDT',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fills (
    id           BIGSERIAL PRIMARY KEY,
    account_id   INT NOT NULL REFERENCES accounts(id),
    bot          TEXT NOT NULL DEFAULT '',
    order_id     BIGINT NOT NULL,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,
    qty          NUMERIC NOT NULL,
    price        NUMERIC NOT NULL,
    fee          NUMERIC NOT NULL,
    realized_pnl NUMERIC NOT NULL,
    maker        BOOLEAN NOT NULL DEFAULT FALSE,
    ts           BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS fills_account_ts ON fills (account_id, ts);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    account_id INT NOT NULL REFERENCES accounts(id),
    ts         BIGINT NOT NULL,
    cash       NUMERIC NOT NULL,
    equity     NUMERIC NOT NULL,
    PRIMARY KEY (account_id, ts)
);

-- Die Wallets (z. B. trend-10000, meanrev-100) legt der Bot-Service beim Start an.
