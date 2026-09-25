-- Grund je Order (Signal, Stop, manueller Ausstieg) für Telegram-Meldungen und Auswertungen
ALTER TABLE fills ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';
