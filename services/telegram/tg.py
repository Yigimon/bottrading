"""Schlanker Client für die Telegram-Bot-API (Long Polling, HTML-Nachrichten, Inline-Tastaturen).

Der Token steht nur in der URL der Anfragen; httpx-Logging ist deshalb auf WARNING gestellt (sonst stünde er im Log).
"""
import logging
import time

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("telegram.api")
LIMIT = 4096


class TelegramError(Exception):
    pass


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Teilt an Zeilengrenzen. Ein offener <pre>-Block wird am Teilungspunkt geschlossen und im nächsten Teil wieder geöffnet."""
    if len(text) <= limit:
        return [text]
    parts, cur, in_pre = [], "", False
    for line in text.split("\n"):
        if len(line) > limit - 20:  # überlange Einzelzeile kürzen
            line = line[:limit - 23] + "…"
        if cur and len(cur) + len(line) + 1 + (6 if in_pre else 0) > limit:
            parts.append(cur.rstrip("\n") + ("</pre>" if in_pre else ""))
            cur = "<pre>" if in_pre else ""
        cur += line + "\n"
        opens, closes = line.count("<pre>"), line.count("</pre>")
        if opens != closes:
            in_pre = opens > closes
    if cur.strip():
        parts.append(cur.rstrip("\n"))
    return parts


class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = httpx.Client(timeout=httpx.Timeout(40, connect=10))

    def call(self, method: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(5):
            try:
                r = self.http.post(self.base + method, json=params)
            except httpx.HTTPError as e:
                log.warning("Telegram %s: Verbindungsfehler (%s), neuer Versuch", method, type(e).__name__)
                time.sleep(2 * (attempt + 1))
                continue
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if data.get("ok"):
                return data["result"]
            retry = (data.get("parameters") or {}).get("retry_after")
            if r.status_code == 429 and retry:
                time.sleep(float(retry) + 0.5)
                continue
            raise TelegramError(f"{method}: {data.get('description') or r.status_code}")
        raise TelegramError(f"{method}: keine Verbindung")

    def send(self, chat_id, text: str, markup: dict | None = None, silent: bool = False, thread_id=None) -> list[dict]:
        out = []
        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            out.append(self.call("sendMessage", chat_id=chat_id, text=chunk, parse_mode="HTML", disable_web_page_preview=True,
                                 disable_notification=silent, message_thread_id=thread_id,
                                 reply_markup=markup if i == len(chunks) - 1 else None))
        return out

    def edit(self, chat_id, message_id: int, text: str, markup: dict | None = None) -> None:
        try:
            self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=split_message(text)[0], parse_mode="HTML",
                      disable_web_page_preview=True, reply_markup=markup)
        except TelegramError as e:
            if "message is not modified" not in str(e):
                raise

    def answer(self, callback_id: str, text: str | None = None) -> None:
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except TelegramError:
            pass

    def updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"])
