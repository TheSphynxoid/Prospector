import json
import time

import httpx

from prospector.web.ingest import sign


def send_email_via_bridge(http: httpx.Client, bridge_url: str, secret: bytes,
                          subject: str, text: str, html: str) -> None:
    """POST the digest to the mail-bridge Worker, signed like /ingest/mail."""
    body = json.dumps({"subject": subject, "text": text, "html": html}).encode()
    ts = str(int(time.time()))
    resp = http.post(f"{bridge_url.rstrip('/')}/digest", content=body, headers={
        "Content-Type": "application/json",
        "X-Prospector-Timestamp": ts,
        "X-Prospector-Signature": "sha256=" + sign(secret, ts, body),
    })
    resp.raise_for_status()
