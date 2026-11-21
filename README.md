# Threads Secretary

**Personal AI Secretary for Threads** — FastAPI + Gemini + SQLite + Threads API, packaged for **Docker Compose** or **Coolify**.

Repository: **https://github.com/cumayogie/threads-secretary**

> **Status:** portable reconstruction, not a byte-for-byte export of the original Coolify production app. Deploy to a **separate staging hostname** and test before replacing production. **Live publishing is OFF by default.**

## What it does

- Generate Indonesian Threads drafts using Gemini (manual topic input).
- Review drafts and approve/reject from a private dashboard.
- Publish an approved draft to Threads **only after explicitly enabling** `THREADS_PUBLISH_ENABLED=true`.
- Store drafts and publish state in persistent SQLite; record uncertain publish results as `needs_review` instead of blindly retrying.
- Protect dashboard with verified Cloudflare Access JWT; optional API-key endpoints for integration.

## Quick start

### Docker Compose

```bash
git clone https://github.com/cumayogie/threads-secretary.git
cd threads-secretary
cp .env.example .env
chmod 600 .env
nano .env                      # Fill in secrets and hostname; leave publishing disabled
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 ai-secretary
```

Health check (from inside container; port 8000 is **not published** on the host):

```bash
docker compose exec ai-secretary python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode())'
```

**You must separately connect a trusted HTTPS reverse proxy / Cloudflare Tunnel to the Docker network** and protect the dashboard hostname using Cloudflare Zero Trust Access. Docker Compose alone does not expose a working public URL.

### Coolify (recommended when already using Coolify)

Create **Application → Public Git Repository** (or GitHub source) → `https://github.com/cumayogie/threads-secretary` → branch `main` → **Dockerfile** build, Dockerfile path `Dockerfile`, port `8000`. Add all `.env.example` keys as Coolify environment variables, create a persistent volume mounted at `/app/data` **before the first deploy**, and use a **new staging domain**. Configure Cloudflare Access for that exact hostname, then deploy and verify `/health` and `/dashboard`.

**Detailed walkthrough:** [INSTALLATION.md](INSTALLATION.md).

## Repository layout

```text
threads-secretary/
├── app/
│   ├── __init__.py
│   └── main.py
├── tests/
│   └── test_app.py
├── .github/workflows/tests.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── compose.yaml
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── INSTALLATION.md
```

## Required environment variables

| Variable | Purpose |
| --- | --- |
| `DASHBOARD_HOST` | Dashboard hostname **without** scheme, e.g. `threads-staging.example.com` |
| `CF_ACCESS_TEAM_DOMAIN` | Cloudflare Access team domain, e.g. `team.cloudflareaccess.com` |
| `CF_ACCESS_AUD` | Audience tag for the Cloudflare Access application on that hostname |
| `GEMINI_API_KEY` | Gemini API key; never commit |
| `GEMINI_MODEL` | Available Gemini model ID; verify in your account |
| `THREADS_ACCESS_TOKEN` | Threads token for authorized account |
| `SECRET_API_KEY` | Random key for `/draft` and `/drafts` API endpoints |
| `DB_PATH` | `/app/data/secretary.db` for Docker |
| `THREADS_PUBLISH_ENABLED` | `false` by default; `true` permits live posting |

Generate `SECRET_API_KEY` on your server with `openssl rand -hex 32`.

## Routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | None | Container health check (do not treat as dashboard auth) |
| `GET /dashboard` | Cloudflare Access JWT | Dashboard |
| `GET /ui/drafts` | Cloudflare Access JWT | List drafts |
| `POST /ui/draft` | Cloudflare Access JWT + Origin | Generate draft |
| `POST /ui/drafts/{id}/approve` | Cloudflare Access JWT + Origin | Approve |
| `POST /ui/drafts/{id}/reject` | Cloudflare Access JWT + Origin | Reject |
| `POST /ui/drafts/{id}/publish` | Cloudflare Access JWT + Origin + publish lock | Publish once |
| `GET /drafts`, `POST /draft` | `x-api-key` | Integration API |

## Safety and limitations

- This is a **personal-use** app; not a public multi-user SaaS.
- **Do not expose the origin** directly to the internet. Use Cloudflare Tunnel or restrictive firewall/proxy rules. The app cryptographically validates Access JWT but a secure ingress boundary is still important.
- The Dockerfile disables trust of arbitrary forwarded headers (`--no-proxy-headers`). Ensure your reverse proxy preserves the original `Host` header. HTTPS is terminated at the trusted proxy.
- Never commit `.env`, SQLite files, credentials, or backups. The repository is public.
- Do not use the same production domain simultaneously on two running instances.
- SQLite persistence is **not** a backup; back up to separate storage.
- No automatic token refresh, scheduler, analytics, replies, or deleted-post reconciliation.
- A timeout while publishing can mean the post actually succeeded; check Threads manually before retrying.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions runs the tests on pushes and pull requests. This is **not** a substitute for an actual Docker build, Cloudflare login, Gemini API, or Threads API staging test.

## License

No license file is included. Public visibility does not automatically grant permission for others to reuse the source.
