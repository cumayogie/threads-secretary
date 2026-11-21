# Panduan Instalasi — AI Secretary for Threads

Panduan ini untuk **Docker Compose** atau **Coolify** saja. Tidak perlu menjalankan `main.py` secara manual. Seluruh perintah dijalankan dari direktori repository yang berisi `compose.yaml` dan `Dockerfile`.

> **Penting:** Paket ini adalah rekonstruksi portabel dari aplikasi yang diuji, bukan ekspor identik dari Dockerfile produksi sebelumnya. Uji pada server staging terlebih dahulu. Publikasi Threads **nonaktif secara default** (`THREADS_PUBLISH_ENABLED=false`).

## 1. Prasyarat

- Server Linux (contoh Ubuntu 22.04/24.04) dengan Docker Engine dan Docker Compose plugin **atau** instalasi Coolify yang aktif.
- Domain/subdomain milik sendiri, HTTPS reverse proxy atau Cloudflare Tunnel, dan Cloudflare Zero Trust Access.
- Meta Developer App dengan akses Threads API untuk akun yang diizinkan; access token yang masih berlaku dengan izin `threads_basic` dan `threads_content_publish`.
- API key Google Gemini dari Google AI Studio dan nama model yang tersedia di project tersebut.
- Source code repository ini. **Jangan mengunggah file `.env`, database `.db`, backup, atau access token ke GitHub.**

## 2. Siapkan repository GitHub

1. Buat repository **Private** di GitHub, misalnya `ai-secretary-threads`.
2. Upload isi folder paket ini **ke root repository**: `app/`, `Dockerfile`, `compose.yaml`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, dan `INSTALLATION.md`.
3. Pastikan `.env` **tidak** ikut terunggah. File `.env.example` aman diunggah karena hanya berisi placeholder.
4. Jangan menyimpan kredensial di `compose.yaml`, `Dockerfile`, atau source Python.

Struktur:

```text
ai-secretary-threads/
├── app/
│   └── main.py
├── .env.example
├── .gitignore
├── Dockerfile
├── compose.yaml
├── requirements.txt
├── README.md
└── INSTALLATION.md
```

## 3A. Instalasi dengan Docker Compose

### A. Pasang Docker

Gunakan petunjuk resmi Docker untuk distribusi Linux Anda: https://docs.docker.com/engine/install/ubuntu/ . Pastikan kedua perintah berikut berhasil:

```bash
docker --version
docker compose version
```

### B. Ambil source code

```bash
git clone https://github.com/USERNAME/ai-secretary-threads.git
cd ai-secretary-threads
```

Ganti `USERNAME` dan nama repository sesuai GitHub Anda. Untuk repository private, gunakan akses GitHub yang sah (SSH key atau credential manager); jangan menaruh personal access token di URL yang disimpan pada shell history.

### C. Atur konfigurasi

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Isi sesuai lingkungan Anda:

```dotenv
DASHBOARD_HOST=threads.example.com
CF_ACCESS_TEAM_DOMAIN=your-team.cloudflareaccess.com
CF_ACCESS_AUD=REPLACE_WITH_ACCESS_AUD_TAG
GEMINI_API_KEY=REPLACE_WITH_GEMINI_KEY
GEMINI_MODEL=gemini-2.5-flash
THREADS_ACCESS_TOKEN=REPLACE_WITH_THREADS_LONG_LIVED_TOKEN
SECRET_API_KEY=REPLACE_WITH_LONG_RANDOM_SECRET
DB_PATH=/app/data/secretary.db
THREADS_PUBLISH_ENABLED=false
```

- `DASHBOARD_HOST`: hostname **tanpa** `https://` atau path.
- `CF_ACCESS_TEAM_DOMAIN`: domain team Cloudflare Access.
- `CF_ACCESS_AUD`: AUD tag dari aplikasi Cloudflare Access yang melindungi hostname dashboard.
- `GEMINI_MODEL`: gunakan model ID yang memang tersedia di Google AI Studio; contoh di atas bisa berubah ketersediaannya.
- `SECRET_API_KEY`: buat nilai acak dengan `openssl rand -hex 32`.
- `DB_PATH`: biarkan `/app/data/secretary.db` untuk Docker.
- `THREADS_PUBLISH_ENABLED`: **tetap `false`** sampai Anda benar-benar siap melakukan publikasi nyata.

### D. Build dan jalankan

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 ai-secretary
```

Verifikasi health check **dari dalam container**:

```bash
docker compose exec ai-secretary python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode())'
```

**Jaringan:** `compose.yaml` hanya menggunakan `expose: 8000`, bukan `ports`. Artinya aplikasi tidak otomatis tersedia di `http://IP-SERVER:8000`. Hubungkan reverse proxy HTTPS atau Cloudflare Tunnel ke service di jaringan Docker yang sesuai. Jika proxy berada di luar jaringan Compose, Anda harus mengatur konektivitas internal secara aman. **Jangan mengekspos port 8000 langsung ke internet.**

### E. Domain dan Cloudflare Access

1. Siapkan reverse proxy HTTPS atau Cloudflare Tunnel yang meneruskan request untuk `threads.example.com` ke aplikasi port internal `8000`.
2. Di Cloudflare Zero Trust, buat aplikasi **Access → Applications → Self-hosted** untuk hostname tersebut.
3. Batasi policy **Allow** hanya untuk email/identitas pribadi Anda.
4. Masukkan AUD tag dan team domain ke `.env` lalu jalankan `docker compose up -d --force-recreate` jika nilainya berubah.
5. Buka `https://threads.example.com/dashboard`, login melalui Cloudflare Access.
6. Coba buat draf, Approve, dan Reject. **Jangan klik Publish untuk tes awal.**

## 3B. Instalasi dengan Coolify

1. Login ke Coolify dan buat **Project → Environment → New Resource → Application**.
2. Pilih sumber **Git Repository** yang berisi file-file di atas. Hubungkan akun GitHub/deploy key jika repository private.
3. Pilih build pack **Dockerfile**, dengan path `Dockerfile` di root repository. Gunakan port internal **8000**.
4. Atur domain aplikasi ke `https://threads.example.com` (ganti dengan domain Anda), dan pastikan HTTPS aktif pada reverse proxy.
5. Tambahkan seluruh variabel dari `.env.example` melalui menu **Environment Variables** di Coolify. **Jangan mengunggah `.env` ke GitHub.**
6. Tambahkan **Persistent Storage**: Docker volume yang di-mount ke `/app/data`. Lakukan **sebelum deploy pertama** supaya database SQLite tidak hilang saat container diganti.
7. Pastikan `THREADS_PUBLISH_ENABLED=false`, lalu klik **Deploy**.
8. Periksa log dan health check `/health`. Sesuaikan DNS Cloudflare dengan IP/proxy atau Tunnel server Coolify.
9. Di Cloudflare Zero Trust, buat aplikasi Access untuk hostname yang sama; batasi akses ke akun pribadi Anda. Salin AUD tag ke Coolify dan **Redeploy**.
10. Buka `https://threads.example.com/dashboard`, login, buat draf, lalu uji Approve/Reject.

**Catatan keamanan Coolify:** Jangan membiarkan origin dapat diakses bebas dengan Host header palsu. Gunakan Cloudflare Tunnel atau pembatasan firewall/proxy, dan pastikan header identitas dari client tidak dipercaya tanpa validasi JWT. Untuk produksi, audit konfigurasi `--forwarded-allow-ips` pada Dockerfile dan batasi proxy yang dipercaya.

## 4. Verifikasi akun Threads tanpa publikasi

Untuk Docker Compose:

```bash
docker compose exec -T ai-secretary python - <<'PY'
import os, httpx
r = httpx.get(
    'https://graph.threads.net/v1.0/me',
    headers={'Authorization': 'Bearer ' + os.environ['THREADS_ACCESS_TOKEN']},
    params={'fields': 'id,username'}, timeout=15,
)
print('HTTP:', r.status_code)
if r.status_code == 200:
    print('Username:', r.json().get('username'))
else:
    print('Review token, permissions and API access')
PY
```

Untuk Coolify, buka terminal container dan jalankan kode Python yang sama tanpa awalan `docker compose exec -T ai-secretary`.

Jangan mencetak access token atau menyimpan output yang berisi rahasia ke GitHub Issues.

## 5. Alur penggunaan

1. Buka `/dashboard` melalui hostname HTTPS yang sudah dilindungi Cloudflare Access.
2. Masukkan topik dan klik tombol pembuatan draf. Gemini membuat konten; database menyimpan draf dengan status `pending`.
3. Tinjau konten. Klik **Approve** atau **Reject**.
4. Dengan `THREADS_PUBLISH_ENABLED=false`, endpoint Publish menolak pengiriman nyata meskipun tombol mungkin masih muncul di UI.
5. Jika ingin publikasi nyata, pastikan akun dan konten benar, backup database, lalu secara sengaja ubah `THREADS_PUBLISH_ENABLED=true` dan **recreate/redeploy** aplikasi. Klik Publish **sekali**.
6. Jika terjadi HTTP 502, timeout, `processing`, atau `needs_review`, **jangan klik Publish lagi**. Periksa akun Threads dan database lebih dahulu karena hasilnya mungkin sudah terbit.
7. Setelah selesai tes, kembalikan `THREADS_PUBLISH_ENABLED=false` dan recreate/redeploy aplikasi.

**Perintah perubahan environment pada Compose:** sesudah mengedit `.env`, gunakan `docker compose up -d --force-recreate` (sekadar `docker compose restart` tidak menjamin environment baru diterapkan). Pada Coolify, simpan Environment Variables lalu **Redeploy**.

## 6. Operasional dan backup

Perintah Compose:

```bash
docker compose ps
docker compose logs -f ai-secretary
docker compose stop ai-secretary
docker compose up -d
docker compose up -d --build
```

**Jangan jalankan `docker compose down -v`**, karena `-v` dapat menghapus volume database.

Backup SQLite secara konsisten dari container Compose:

```bash
docker compose exec -T ai-secretary python - <<'PY'
import sqlite3, datetime
from pathlib import Path
src = '/app/data/secretary.db'
dst = '/app/data/secretary-backup-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S') + '.db'
with sqlite3.connect(src) as source, sqlite3.connect(dst) as backup:
    source.backup(backup)
print('Backup:', dst)
PY
```

Backup di dalam volume tetap perlu **disalin ke penyimpanan terpisah** agar aman jika server atau volumenya hilang. Untuk restore/migrasi, hentikan aplikasi, backup kondisi saat ini, salin database hasil backup ke volume `/app/data`, pastikan owner dapat ditulis UID `1000`, lalu jalankan kembali. Uji migrasi terlebih dahulu pada server staging. **Jangan jalankan dua instance aktif dengan token Threads yang sama jika keduanya dapat memublikasikan.**

## 7. Troubleshooting

| Masalah | Pemeriksaan |
| --- | --- |
| Dashboard 401 | Cloudflare Access JWT, team domain, AUD tag |
| Dashboard 403 | Hostname `DASHBOARD_HOST` atau Origin tidak sesuai |
| Publish 403 | Normal jika `THREADS_PUBLISH_ENABLED=false` |
| Gemini gagal | API key, model ID, kuota, akses jaringan |
| Threads API gagal | Token, izin, akun target, masa berlaku token |
| Publish timeout/502 | Jangan retry otomatis; cek Threads dan status database |
| SQLite permission denied | Persistent volume `/app/data` harus dapat ditulis UID 1000 |
| Container berjalan tetapi URL tidak terbuka | Reverse proxy, DNS, HTTPS, Cloudflare Access, jaringan Docker |

## 8. Catatan keamanan dan batasan

- Aplikasi ini **untuk penggunaan pribadi**, bukan layanan multi-tenant publik.
- Meta App boleh tetap dalam Development Mode selama penggunaan dan akun diizinkan oleh Meta; fitur tertentu mungkin memerlukan izin/review tambahan.
- Tidak ada fitur token renewal otomatis, content calendar, scheduling, analytics, atau AI reply assistant dalam paket ini.
- Riwayat `published` di database tidak otomatis berubah jika postingan dihapus manual di Threads.
- Source code ini belum dinyatakan identik dengan versi produksi lama. Jangan mengganti deployment produksi tanpa backup, review perubahan, dan pengujian staging.
