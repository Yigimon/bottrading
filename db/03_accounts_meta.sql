-- Strategie und Kerzenintervall je Wallet (für das Dashboard).
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS interval TEXT;
UPDATE accounts SET strategy = split_part(name, '-', 1), interval = '4h' WHERE strategy IS NULL;
