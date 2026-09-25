-- Nur geschlossene Kerzen, Zeitstempel in UTC (Millisekunden seit Epoch wie bei Binance).
CREATE TABLE IF NOT EXISTS candles (
    symbol      TEXT             NOT NULL,
    interval    TEXT             NOT NULL,
    open_time   BIGINT           NOT NULL,
    close_time  BIGINT           NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);
