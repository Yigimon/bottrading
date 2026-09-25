"""Gruppen mit Themen: legt die Themen an und ordnet Meldungen zu. Ohne Themen (Direktchat) geht alles in den Chat.

Themen-IDs und Zuordnung liegen in der Tabelle control ('telegram:topics', 'telegram:routing'), nicht im Code.
"""
import json
import logging

from tg import TelegramError

log = logging.getLogger("telegram.topics")

# Schlüssel -> (Anzeigename, Farbe laut Telegram-Palette)
TOPICS = {
    "overview": ("Übersicht", 0x6FB9F0),
    "trades_big": ("Trades 10.000", 0x8EEE98),
    "trades_small": ("Trades 100", 0xCB86DB),
    "alarms": ("Alarme", 0xFF93B2),
}
# Meldungsart -> Thema. trades_big/trades_small: Käufe und Verkäufe von Wallets mit >= 1.000 bzw. < 1.000 USDT Startkapital.
ROUTING_DEFAULT = {"trades_big": "trades_big", "trades_small": "trades_small", "warning": "alarms", "error": "alarms",
                   "info": "overview", "startup": "overview", "daily": "overview"}
# Themen, deren Meldungen standardmäßig ohne Ton kommen (zusätzlich zu /notify)
SILENT_TOPICS_DEFAULT = ["trades_small"]
ROUTE_LABELS = {"trades_big": "Trades der großen Wallets (≥ 1.000 USDT)", "trades_small": "Trades der kleinen Wallets (< 1.000 USDT)",
                "warning": "Warnungen", "error": "Fehler", "info": "Info", "startup": "Dienst-Starts", "daily": "Tagesbericht"}


def _get(conn, key, default):
    row = conn.execute("SELECT value FROM control WHERE key=%s", (key,)).fetchone()
    try:
        return json.loads(row["value"]) if row else default
    except (TypeError, ValueError):
        return default


def _set(conn, key, value):
    conn.execute("INSERT INTO control (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (key, json.dumps(value)))
    conn.commit()


def routing(conn) -> dict:
    return {**ROUTING_DEFAULT, **_get(conn, "telegram:routing", {})}


def set_route(conn, kind, topic):
    r = _get(conn, "telegram:routing", {}); r[kind] = topic; _set(conn, "telegram:routing", r)


def silent_topics(conn) -> list:
    return _get(conn, "telegram:silent_topics", SILENT_TOPICS_DEFAULT)


def set_silent_topic(conn, topic, silent: bool):
    cur = set(silent_topics(conn)); (cur.add if silent else cur.discard)(topic); _set(conn, "telegram:silent_topics", sorted(cur))


class Topics:
    """Themen einer Gruppe verwalten. forum=False: alles geht ohne Thema in den Chat."""

    def __init__(self, api, conn, chat_id):
        self.api, self.conn, self.chat_id = api, conn, chat_id
        self.forum = False
        self.ids = _get(conn, "telegram:topics", {})

    def setup(self):
        try:
            chat = self.api.call("getChat", chat_id=self.chat_id)
        except TelegramError as e:
            log.warning("getChat fehlgeschlagen: %s", e)
            return
        self.forum = bool(chat.get("is_forum"))
        if self.forum:
            for key in TOPICS:
                self.ensure(key)

    def ensure(self, key, force=False):
        if not self.forum:
            return None
        if key in self.ids and not force:
            return self.ids[key]
        name, color = TOPICS[key]
        try:
            t = self.api.call("createForumTopic", chat_id=self.chat_id, name=name, icon_color=color)
        except TelegramError as e:
            log.warning("Thema '%s' konnte nicht angelegt werden (Bot braucht Admin-Recht 'Themen verwalten'): %s", name, e)
            return None
        self.ids[key] = t["message_thread_id"]
        _set(self.conn, "telegram:topics", self.ids)
        log.info("Thema '%s' angelegt (ID %s)", name, t["message_thread_id"])
        return self.ids[key]

    def thread_for(self, kind):
        return self.ensure(routing(self.conn).get(kind, "overview")) if self.forum else None

    def is_silent(self, kind):
        return self.forum and routing(self.conn).get(kind, "overview") in silent_topics(self.conn)

    def send(self, kind, text, silent=False, markup=None):
        """Sendet ins zugeordnete Thema. Wurde das Thema gelöscht, wird es neu angelegt und erneut gesendet."""
        thread = self.thread_for(kind)
        silent = silent or self.is_silent(kind)
        try:
            return self.api.send(self.chat_id, text, markup, silent=silent, thread_id=thread)
        except TelegramError as e:
            if thread and "thread not found" in str(e).lower():
                key = routing(self.conn).get(kind, "overview")
                return self.api.send(self.chat_id, text, markup, silent=silent, thread_id=self.ensure(key, force=True))
            raise
