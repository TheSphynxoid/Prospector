# Prospector

Always-on personal opportunity finder. It pulls computer-science jobs, freelance gigs, bounties and PFE offers
from many sources, ranks them against your profile and projects, and sends you a daily digest
(Telegram + email) with a dashboard to browse, star and dismiss leads. It never applies or messages anyone
for you.

- Design: [docs/superpowers/specs/2026-11-03-prospector-design.md](docs/superpowers/specs/2026-11-03-prospector-design.md)
- Plan: [docs/superpowers/plans/2026-11-03-prospector-v1.md](docs/superpowers/plans/2026-11-03-prospector-v1.md)

## How it works

1. **Sources** — Remotive, RemoteOK, Himalayas, Arbeitnow, Adzuna (FR/DE/GB/AU), HN "Who is hiring",
   GitHub `💎 Bounty` issues, Freelancer.com, Keejob (RSS), and job-alert emails sent to
   `alerts@prospector.thesphynx.net` (via the `mail-bridge` Cloudflare Worker).
2. **Normalize + dedupe** — one lead per posting even when it appears on several boards.
3. **Stage 1 (free)** — hard filters, local CPU embeddings, keyword/pay/remote/freshness rules and your feedback.
4. **Stage 2 (LLM)** — the top ~20 leads a day get a verdict, a "why you fit", and which project to lead with
   (OpenCode Go, OpenAI-compatible; swappable in `.env`).
5. **Digest at 08:00 Tunis time** + dashboard at `https://prospector.thesphynx.net`.

## Local development

```bash
python -m pip install --user uv          # once
uv sync
uv run pytest -m "not slow"             # fast suite
uv run pytest                           # includes the real embedding model (~1 GB download)
cd mail-bridge && npm install && npx vitest run && npx tsc --noEmit
```

CLI (`uv run python -m prospector …` locally, `docker compose exec prospector python -m prospector …` on the server):

| Command | What it does |
|---|---|
| `serve` | dashboard + scheduler (what the container runs) |
| `run-source <id>` | fetch one source now |
| `stage2` | run the LLM review now |
| `digest [--dry-run]` | send the digest now (or just print it) |
| `check-llm` | list LLM models and check the configured ones |

## Deploy (server, over Tailscale)

```bash
git clone <repo> prospector && cd prospector
cp .env.example .env && nano .env        # fill in secrets, TAILSCALE_IP
mkdir -p data && cp profile.example.yaml data/profile.yaml && sudo chown -R 1000:1000 data
docker compose up -d --build
docker compose logs -f                    # first start downloads the embedding model (~1 GB)
```

Updates: `git pull && docker compose up -d --build`.

## Owner setup checklist

These need your accounts, so they're manual:

1. **OpenCode Go** — create an API key → `LLM_API_KEY`. Then `docker compose exec prospector python -m prospector check-llm`.
2. **Telegram** — create a bot with @BotFather → `TELEGRAM_TOKEN`; message the bot once, then get your chat id
   from `https://api.telegram.org/bot<TOKEN>/getUpdates` → `TELEGRAM_CHAT_ID`.
3. **Optional sources** — Adzuna app id/key (developer.adzuna.com) and a GitHub token (no scopes needed) → `.env`.
4. **cloudflared** — add the rule from `deploy/cloudflared-ingress.yml.example` and restart cloudflared.
5. **Cloudflare Access** (Zero Trust → Access → Applications):
   - App `prospector.thesphynx.net` — policy: allow your email only. Copy its **AUD tag** → `ACCESS_AUD`,
     and your team domain (`<team>.cloudflareaccess.com`) → `ACCESS_TEAM_DOMAIN`.
   - App `prospector.thesphynx.net/ingest/mail` — policy action **Service Auth** with a new service token.
     Keep the client id/secret for the Worker.
6. **Email** (Cloudflare dashboard → Email):
   - Enable **Email Routing** for the subdomain `prospector.thesphynx.net` (only the subdomain gets MX records;
     your Zoho mail on the apex is untouched).
   - Enable **Email Sending** for the same domain (`npx wrangler email sending enable prospector.thesphynx.net`).
   - Routing rule: `alerts@prospector.thesphynx.net` → Worker `mail-bridge`.
7. **mail-bridge Worker**:
   ```bash
   cd mail-bridge && npm install
   npx wrangler r2 bucket create mail-bridge-spool
   npx wrangler queues create mail-bridge-retry
   # set OWNER_EMAIL in wrangler.jsonc to your Zoho address, then:
   npx wrangler secret put BRIDGE_SECRET            # same value as BRIDGE_SECRET in .env
   npx wrangler secret put ACCESS_CLIENT_ID
   npx wrangler secret put ACCESS_CLIENT_SECRET
   npx wrangler deploy                              # copy the workers.dev URL → BRIDGE_URL in .env
   ```
   If npm blocked workerd's install script, run `npm install-scripts approve workerd` first.
8. **Job alerts** — subscribe alerts on LinkedIn, Indeed, Welcome to the Jungle, Malt and Tanitjobs to
   `alerts@prospector.thesphynx.net`. Confirmation emails appear under **Needs you** on the dashboard —
   click them yourself.

## Profile

`data/profile.yaml` (start from `profile.example.yaml`): skills, project write-ups (these drive matching),
target kinds/regions, hard filters (unpaid, min pay, languages, blocked keywords/companies) and boost keywords.
Restart the container after editing.

## Sources not used

- LinkedIn, Indeed, Malt, Welcome to the Jungle: their terms forbid scraping — covered through alert emails instead.
