"""What still needs setting up, for the overview's setup card."""
from dataclasses import dataclass
from pathlib import Path

from prospector.config import Settings
from prospector.store.kv import KV

EXAMPLE_PROFILE = Path(__file__).resolve().parents[3] / "profile.example.yaml"


@dataclass(frozen=True)
class ChecklistItem:
    text: str
    href: str


def _placeholder(value: str | None) -> bool:
    return not value or "REPLACE_ME" in value


def setup_items(settings: Settings, kv: KV, profile_path: Path, example_path: Path) -> list[ChecklistItem]:
    items = []
    key = settings.llm_api_key.get_secret_value()
    last = kv.get("llm_last_error") or ""
    if _placeholder(key):
        items.append(ChecklistItem("Add your OpenCode Go API key — AI reviews are off until then.",
                                   "/settings/connections#f-llm_api_key"))
    elif "HTTP 401" in last or "HTTP 403" in last:
        items.append(ChecklistItem("Your OpenCode Go key was rejected — check it.", "/settings/connections#f-llm_api_key"))
    if not (settings.telegram_token and settings.telegram_chat_id):
        items.append(ChecklistItem("Connect Telegram to get the daily digest there.", "/settings/connections#f-telegram_token"))
    if not settings.bridge_url:
        items.append(ChecklistItem("Set the mail-bridge Worker URL for the email digest.", "/settings/connections#f-bridge_url"))
    if _placeholder(settings.access_team_domain) or _placeholder(settings.access_aud):
        items.append(ChecklistItem("Fill in Cloudflare Access so prospector.thesphynx.net works.",
                                   "/settings/connections#f-access_team_domain"))
    try:
        if Path(profile_path).read_bytes() == Path(example_path).read_bytes():
            items.append(ChecklistItem("Your profile is still the example — make it yours.", "/settings/profile"))
    except OSError:
        pass  # no example shipped, or no profile file: nothing useful to compare
    return items
