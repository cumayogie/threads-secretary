# Installation Guide — Threads Secretary

Official repository: **https://github.com/cumayogie/threads-secretary**  
Supported deployment paths: **Coolify (recommended)** or **Docker Compose**. No manual `python main.py` setup required.

> This package is a portable reconstruction of the working concept, **not** an exact export of the old Coolify production code. Always use a separate staging domain, test thoroughly, and back up existing data before migrating. Live publishing is disabled by default.

## 1. Before you begin

You need:

1. Ubuntu/Linux server with Docker Engine + Compose **or** an existing Coolify installation.
2. Domain/subdomain controlled in Cloudflare, plus an HTTPS reverse proxy or Cloudflare Tunnel.
3. Cloudflare Zero Trust Access application protecting the dashboard hostname, with an Allow policy restricted to your identity.
4. A Gemini API key and supported Gemini model ID.
5. A Meta Threads app/token authorized for the Threads account; for publishing, relevant scopes such as `threads_basic` and `threads_content_publish`.

**Important:** The application verifies Cloudflare Access JWT and rejects dashboard requests with the wrong hostname. Do not skip Access setup or expose the application directly. **Keep your old Coolify application running untouched** while preparing staging.

## 2. Option A — Install in Coolify (recommended)

### Step A1 — Create an independent staging app

1. In Coolify, create a **new project/resource → Application**. Do not edit the existing production application.
2. Select **Public Git Repository** or connected GitHub source.
3. Repository: `https://github.com/cumayogie/threads-secretary`; branch: `main`.
4. Build Pack: **Dockerfile**; Dockerfile location: `Dockerfile` (repository root); internal/exposed port: `8000`.
5. Choose a **new** staging hostname, e.g. `threads-staging.your-domain.com` (replace with a domain you own). Do not reuse `threads.yogieindiarto.com` while production is live.

### Step A2 — Configure secrets (Coolify → Environment Variables)

Copy the **keys**, not placeholder values, from `.env.example`:

```dotenv
DASHBOARD_HOST=threads-staging.your-domain.com
CF_ACCESS_TEAM_DOMAIN=your-team.cloudflareaccess.com
CF_ACCESS_AUD=YOUR_STAGING_ACCESS_APPLICATION_AUD
GEMINI_API_KEY=YOUR_GEMINI_KEY
GEMINI_MODEL=gemini-2.5-flash
THREADS_ACCESS_TOKEN=YOUR_THREADS_TOKEN
SECRET_API_KEY=GENERATE_WITH_OPENSSL_RAND_HEX_32
DB_PATH=/app/data/secretary.db
THREADS_PUBLISH_ENABLED=false
```

- `DASHBOARD_HOST` is **hostname only**: no `https://`, port, or path.
- `CF_ACCESS_AUD` is specific to the **Cloudflare Access application** for the staging hostname. Do not assume the production AUD is correct for staging.
- Verify `GEMINI_MODEL` is available for your key; example model IDs can change.
- Generate `SECRET_API_KEY` with `openssl rand -hex 32`; store the result **only in Coolify**, not GitHub.
- `DB_PATH` must remain `/app/data/secretary.db` inside the container.
- Keep `THREADS_PUBLISH_ENABLED=false` until you deliberately want to publish real posts.

### Step A3 — Persist SQLite **before first deploy**

In Coolify **Persistent Storage**, create a Docker volume mounted at **`/app/data`**. The Docker image runs as UID `1000`; the volume must be writable by that user. A named volume initialized from the image directory typically works, but verify permissions via logs. Do not use ephemeral storage for production drafts.

### Step A4 — Connect domain, TLS, and Access

1. Set the staging domain in Coolify and enable HTTPS using its proxy.
2. Point Cloudflare DNS to the appropriate Coolify ingress (or configure Cloudflare Tunnel).
3. In Cloudflare Zero Trust → **Access → Applications**, create a **Self-hosted** application for the **exact staging hostname**. Restrict Allow policy to your identity.
4. Copy the application's **AUD tag** into `CF_ACCESS_AUD` and the team domain into `CF_ACCESS_TEAM_DOMAIN` in Coolify.
5. Ensure requests reach the app through the trusted proxy, preserving the original **Host** header. Do not publish container port `8000` directly to the internet.
6. Save environment changes and **Redeploy** (a simple restart may not apply changed environment variables).

### Step A5 — Verify

1. Open `https://YOUR-STAGING-HOST/health` and confirm `{"status":"ok",...}`. Health is intentionally unauthenticated at the app layer; Cloudflare Access may require login first.
2. Open `https://YOUR-STAGING-HOST/dashboard`; authenticate with Cloudflare Access.
3. Create a draft; confirm Gemini returns text. Test **Approve** and **Reject**.
4. Confirm `THREADS_PUBLISH_ENABLED=false`; do **not** enable posting during initial testing.
5. Inspect Coolify logs for permission errors, HTTP 401/403, and Gemini errors.

If the dashboard returns **401**, verify Access JWT/AUD/team domain. If it returns **403**, verify `DASHBOARD_HOST`, Host header preservation, and HTTPS Origin.

## 3. Option B — Install with Docker Compose

### Step B1 — Install Docker

Follow the official Docker Engine + Compose installation instructions for Ubuntu: https://docs.docker.com/engine/install/ubuntu/ . Then verify:

```bash
docker --version
docker compose version
```

### Step B2 — Clone repository and configure `.env`

```bash
git clone https://github.com/cumayogie/threads-secretary.git
cd threads-secretary
cp .env.example .env
chmod 600 .env
nano .env
```

Fill all variables as described in **Step A2**, using your own staging hostname and Access application AUD. Never upload `.env` to GitHub.

### Step B3 — Build, run, and check health

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 ai-secretary
```

Test from **inside** the container:

```bash
docker compose exec ai-secretary python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode())'
```

`compose.yaml` uses `expose: 8000`, **not** `ports`. This is intentional: the container is not directly reachable via `http://SERVER-IP:8000`. Connect a trusted HTTPS reverse proxy or Cloudflare Tunnel to the same Docker network. If your proxy is in another Docker network, explicitly join it to the app's network or use an internal-only proxy route. Configure Cloudflare Access for the staging hostname as in **Step A4**. **Do not** replace `expose` with a public `ports: 8000:8000` mapping.

### Step B4 — Apply changes and operate

```bash
# After editing .env (recreate to apply environment changes):
docker compose up -d --force-recreate
# After updating source code:
git pull --ff-only
docker compose up -d --build
# Logs:
docker compose logs -f ai-secretary
```

**Never run `docker compose down -v` unless you intend to delete the database volume.**

## 4. Verify Threads token without publishing

For Docker Compose:

```bash
docker compose exec -T ai-secretary python - <<'PY'
import os
import httpx
r = httpx.get(
    'https://graph.threads.net/v1.0/me',
    headers={'Authorization': 'Bearer ' + os.environ['THREADS_ACCESS_TOKEN']},
    params={'fields': 'id,username'},
    timeout=15,
)
print('HTTP:', r.status_code)
print('Username:', r.json().get('username') if r.status_code == 200 else 'unavailable')
PY
```

For Coolify, open the container terminal and run the equivalent Python statements without the `docker compose exec` wrapper. Do not print or share access tokens. Verify the returned account is the one you intend to use.

## 5. Use the dashboard

1. Sign in via Cloudflare Access at `https://YOUR-STAGING-HOST/dashboard`.
2. Enter a topic; select **Buat Draf dengan Gemini**.
3. Review the generated draft. Choose **Approve** or **Reject**.
4. Approved drafts may show a **Publish** button, but the server blocks it while `THREADS_PUBLISH_ENABLED=false`.
5. To perform a deliberate **live** post: back up data, confirm Threads account and text, set `THREADS_PUBLISH_ENABLED=true`, **redeploy/recreate**, then click Publish **once**. Afterward, consider setting the lock back to `false`.

**Publishing uncertainty:** A network timeout or HTTP 502 does **not** prove that the post failed. Inspect Threads and the draft's `publish_state` / `publish_stage`; **never blindly retry**.

## 6. Database, backups, and migration

- SQLite lives at `/app/data/secretary.db` on persistent storage.
- Backup to **separate storage**, not only another file on the same volume.
- To take a SQLite-consistent backup with Compose:

```bash
docker compose exec -T ai-secretary python - <<'PY'
import sqlite3, datetime
src = '/app/data/secretary.db'
dst = '/app/data/secretary-backup-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S') + '.db'
with sqlite3.connect(src) as original, sqlite3.connect(dst) as backup:
    original.backup(backup)
print('Backup created inside container:', dst)
PY
```

Copy that backup out of the container/volume and store it securely. Before restoring, stop the destination app, make another backup, and ensure file ownership permits UID `1000` to write the database. Test restoration in staging first.

**Migration from your existing Coolify installation:** The source is reconstructed, so confirm schema and functionality before transferring any production DB. Keep publishing locked and avoid two instances posting simultaneously with the same token. A deleted post on Threads is not automatically marked deleted in local SQLite history.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| Docker build fails at `COPY app/` | Verify `app/main.py` exists at repository root under `app/` |
| Container unhealthy | Check `docker compose logs` / Coolify logs; verify `/health` inside container |
| SQLite `permission denied` | Volume mount `/app/data` and write permission for UID `1000` |
| Dashboard HTTP 401 | Access JWT, team domain, AUD, proxy forwarding the Access assertion header |
| Dashboard HTTP 403 | Host header, `DASHBOARD_HOST`, HTTPS Origin |
| Gemini HTTP 502 | API key, model availability, quota, outbound HTTPS |
| Publish HTTP 403 | Expected with `THREADS_PUBLISH_ENABLED=false` |
| Publish HTTP 502 / `needs_review` | Inspect Threads manually; do not retry blindly |
| Domain unreachable | Cloudflare DNS, TLS, reverse proxy, Docker network, Cloudflare Tunnel |

## 8. Security and production checklist

- [ ] `.env` and credentials absent from GitHub; `.env.example` contains placeholders only.
- [ ] Staging domain distinct from production.
- [ ] Cloudflare Access protects the dashboard; Allow policy restricted to your identity.
- [ ] HTTPS proxy preserves original Host; origin not reachable directly from internet.
- [ ] No public port 8000 mapping.
- [ ] Persistent `/app/data` volume created before deployment; backups exported elsewhere.
- [ ] Gemini test draft and approval/rejection tested.
- [ ] Threads token verified read-only; publishing remains disabled until intentional.
- [ ] Real Docker build and health check passed on staging server.

## 9. What is not included

No automated Threads token renewal, scheduled posting, analytics, replies, deleted-post reconciliation, or multi-user roles. Meta app permissions and Gemini model availability can change; validate them in the relevant provider dashboard. This project is designed for private use, not as a publicly open service.
