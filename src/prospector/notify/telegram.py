import httpx


def send_telegram(http: httpx.Client, token: str, chat_id: str, text: str) -> None:
    resp = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True})
    resp.raise_for_status()


def find_chats(http: httpx.Client, token: str) -> list[tuple[str, str]]:
    """Chats that recently wrote to the bot, as (chat id, name), newest last, one entry per chat."""
    resp = http.get(f"https://api.telegram.org/bot{token}/getUpdates")
    resp.raise_for_status()
    chats: dict[str, str] = {}
    for update in resp.json().get("result", []):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat and "id" in chat:
                name = chat.get("title") or " ".join(filter(None, (chat.get("first_name"), chat.get("last_name"))))
                chats[str(chat["id"])] = f"{name or 'unnamed'} ({chat.get('type', 'chat')})"
    return list(chats.items())
