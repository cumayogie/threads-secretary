# Personal AI Secretary for Threads — Portable Edition

> **Status:** portable reconstruction of the tested deployment, **not** an exact export of the existing Coolify Dockerfile. Do a staging test before production. Default live publishing is **disabled**.

## Features
- FastAPI and HTML/JS dashboard (`/dashboard`)
- Cloudflare Access JWT validation (RS256, issuer, audience) and Origin validation on writes
- Gemini generates Indonesian Threads drafts, stored in SQLite
- Approve/reject workflow
- Two-step Threads publish with atomic claim, stage tracking and no automatic retries
- Optional API-key endpoints: `GET /drafts`, `POST /draft`
- Persistent SQLite volume, Docker health check

## 1. Prerequisites
- Linux VPS (Ubuntu 22.04/24.04 or similar), Docker Engine + Compose plugin; alternatively Coolify with Dockerfile build.
- A domain/subdomain (e.g. `threads.example.com`), Cloudflare DNS and Cloudflare Zero Trust Access configured to protect it.
- HTTPS reverse proxy or Cloudflare Tunnel pointing at the app on port 8000. **Do not expose port 8000 publicly.**
- Meta Developer App with Threads API access for your own permitted account and a valid access token with `threads_basic` and `threads_content_publish`.
- Gemini API key and supported model ID. Verify the model name in your own AI Studio project.

## 2. Install using Docker Compose
```bash
sudo apt update
# Install Docker Engine and docker compose plugin from official Docker docs if absent.
mkdir -p ~/ai-secretary && cd ~/ai-secretary
# Copy all extracted package files into this directory.
cp .env.example .env
chmod 600 .env
nano .env
```
Fill `DASHBOARD_HOST`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `THREADS_ACCESS_TOKEN`, and `SECRET_API_KEY`. Generate a random secret with `openssl rand -hex 32`. Leave `THREADS_PUBLISH_ENABLED=false` during setup.

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 ai-secretary
docker compose exec ai-secretary python -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8000/health").read().decode())'
```

**Network:** `compose.yaml` intentionally uses `expose` rather than `ports`; the service is reachable only on the Docker network. Configure your HTTPS reverse proxy on the same Docker network, or deploy via Coolify (see next section). Never forward unauthenticated traffic directly to port 8000.

## 3. Install with Coolify
1. Create a new project, environment and application; select **Dockerfile** source (upload/repository containing this folder).
2. Set Dockerfile path to `Dockerfile`, internal port `8000`, and domain to `https://threads.example.com`.
3. Enter all `.env.example` keys in Coolify's **Environment Variables**, replacing placeholder values. Start with `THREADS_PUBLISH_ENABLED=false`.
4. Attach **persistent storage** at `/app/data` (e.g. a Docker volume). Do this **before first deployment**.
5. Deploy. Verify `GET /health` returns status `ok`.
6. In Cloudflare DNS, point the subdomain at your HTTPS reverse proxy / tunnel. Enable Cloudflare Zero Trust Access application for that exact hostname. Add only your own approved identity to its Access policy.
7. Copy the Access application's **AUD tag** and team domain into Coolify env, then redeploy.
8. Open `https://threads.example.com/dashboard`; complete Cloudflare Access login. Create a test draft, approve/reject it. Do not publish yet.

**Security caveat:** This app trusts `cf-access-jwt-assertion` only after cryptographic verification, but for defense in depth restrict direct origin access and sanitize proxy-forwarded headers at your reverse proxy. Never use `--forwarded-allow-ips '*'` on a publicly reachable app without a trusted proxy boundary; configure trusted proxy IPs for a hardened production deployment.

## 4. Meta Developer / Threads setup
1. Create or reuse a Meta Developer App with Threads API product and a Threads account authorized for your app's mode.
2. Configure any required OAuth redirect URL, scopes and app settings in Meta Developer. For a private development app, only permitted/test accounts can access APIs.
3. Obtain an access token using the Meta-approved Threads OAuth/token flow. Use a long-lived token where supported and arrange renewal **before expiry**.
4. Store token as `THREADS_ACCESS_TOKEN` in server environment; never put it in frontend code or repository.
5. Test account identity read-only (run inside the container):
```bash
docker compose exec -T ai-secretary python - <<'PY'
import os,httpx
r=httpx.get('https://graph.threads.net/v1.0/me',headers={'Authorization':'Bearer '+os.environ['THREADS_ACCESS_TOKEN']},params={'fields':'id,username'},timeout=15)
print('HTTP',r.status_code,'USERNAME',r.json().get('username') if r.status_code==200 else 'unavailable')
PY
```
6. Do not switch Meta app to Live solely because this private app is hosted online. Follow Meta's current policy for app review and permissions if expanding to other users.

## 5. Google AI Studio setup
1. Create/reuse a Gemini API key in Google AI Studio and ensure API access/billing/quota match your plan.
2. Put it in `GEMINI_API_KEY`, and select a currently supported model ID via `GEMINI_MODEL`.
3. Use dashboard to create a draft. No content is published merely by generating a draft.

## 6. Publish a post (optional, LIVE action)
1. Confirm the target Threads account using `/v1.0/me` and review the draft in the dashboard.
2. Back up the SQLite database.
3. Explicitly set `THREADS_PUBLISH_ENABLED=true` and redeploy/restart the app.
4. Approve a draft, click **Publish to Threads** **once**, confirm, and wait.
5. Verify the post on Threads and in SQLite. If a timeout or `needs_review` occurs, **do not retry** until you have checked Threads manually.
6. Set `THREADS_PUBLISH_ENABLED=false` and restart after testing if you want to block further live posts.

## 7. Backup / restore / migrate existing data
**Before migration**, stop writes to the old instance and take a SQLite-consistent backup using Python's `sqlite3.Connection.backup()` (not a blind copy while SQLite is active). Keep old service running until new instance is verified; do not let both instances publish with the same token simultaneously.

For Coolify, copy the backup into the new persistent `/app/data/secretary.db` **before** starting the new application. The app automatically adds missing columns from older schemas. It preserves existing `published` records and does not reset them to `approved`.

For Docker Compose, easiest migration is to copy the backup into the named volume using a temporary container, while the app is stopped:
```bash
docker compose stop ai-secretary
# Place secretary-backup.db in the current directory first.
docker run --rm -v "$(pwd):/backup:ro" -v "$(basename "$(pwd)")_secretary-data:/data" alpine sh -c 'cp /backup/secretary-backup.db /data/secretary.db && chown 1000:1000 /data/secretary.db'
docker compose up -d
```
**Important:** Compose volume names depend on the Compose project name. Check `docker volume ls` and replace the volume name above with the exact one. If your old DB schema differs, inspect a backup and test migration in staging first. Do not overwrite an existing production DB without an independent backup.

## 8. Verify database
```bash
docker compose exec -T ai-secretary python - <<'PY'
import sqlite3
with sqlite3.connect('/app/data/secretary.db') as c:
 print('integrity:',c.execute('PRAGMA integrity_check').fetchone()[0])
 for row in c.execute('SELECT id,status,publish_state,publish_stage,threads_post_id FROM drafts ORDER BY id'):print(row)
PY
```

## 9. Security / operations checklist
- Never expose `.env`, token values, database or port 8000 publicly.
- Protect the dashboard using Cloudflare Access; use HTTPS only.
- Restrict origin to Cloudflare Tunnel or firewall/known proxy addresses.
- Keep `THREADS_PUBLISH_ENABLED=false` unless intentionally publishing.
- Back up SQLite regularly and test restore; persistent volume is not a backup.
- Rotate credentials if leaked; monitor token expiry and API quotas.
- Review all generated drafts before approval; AI text can contain inaccuracies.
- Manual deletion of a post on Threads does not automatically change its local `published` history.
- This build does **not** include token auto-renewal, scheduled posting, analytics, reply automation or multi-user roles.
- A failed publishing response may mean Threads actually published the post. Never blindly retry.

## 10. Troubleshooting
- **401 on dashboard**: Cloudflare Access JWT missing/invalid; check team domain and AUD.
- **403 on dashboard**: Hostname mismatch; check `DASHBOARD_HOST` and reverse proxy.
- **403 on publish**: expected when `THREADS_PUBLISH_ENABLED=false`.
- **403 on write**: Origin mismatch; access dashboard through configured HTTPS hostname.
- **Gemini 502**: API key, model, quota, or network issue.
- **Threads 502**: inspect `publish_state`, `publish_stage`, and Threads account; do not retry automatically.
- **SQLite permission error**: ensure persistent `/app/data` is writable by UID 1000.

## Differences from original tested app
This is a reconstructed portable release. The UI and some endpoints may differ from the live Coolify Dockerfile; import the exact current `main.py`/Dockerfile from your existing server if you need a byte-for-byte clone. This package adds a **default-off Publish Lock** for safety.
