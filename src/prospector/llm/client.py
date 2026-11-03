import json
import re

import httpx

from prospector import __version__
from prospector.http import describe_error

MODELS_FALLBACK_URL = "https://opencode.ai/inference/go/v1/models"
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(Exception):
    pass


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model reply that may wrap it in fences or prose."""
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(candidate[start:end + 1])


class LLMClient:
    """Minimal OpenAI-compatible chat client (OpenCode Go by default)."""

    def __init__(self, base_url: str, api_key: str, model: str, http: httpx.Client):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.answered = 0  # completions that returned a reply (used to charge the daily cap)
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}", "User-Agent": f"prospector/{__version__}"}

    def complete(self, system: str, user: str, session_id: str) -> str:
        try:
            resp = self._http.post(
                f"{self.base_url}/chat/completions",
                headers={**self._headers, "x-opencode-session": session_id},
                json={"model": self.model, "temperature": 0,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMError(describe_error(e)) from e
        self.answered += 1
        return content

    def list_models(self) -> list[str]:
        causes = []
        for url in (f"{self.base_url}/models", MODELS_FALLBACK_URL):
            try:
                resp = self._http.get(url, headers=self._headers, timeout=20)
                resp.raise_for_status()
                return [m["id"] for m in resp.json()["data"]]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                causes.append(describe_error(e))
        # Report the configured endpoint's failure (e.g. "HTTP 401 from opencode.ai"); never a URL.
        raise LLMError(f"could not list models ({causes[0]})")
