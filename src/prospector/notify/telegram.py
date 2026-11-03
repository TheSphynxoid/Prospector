import httpx


def send_telegram(http: httpx.Client, token: str, chat_id: str, text: str) -> None:
    resp = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True})
    resp.raise_for_status()
