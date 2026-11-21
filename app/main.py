import os, sqlite3, secrets, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import httpx, jwt
from jwt import PyJWKClient
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_PATH = os.getenv('DB_PATH', '/app/data/secretary.db')
DASHBOARD_HOST = os.getenv('DASHBOARD_HOST', 'threads.example.com').lower()
TEAM_DOMAIN = os.getenv('CF_ACCESS_TEAM_DOMAIN', '').removeprefix('https://').strip('/')
AUD = os.getenv('CF_ACCESS_AUD', '')
ISSUER = f'https://{TEAM_DOMAIN}'
JWKS = PyJWKClient(f'{ISSUER}/cdn-cgi/access/certs') if TEAM_DOMAIN else None
app = FastAPI(title='Personal AI Secretary for Threads', version='1.0.0')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

@contextmanager
def database():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def initialize():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with database() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          topic TEXT NOT NULL, content TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          approved_at TEXT, threads_container_id TEXT, threads_post_id TEXT,
          published_at TEXT,
          publish_state TEXT NOT NULL DEFAULT 'not_started',
          publish_started_at TEXT, publish_error TEXT,
          publish_stage TEXT NOT NULL DEFAULT 'not_started',
          publish_attempt_id TEXT, publish_updated_at TEXT
        )''')
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(drafts)')}
        additions = {
          'approved_at':'TEXT','threads_container_id':'TEXT','threads_post_id':'TEXT',
          'published_at':'TEXT','publish_state':"TEXT NOT NULL DEFAULT 'not_started'",
          'publish_started_at':'TEXT','publish_error':'TEXT',
          'publish_stage':"TEXT NOT NULL DEFAULT 'not_started'",
          'publish_attempt_id':'TEXT','publish_updated_at':'TEXT'
        }
        for name, spec in additions.items():
            if name not in columns: conn.execute(f'ALTER TABLE drafts ADD COLUMN {name} {spec}')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_drafts_threads_post_id ON drafts(threads_post_id) WHERE threads_post_id IS NOT NULL')

@app.on_event('startup')
def startup(): initialize()

@app.get('/health')
def health(): return {'status':'ok','version':'1.0.0'}

def dashboard_auth(request: Request):
    if request.url.hostname != DASHBOARD_HOST:
        raise HTTPException(403, 'Dashboard hostname required')
    if not JWKS or not AUD:
        raise HTTPException(503, 'Cloudflare Access not configured')
    token = request.headers.get('cf-access-jwt-assertion')
    if not token: raise HTTPException(401, 'Cloudflare Access token required')
    try:
        key = JWKS.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=['RS256'], audience=AUD,
                          issuer=ISSUER, options={'require':['exp','iss','aud']})
    except Exception:
        raise HTTPException(401, 'Invalid Cloudflare Access token')

def write_auth(request: Request, claims=Depends(dashboard_auth)):
    if request.headers.get('origin') != f'https://{DASHBOARD_HOST}':
        raise HTTPException(403, 'Invalid origin')
    return claims

def api_auth(request: Request):
    expected = os.getenv('SECRET_API_KEY', '')
    supplied = request.headers.get('x-api-key','')
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, 'Invalid API key')

class TopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=250)

async def generate(topic):
    key = os.getenv('GEMINI_API_KEY','')
    model = os.getenv('GEMINI_MODEL','gemini-2.5-flash')
    if not key: raise HTTPException(503,'Gemini API key missing')
    prompt = ('Tulis satu postingan Threads bahasa Indonesia natural, menarik, orisinal, '
              'maksimal 480 karakter. Tanpa HTML, Markdown, hashtag berlebihan, atau '
              'klaim pengalaman pribadi yang tidak diketahui. Hanya keluarkan teks postingan. '
              f'Topik: {topic}')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, headers={'x-goog-api-key':key},
              json={'contents':[{'parts':[{'text':prompt}]}],
                    'generationConfig':{'temperature':0.8,'maxOutputTokens':600}})
            resp.raise_for_status()
            text = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        raise HTTPException(502,'Gemini generation failed')
    if not text or len(text)>500:
        raise HTTPException(422,'Generated content invalid or over 500 characters; retry')
    return text

@app.get('/ui/drafts')
def list_drafts(claims=Depends(dashboard_auth)):
    with database() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM drafts ORDER BY id DESC')]

@app.post('/ui/draft')
async def create_draft(body:TopicRequest, claims=Depends(write_auth)):
    content = await generate(body.topic)
    with database() as conn:
        cursor=conn.execute('INSERT INTO drafts(topic,content) VALUES(?,?)',(body.topic,content))
        draft_id=cursor.lastrowid
    return {'id':draft_id,'status':'pending','content':content}

@app.post('/ui/drafts/{draft_id}/approve')
def approve(draft_id:int, claims=Depends(write_auth)):
    with database() as conn:
        c=conn.execute("UPDATE drafts SET status='approved',approved_at=? WHERE id=? AND status='pending' AND publish_state='not_started'",(now(),draft_id))
        if c.rowcount!=1: raise HTTPException(409,'Draft not pending')
    return {'id':draft_id,'status':'approved'}

@app.post('/ui/drafts/{draft_id}/reject')
def reject(draft_id:int, claims=Depends(write_auth)):
    with database() as conn:
        c=conn.execute("UPDATE drafts SET status='rejected' WHERE id=? AND status='pending' AND publish_state='not_started'",(draft_id,))
        if c.rowcount!=1: raise HTTPException(409,'Draft not pending')
    return {'id':draft_id,'status':'rejected'}

@app.post('/ui/drafts/{draft_id}/publish')
async def publish(draft_id:int, claims=Depends(write_auth)):
    # Fail closed: explicitly enable in environment before live publishing.
    if os.getenv('THREADS_PUBLISH_ENABLED','false').lower() != 'true':
        raise HTTPException(403,'Publishing disabled by administrator')
    token=os.getenv('THREADS_ACCESS_TOKEN','')
    if not token: raise HTTPException(503,'Threads token missing')
    attempt=str(uuid.uuid4())
    with database() as conn:
        c=conn.execute('''UPDATE drafts SET publish_state='processing',publish_stage='claimed',
             publish_attempt_id=?,publish_started_at=?,publish_updated_at=?,publish_error=NULL
             WHERE id=? AND status='approved' AND publish_state='not_started'
             AND publish_stage='not_started' AND threads_container_id IS NULL
             AND threads_post_id IS NULL''',(attempt,now(),now(),draft_id))
        if c.rowcount!=1: raise HTTPException(409,'Draft already published or publishing')
        content=conn.execute('SELECT content FROM drafts WHERE id=?',(draft_id,)).fetchone()['content']
    def update(stage, **fields):
        allowed={'threads_container_id','threads_post_id','published_at','publish_error','publish_state','status'}
        if not set(fields)<=allowed: raise ValueError('Invalid field')
        parts=['publish_stage=?','publish_updated_at=?']
        values=[stage,now()]
        for k,v in fields.items(): parts.append(f'{k}=?');values.append(v)
        values.extend([draft_id,attempt])
        with database() as conn:
            c=conn.execute(f"UPDATE drafts SET {','.join(parts)} WHERE id=? AND publish_attempt_id=? AND publish_state IN ('processing','needs_review')",values)
            if c.rowcount!=1: raise RuntimeError('Publish state changed')
    try:
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            update('container_request_started')
            r=await client.post('https://graph.threads.net/v1.0/me/threads',
              headers={'Authorization':f'Bearer {token}'},
              data={'media_type':'TEXT','text':content,'auto_publish_text':'false'})
            r.raise_for_status()
            container_id=str(r.json()['id'])
            update('container_created',threads_container_id=container_id)
            update('publish_request_started')
            r=await client.post('https://graph.threads.net/v1.0/me/threads_publish',
              headers={'Authorization':f'Bearer {token}'},data={'creation_id':container_id})
            r.raise_for_status()
            post_id=str(r.json()['id'])
            update('published',publish_state='published',status='published',
              threads_post_id=post_id,published_at=now(),publish_error=None)
            return {'id':draft_id,'status':'published','threads_post_id':post_id}
    except Exception as exc:
        try: update('needs_review',publish_state='needs_review',publish_error=type(exc).__name__)
        except Exception: pass
        raise HTTPException(502,'Publishing outcome uncertain; inspect Threads manually; do not retry')

@app.get('/drafts',dependencies=[Depends(api_auth)])
def api_drafts():
    with database() as conn: return [dict(r) for r in conn.execute('SELECT * FROM drafts ORDER BY id DESC')]

@app.post('/draft',dependencies=[Depends(api_auth)])
async def api_draft(body:TopicRequest):
    content=await generate(body.topic)
    with database() as conn:
        c=conn.execute('INSERT INTO drafts(topic,content) VALUES(?,?)',(body.topic,content))
    return {'id':c.lastrowid,'content':content,'status':'pending'}

DASHBOARD = r'''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Secretary for Threads</title><style>
:root{font-family:system-ui,Arial;background:#f5f6f9;color:#19202a}body{max-width:850px;margin:32px auto;padding:0 18px}h1{font-size:1.65rem}.card{background:white;border:1px solid #dce1e9;border-radius:12px;padding:18px;margin:16px 0;white-space:pre-wrap}textarea,input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #c8cdd8;border-radius:8px;font:inherit}button{background:#1b4e9b;color:white;border:0;border-radius:8px;padding:9px 13px;margin:8px 6px 0 0;cursor:pointer}button:disabled{opacity:.45}.muted{color:#586474;font-size:.88rem}.tag{font-weight:700}#message{white-space:pre-wrap}
</style></head><body><h1>Personal AI Secretary · Threads</h1><p class="muted">Private dashboard · Manual approval</p><section class="card"><label for="topic">Topik draf baru</label><input id="topic" maxlength="250" placeholder="Contoh: Manfaat AI untuk pekerjaan"><button id="create">Buat Draf dengan Gemini</button><p id="message" role="status"></p></section><h2>Daftar Draf</h2><div id="drafts"></div><script>
const msg=document.getElementById('message');
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
async function request(url,method='GET',body){const options={method,credentials:'same-origin',headers:{}};if(body){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}const r=await fetch(url,options);const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.detail||'HTTP '+r.status);return data}
async function load(){const data=await request('/ui/drafts');const target=document.getElementById('drafts');target.replaceChildren();for(const d of data){const c=node('article',undefined,'card');c.append(node('div','#'+d.id+' · '+d.topic,'tag'),node('p',d.content),node('p','Status: '+d.status+' · Publish: '+d.publish_state,'muted'));if(d.threads_post_id)c.append(node('p','Post ID: '+d.threads_post_id,'muted'));if(d.publish_state==='processing'||d.publish_state==='needs_review')c.append(node('p','Review required; check Threads manually. Do not retry.','muted'));if(d.status==='pending'){action(c,'Approve',d.id,'approve');action(c,'Reject',d.id,'reject')}if(d.status==='approved'&&d.publish_state==='not_started'&&d.publish_stage==='not_started'){action(c,'Publish to Threads',d.id,'publish')}target.append(c)}}
function action(card,label,id,operation){const b=node('button',label);b.onclick=async()=>{if(operation==='publish'&&!confirm('Publikasikan Draft #'+id+' ke Threads sekarang?'))return;b.disabled=true;msg.textContent='Memproses...';try{await request('/ui/drafts/'+id+'/'+operation,'POST');msg.textContent='Selesai';await load()}catch(e){msg.textContent='Error: '+e.message;await load().catch(()=>{})}finally{b.disabled=false}};card.append(b)}
document.getElementById('create').onclick=async()=>{const topic=document.getElementById('topic').value.trim();if(topic.length<3){msg.textContent='Topik minimal 3 karakter';return}const b=document.getElementById('create');b.disabled=true;msg.textContent='Gemini sedang membuat draf...';try{await request('/ui/draft','POST',{topic});msg.textContent='Draf berhasil dibuat';await load()}catch(e){msg.textContent='Error: '+e.message}finally{b.disabled=false}};
load().catch(e=>{msg.textContent='Tidak dapat memuat draf: '+e.message});</script></body></html>'''

@app.get('/dashboard',response_class=HTMLResponse)
def dashboard(claims=Depends(dashboard_auth)):
    return DASHBOARD
