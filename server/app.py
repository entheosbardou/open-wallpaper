import hashlib, hmac, json, mimetypes, os, secrets, time, base64, io, shutil, urllib.parse
import threading
from contextlib import contextmanager
import pymysql
from pymysql.cursors import DictCursor
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA=Path(os.environ.get('DATA_DIR','./data')); DATA.mkdir(parents=True,exist_ok=True)
_db_init_lock=threading.Lock()
_db_initialized=False
_db_bootstrapping=False
MEDIA=DATA/'media'; MEDIA.mkdir(exist_ok=True)
WEB=Path(__file__).resolve().parent.parent/'web'
MAX_BYTES=100*1024*1024
TYPES={'.jpg':('image/jpeg','image'),'.jpeg':('image/jpeg','image'),'.png':('image/png','image'),'.webp':('image/webp','image'),'.gif':('image/gif','image'),'.mp4':('video/mp4','video'),'.webm':('video/webm','video')}
app=FastAPI(title='Open Wallpaper Server',version='0.5.1',docs_url=None,redoc_url=None)

@contextmanager
def db():
    if not _db_initialized and not _db_bootstrapping:init()
    con=None
    for attempt in range(30):
        try:
            con=pymysql.connect(host=os.environ.get('DB_HOST','mysql'),port=int(os.environ.get('DB_PORT','3306')),
                user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],database=os.environ.get('DB_NAME','open_wallpaper'),
                charset='utf8mb4',autocommit=False,cursorclass=DictCursor,connect_timeout=10)
            break
        except pymysql.err.OperationalError:
            if attempt==29:raise
            time.sleep(2)
    try:
        with con.cursor() as cursor: yield cursor
        con.commit()
    except Exception:
        con.rollback();raise
    finally: con.close()

def init():
    global _db_initialized,_db_bootstrapping
    if _db_initialized:return
    with _db_init_lock:
        if _db_initialized:return
        statements=(
        "CREATE TABLE IF NOT EXISTS sessions(token_hash VARCHAR(64) PRIMARY KEY, expires BIGINT NOT NULL, user_id VARCHAR(64)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS media(id VARCHAR(64) PRIMARY KEY,name VARCHAR(255) NOT NULL,filename VARCHAR(1024) NOT NULL,kind VARCHAR(16) NOT NULL,mime VARCHAR(128) NOT NULL,folder_id VARCHAR(64), INDEX media_folder_id(folder_id),INDEX media_filename(filename(191))) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS scenes(id VARCHAR(64) PRIMARY KEY,name VARCHAR(255) NOT NULL,manifest LONGTEXT NOT NULL,owner_id VARCHAR(64),visibility VARCHAR(32) NOT NULL DEFAULT 'private') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS devices(id VARCHAR(64) PRIMARY KEY,name VARCHAR(255) NOT NULL,token_hash VARCHAR(64) NOT NULL UNIQUE,scene_id VARCHAR(64),created BIGINT NOT NULL,playlist_id VARCHAR(64),owner_id VARCHAR(64)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS pairing(code_hash VARCHAR(64) PRIMARY KEY,device_name VARCHAR(255) NOT NULL,expires BIGINT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS playlists(id VARCHAR(64) PRIMARY KEY,name VARCHAR(255) NOT NULL,items LONGTEXT NOT NULL,interval_seconds INT NOT NULL,shuffle TINYINT NOT NULL,owner_id VARCHAR(64),visibility VARCHAR(32) NOT NULL DEFAULT 'private') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS qr_invites(token_hash VARCHAR(64) PRIMARY KEY,expires BIGINT NOT NULL,owner_id VARCHAR(64)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS folders(id VARCHAR(64) PRIMARY KEY,name VARCHAR(255) NOT NULL,parent_id VARCHAR(64),INDEX folders_parent_id(parent_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS users(id VARCHAR(64) PRIMARY KEY,username VARCHAR(60) UNIQUE NOT NULL,salt VARCHAR(64),password_hash VARCHAR(255),role VARCHAR(16) NOT NULL DEFAULT 'user',enabled TINYINT NOT NULL DEFAULT 1,oidc_issuer VARCHAR(512),oidc_sub VARCHAR(255),UNIQUE KEY users_oidc(oidc_issuer(191),oidc_sub(191))) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS user_permissions(user_id VARCHAR(64) NOT NULL,permission VARCHAR(64) NOT NULL,allowed TINYINT NOT NULL,PRIMARY KEY(user_id,permission)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS resource_shares(kind VARCHAR(16) NOT NULL,resource_id VARCHAR(64) NOT NULL,recipient_id VARCHAR(64) NOT NULL,can_edit TINYINT NOT NULL DEFAULT 0,PRIMARY KEY(kind,resource_id,recipient_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS auth_states(state_hash VARCHAR(64) PRIMARY KEY,nonce VARCHAR(128) NOT NULL,verifier VARCHAR(128) NOT NULL,expires BIGINT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS folder_grants(folder_id VARCHAR(64) NOT NULL,user_id VARCHAR(64) NOT NULL,can_view TINYINT NOT NULL DEFAULT 0,can_use TINYINT NOT NULL DEFAULT 0,can_upload TINYINT NOT NULL DEFAULT 0,can_edit TINYINT NOT NULL DEFAULT 0,can_delete TINYINT NOT NULL DEFAULT 0,can_manage TINYINT NOT NULL DEFAULT 0,PRIMARY KEY(folder_id,user_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
        "CREATE TABLE IF NOT EXISTS claims(code_hash VARCHAR(64) PRIMARY KEY,token VARCHAR(128) NOT NULL,expires BIGINT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    )
        _db_bootstrapping=True
        try:
            with db() as c:
                for statement in statements:c.execute(statement)
        finally:
            _db_bootstrapping=False
        _db_initialized=True

PERMISSIONS=('media.view','media.upload','media.delete','folders.manage','scenes.create','playlists.create','devices.pair','devices.manage','sharing.manage','users.manage')
DEFAULT_PERMISSIONS={'media.view','media.upload','scenes.create','playlists.create','devices.pair','sharing.manage'}

FOLDER_RIGHTS=('view','use','upload','edit','delete','manage')
def folder_rights(c,user,fid):
    if user['role']=='admin':return {r:True for r in FOLDER_RIGHTS}
    result={r:False for r in FOLDER_RIGHTS}
    if fid is None:return result
    chain=[];seen=set()
    while fid:
        if fid in seen:raise HTTPException(400,'Folder cycle')
        seen.add(fid)
        c.execute('SELECT parent_id FROM folders WHERE id=%s',(fid,));row=c.fetchone()
        if not row:raise HTTPException(404,'Not found')
        chain.append(fid);fid=row['parent_id']
    for folder in reversed(chain):
        c.execute('SELECT * FROM folder_grants WHERE folder_id=%s AND user_id=%s',(folder,user['id']));row=c.fetchone()
        if row:
            for right in FOLDER_RIGHTS:result[right]=bool(row['can_'+right])
    return result

def folder_check(c,user,fid,right='view'):
    if not folder_rights(c,user,fid)[right]:raise HTTPException(404,'Not found')

def media_check(c,user,ident,right='view'):
    c.execute('SELECT * FROM media WHERE id=%s',(ident,));row=c.fetchone()
    if not row:raise HTTPException(404,'Not found')
    if not allowed(user,'media.view') and right in ('view','use'):raise HTTPException(404,'Not found')
    folder_check(c,user,row['folder_id'],right)
    return row

def filter_media_ids(c,user,ids,right='use'):
    result=[]
    for ident in ids:
        try:media_check(c,user,ident,right);result.append(ident)
        except HTTPException:pass
    return result

def visible_folder_ids(c,user):
    c.execute('SELECT id,parent_id FROM folders');rows=c.fetchall()
    visible={r['id'] for r in rows if folder_rights(c,user,r['id'])['view']}
    # Parents of permitted folders are navigation-only, not accessible folders.
    nav=set(visible)
    for fid in list(visible):
        while fid:
            c.execute('SELECT parent_id FROM folders WHERE id=%s',(fid,));row=c.fetchone()
            fid=row['parent_id'] if row else None
            if fid:nav.add(fid)
    return visible,nav

def current_user(req:Request):
    token=req.cookies.get('session','') or bearer(req)
    with db() as c:
        if token:
            c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires>%s AND u.enabled=1',(digest(token),int(time.time())))
            row=c.fetchone()
        else:row=None
    if not row:raise HTTPException(401,'Sign in required')
    return dict(row)

def allowed(user,permission):
    if user['role']=='admin':return True
    with db() as c:
        c.execute('SELECT allowed FROM user_permissions WHERE user_id=%s AND permission=%s',(user['id'],permission));row=c.fetchone()
    return bool(row['allowed']) if row else permission in DEFAULT_PERMISSIONS

def require(permission):
    def check(req:Request):
        u=current_user(req)
        if not allowed(u,permission):raise HTTPException(403,'Permission denied: '+permission)
        return u
    return check

def resource_access(c,user,kind,ident,edit=False):
    table={'scene':'scenes','playlist':'playlists','device':'devices'}[kind]
    c.execute(f'SELECT * FROM {table} WHERE id=%s',(ident,));r=c.fetchone()
    if not r:raise HTTPException(404,'Not found')
    if user['role']=='admin' or r['owner_id']==user['id']:return r
    if kind=='device':raise HTTPException(404,'Not found')
    c.execute('SELECT can_edit FROM resource_shares WHERE kind=%s AND resource_id=%s AND recipient_id IN (%s,%s)',(kind,ident,user['id'],'*'));share=c.fetchall()
    if (not edit and (r['visibility']=='everyone' or share)) or (edit and any(x['can_edit'] for x in share)):return r
    raise HTTPException(404,'Not found')

def visible(c,user,kind):
    table={'scene':'scenes','playlist':'playlists','device':'devices'}[kind]
    c.execute(f'SELECT * FROM {table} ORDER BY name');rows=c.fetchall()
    out=[]
    for r in rows:
        try:resource_access(c,user,kind,r['id']);out.append(r)
        except HTTPException:pass
    return out

def ensure_create(user,kind):
    permission={'scene':'scenes.create','playlist':'playlists.create'}[kind]
    if not allowed(user,permission):raise HTTPException(403,'Permission denied: '+permission)

def ensure_references(c,user,scene_id=None,playlist_id=None):
    if scene_id:resource_access(c,user,'scene',scene_id)
    if playlist_id:resource_access(c,user,'playlist',playlist_id)

def csrf_guard(req:Request):
    # Origin check on all state-changing cookie-authenticated calls.
    if req.method in ('GET','HEAD','OPTIONS') or not req.cookies.get('session'):return
    origin=req.headers.get('origin')
    if not origin:raise HTTPException(403,'Origin header required')
    expected=os.environ.get('PUBLIC_URL','').rstrip('/') or str(req.base_url).rstrip('/')
    if origin.rstrip('/')!=expected:raise HTTPException(403,'Invalid request origin')

@app.middleware('http')
async def security_middleware(req:Request,call_next):
    if req.url.path.startswith('/api/'):
        try:csrf_guard(req)
        except HTTPException as e:return JSONResponse({'detail':e.detail},status_code=e.status_code)
    return await call_next(req)

def folder_path(c, fid):
    parts=[];seen=set()
    while fid:
        if fid in seen:raise HTTPException(400,'Folder cycle')
        seen.add(fid)
        c.execute('SELECT name,parent_id FROM folders WHERE id=%s',(fid,));row=c.fetchone()
        if not row:raise HTTPException(404,'Folder not found')
        parts.append(row['name']);fid=row['parent_id']
    return Path(*reversed(parts)) if parts else Path()

def folder_name(name):
    name=name.strip()
    if not name or name in ('.','..') or '/' in name or chr(92) in name or any(ord(x)<32 for x in name):raise HTTPException(400,'Invalid folder name')
    return name

def unique_file(directory,name):
    name=Path(name).name;stem=Path(name).stem;ext=Path(name).suffix
    target=directory/name;i=1
    while target.exists():target=directory/f'{stem} ({i}){ext}';i+=1
    return target

def replace_media_refs(c,old_id,new_id):
    c.execute('SELECT id,items FROM playlists')
    for row in c.fetchall():
        items=json.loads(row['items'])
        updated=[new_id if x==old_id else x for x in items] if isinstance(items,list) else {**items,'media_ids':[new_id if x==old_id else x for x in items.get('media_ids',[])]}
        if updated!=items:c.execute('UPDATE playlists SET items=%s WHERE id=%s',(json.dumps(updated),row['id']))
    c.execute('SELECT id,manifest FROM scenes')
    for row in c.fetchall():
        manifest=json.loads(row['manifest']);changed=False
        for layer in manifest.get('layers',[]):
            if layer.get('media_id')==old_id:
                layer['media_id']=new_id;changed=True
        if changed:c.execute('UPDATE scenes SET manifest=%s WHERE id=%s',(json.dumps(manifest),row['id']))


def reconcile_media(c,physical):
    """Never remove a physical file. Repair only unambiguous matches."""
    c.execute('SELECT * FROM media ORDER BY id');rows=[dict(r) for r in c.fetchall()]
    by_path={}
    for row in rows:by_path.setdefault(row['filename'],[]).append(row)
    # Exact duplicate path: prefer a referenced ID, then the earliest existing ID.
    references=set()
    c.execute('SELECT items FROM playlists')
    for row in c.fetchall():
        items=json.loads(row['items']);references.update(items if isinstance(items,list) else items.get('media_ids',[]))
    c.execute('SELECT manifest FROM scenes')
    for row in c.fetchall():
        references.update(x.get('media_id') for x in json.loads(row['manifest']).get('layers',[]))
    for path,duplicates in by_path.items():
        if len(duplicates)<2:continue
        duplicates.sort(key=lambda r:(r['id'] not in references,rows.index(r)))
        winner=duplicates[0]
        for duplicate in duplicates[1:]:
            replace_media_refs(c,duplicate['id'],winner['id'])
            c.execute('DELETE FROM media WHERE id=%s',(duplicate['id'],))
    c.execute('SELECT * FROM media ORDER BY id');rows=[dict(r) for r in c.fetchall()]
    occupied={r['filename'] for r in rows if r['filename'] in physical}
    missing=[r for r in rows if r['filename'] not in physical]
    unindexed=set(physical)-occupied
    # If exactly one real file has a given basename and every index record
    # for that basename refers to that file or to a missing path, consolidate.
    # Never merge when two real files share a basename.
    names={Path(r['filename']).name for r in missing}
    for name in names:
        actual=[path for path in physical if Path(path).name==name]
        if len(actual)!=1:continue
        target=actual[0]
        candidates=[r for r in missing if Path(r['filename']).name==name]
        c.execute('SELECT * FROM media WHERE filename=%s',(target,));existing=c.fetchall()
        combined=existing+candidates
        if not combined:continue
        # Keep a referenced ID when possible, otherwise the oldest row.
        combined.sort(key=lambda r:(r['id'] not in references, next((i for i,x in enumerate(rows) if x['id']==r['id']),999999)))
        winner=combined[0]
        for duplicate in combined[1:]:
            replace_media_refs(c,duplicate['id'],winner['id'])
            c.execute('DELETE FROM media WHERE id=%s',(duplicate['id'],))
        c.execute('UPDATE media SET filename=%s,folder_id=%s,name=%s WHERE id=%s',
                  (target,physical[target],name,winner['id']))
        unindexed.discard(target)
    return unindexed


def sync_media():
    # Serialize concurrent HTTP requests so the same file is never imported twice.
    import threading
    with _media_sync_lock:
        with db() as c:
            c.execute('SELECT id FROM folders');folder_rows=c.fetchall()
            known={str(folder_path(c,r['id'])):r['id'] for r in folder_rows}
            physical={}
            for root,dirs,files in os.walk(MEDIA,followlinks=False):
                dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink() and not d.startswith('.')]
                relative=Path(root).relative_to(MEDIA)
                parent=None;walk=Path()
                for part in relative.parts:
                    walk=walk/part;key=str(walk)
                    if key not in known:
                        ident=uuid4().hex
                        c.execute('INSERT INTO folders VALUES(%s,%s,%s)',(ident,part,parent));known[key]=ident
                    parent=known[key]
                for filename in files:
                    full=Path(root)/filename
                    if full.is_symlink() or full.suffix.lower() not in TYPES:continue
                    physical[str(full.relative_to(MEDIA))]=parent
            unindexed=reconcile_media(c,physical)
            for rel in sorted(unindexed):
                mime,kind=TYPES[Path(rel).suffix.lower()]
                c.execute('INSERT INTO media(id,name,filename,kind,mime,folder_id) VALUES(%s,%s,%s,%s,%s,%s)',
                          (uuid4().hex,Path(rel).name,rel,kind,mime,physical[rel]))


import threading
_media_sync_lock=threading.Lock()

def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def hash_password(p,s): return hashlib.scrypt(p.encode(),salt=bytes.fromhex(s),n=2**14,r=8,p=1).hex()
def bearer(req):
    h=req.headers.get('authorization','')
    return h[7:] if h.startswith('Bearer ') else ''
def admin(req:Request):
    return current_user(req)
def device(req:Request):
    token=bearer(req)
    with db() as c:
        if token:c.execute('SELECT * FROM devices WHERE token_hash=%s',(digest(token),));row=c.fetchone()
        else:row=None
    if not row: raise HTTPException(401,'Device token required')
    return dict(row)

def clean_media(row):
    d=dict(row); d.pop('filename'); d['url']='/api/media/'+d['id']+'/file';return d

class Credentials(BaseModel):
    username:str=Field(min_length=3,max_length=60)
    password:str=Field(min_length=12,max_length=256)
class Scene(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    layers:list[dict]=Field(default_factory=list,max_length=40)
    canvas:dict=Field(default_factory=lambda:{'width':1920,'height':1080,'scaling':'cover'})
class DeviceAssign(BaseModel):
    scene_id:str|None=None
    playlist_id:str|None=None
class Playlist(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    media_ids:list[str]=Field(default_factory=list,max_length=500)
    folder_ids:list[str]=Field(default_factory=list,max_length=100)
    interval_seconds:int=Field(default=30,ge=3,le=86400)
    shuffle:bool=False
class BulkDelete(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=500)
class FolderInput(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    parent_id:str|None=None
class MoveMedia(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=500)
    folder_id:str|None=None
class Pair(BaseModel):
    code:str

@app.get('/api/health')
def health(): return {'status':'ok','version':'0.5.1'}
@app.get('/api/status')
def status():
    with db() as c:
        c.execute('SELECT 1 FROM users');setup_required=c.fetchone() is None
        return {'setup_required':setup_required,'oidc_enabled':bool(os.getenv('OIDC_ISSUER') and os.getenv('OIDC_CLIENT_ID'))}
@app.post('/api/setup')
def setup(body:Credentials):
    with db() as c:
        c.execute('SELECT GET_LOCK(%s,10) AS acquired',('open_wallpaper_initial_setup',));lock=c.fetchone()
        if not lock or lock['acquired']!=1:raise HTTPException(503,'Could not lock initial setup')
        c.execute('SELECT 1 FROM users')
        if c.fetchone():raise HTTPException(409,'Already configured')
        salt=secrets.token_hex(16);uid=uuid4().hex
        c.execute('INSERT INTO users(id,username,salt,password_hash,role) VALUES(%s,%s,%s,%s,%s)',(uid,body.username,salt,hash_password(body.password,salt),'admin'))
    return {'ok':True}

def login_response(uid):
    token=secrets.token_urlsafe(36)
    with db() as c:c.execute('INSERT INTO sessions(token_hash,expires,user_id) VALUES(%s,%s,%s)',(digest(token),int(time.time())+86400*7,uid))
    resp=JSONResponse({'ok':True});resp.set_cookie('session',token,httponly=True,samesite='lax',secure=os.getenv('PUBLIC_URL','').startswith('https://'),max_age=86400*7,path='/');return resp
@app.post('/api/login')
def login(body:Credentials):
    with db() as c:
        c.execute('SELECT * FROM users WHERE username=%s AND enabled=1',(body.username,));row=c.fetchone()
        if not row or not row['salt'] or not hmac.compare_digest(row['password_hash'],hash_password(body.password,row['salt'])):raise HTTPException(401,'Invalid credentials')
    return login_response(row['id'])
@app.post('/api/logout')
def logout(req:Request, _:dict=Depends(admin)):
    with db() as c:c.execute('DELETE FROM sessions WHERE token_hash=%s',(digest(req.cookies.get('session','') or bearer(req)),))
    resp=JSONResponse({'ok':True});resp.delete_cookie('session');return resp

@app.get('/api/me')
def me(u:dict=Depends(admin)):
    return {'id':u['id'],'username':u['username'],'role':u['role'],'permissions':{p:allowed(u,p) for p in PERMISSIONS}}

class NewUser(BaseModel):
    username:str=Field(min_length=3,max_length=60)
    password:str=Field(min_length=12,max_length=256)
    role:str='user'
class UserUpdate(BaseModel):
    enabled:bool|None=None
    role:str|None=None
    permissions:dict[str,bool]|None=None
    oidc_issuer:str|None=None
    oidc_sub:str|None=None
class ShareInput(BaseModel):
    recipient_id:str
    can_edit:bool=False

@app.get('/api/users')
def users(u:dict=Depends(require('users.manage'))):
    with db() as c:
        c.execute('SELECT * FROM users ORDER BY username')
        return [{**{k:r[k] for k in ('id','username','role','enabled','oidc_issuer','oidc_sub')},'permissions':{p:allowed(dict(r),p) for p in PERMISSIONS}} for r in c.fetchall()]
@app.post('/api/users')
def add_user(body:NewUser,u:dict=Depends(require('users.manage'))):
    if body.role not in ('admin','user'):raise HTTPException(400,'Invalid role')
    salt=secrets.token_hex(16);uid=uuid4().hex
    try:
        with db() as c:c.execute('INSERT INTO users(id,username,salt,password_hash,role) VALUES(%s,%s,%s,%s,%s)',(uid,body.username,salt,hash_password(body.password,salt),body.role))
    except pymysql.err.IntegrityError:raise HTTPException(409,'Username already exists')
    return {'id':uid}
@app.patch('/api/users/{uid}')
def change_user(uid:str,body:UserUpdate,u:dict=Depends(require('users.manage'))):
    if body.role is not None and body.role not in ('admin','user'):raise HTTPException(400,'Invalid role')
    if body.permissions and any(p not in PERMISSIONS for p in body.permissions):raise HTTPException(400,'Unknown permission')
    if uid==u['id'] and (body.enabled is False or body.role=='user'):raise HTTPException(400,'Cannot demote or disable yourself')
    with db() as c:
        c.execute('SELECT * FROM users WHERE id=%s',(uid,));r=c.fetchone()
        if not r:raise HTTPException(404)
        if body.role is not None:c.execute('UPDATE users SET role=%s WHERE id=%s',(body.role,uid))
        if body.enabled is not None:c.execute('UPDATE users SET enabled=%s WHERE id=%s',(int(body.enabled),uid))
        if body.oidc_issuer is not None or body.oidc_sub is not None:
            if not body.oidc_issuer or not body.oidc_sub or body.oidc_issuer!=os.getenv('OIDC_ISSUER',''):raise HTTPException(400,'OIDC issuer and subject required; issuer must match configured provider')
            c.execute('UPDATE users SET oidc_issuer=%s,oidc_sub=%s WHERE id=%s',(body.oidc_issuer,body.oidc_sub,uid))
        for p,v in (body.permissions or {}).items():c.execute('INSERT INTO user_permissions VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE allowed=VALUES(allowed)',(uid,p,int(v)))
        if body.enabled is False:c.execute('DELETE FROM sessions WHERE user_id=%s',(uid,))
    return {'ok':True}
@app.get('/api/{kind}/{ident}/shares')
def list_shares(kind:str,ident:str,u:dict=Depends(admin)):
    if kind not in ('scenes','playlists'):raise HTTPException(404)
    singular=kind[:-1]
    with db() as c:
        r=resource_access(c,u,singular,ident,edit=True)
        if r['owner_id']!=u['id'] and u['role']!='admin':raise HTTPException(403)
        c.execute('SELECT recipient_id,can_edit FROM resource_shares WHERE kind=%s AND resource_id=%s',(singular,ident))
        return {'visibility':r['visibility'],'shares':[dict(x) for x in c.fetchall()]}
@app.put('/api/{kind}/{ident}/shares')
def set_shares(kind:str,ident:str,body:ShareInput,u:dict=Depends(require('sharing.manage'))):
    if kind not in ('scenes','playlists'):raise HTTPException(404)
    singular=kind[:-1]
    with db() as c:
        r=resource_access(c,u,singular,ident,edit=True)
        if r['owner_id']!=u['id'] and u['role']!='admin':raise HTTPException(403)
        if body.recipient_id!='*':
            c.execute('SELECT 1 FROM users WHERE id=%s AND enabled=1',(body.recipient_id,))
            if not c.fetchone():raise HTTPException(404,'User not found')
        c.execute('INSERT INTO resource_shares VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE can_edit=VALUES(can_edit)',(singular,ident,body.recipient_id,int(body.can_edit)))
    return {'ok':True}
@app.delete('/api/{kind}/{ident}/shares/{recipient_id}')
def remove_share(kind:str,ident:str,recipient_id:str,u:dict=Depends(require('sharing.manage'))):
    if kind not in ('scenes','playlists'):raise HTTPException(404)
    singular=kind[:-1]
    with db() as c:
        r=resource_access(c,u,singular,ident,edit=True)
        if r['owner_id']!=u['id'] and u['role']!='admin':raise HTTPException(403)
        c.execute('DELETE FROM resource_shares WHERE kind=%s AND resource_id=%s AND recipient_id=%s',(singular,ident,recipient_id))
    return {'ok':True}

# OpenID Connect: authorization-code + PKCE; validated ID token via provider JWKS.
async def oidc_metadata():
    import httpx
    # OIDC issuer identifiers are exact values. In particular, Authentik
    # includes a trailing slash in its issuer URL and discovery metadata.
    issuer=os.getenv('OIDC_ISSUER','')
    if not issuer.startswith('https://') or not os.getenv('OIDC_CLIENT_ID'):raise HTTPException(404,'OIDC not configured with HTTPS issuer')
    async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
        r=await client.get(issuer+'/.well-known/openid-configuration');r.raise_for_status();meta=r.json()
    if meta.get('issuer')!=issuer:raise HTTPException(502,'OIDC issuer mismatch')
    for field in ('authorization_endpoint','token_endpoint','jwks_uri'):
        if not str(meta.get(field,'')).startswith('https://'):raise HTTPException(502,'OIDC endpoint must use HTTPS')
    return meta
@app.get('/api/oidc/start')
async def oidc_start(req:Request):
    from authlib.oauth2.rfc7636 import create_s256_code_challenge
    meta=await oidc_metadata();state=secrets.token_urlsafe(40);nonce=secrets.token_urlsafe(40);verifier=secrets.token_urlsafe(48)
    with db() as c:
        c.execute('DELETE FROM auth_states WHERE expires<%s',(int(time.time()),))
        c.execute('INSERT INTO auth_states VALUES(%s,%s,%s,%s)',(digest(state),nonce,verifier,int(time.time())+600))
    base=os.environ.get('PUBLIC_URL','').rstrip('/')
    if not base.startswith('https://') and os.getenv('OIDC_ALLOW_HTTP')!='1':raise HTTPException(400,'OIDC requires HTTPS PUBLIC_URL')
    params={'client_id':os.environ['OIDC_CLIENT_ID'],'response_type':'code','redirect_uri':base+'/api/oidc/callback','scope':'openid profile email','state':state,'nonce':nonce,'code_challenge':create_s256_code_challenge(verifier),'code_challenge_method':'S256'}
    return RedirectResponse(meta['authorization_endpoint']+'?'+urllib.parse.urlencode(params))
@app.get('/api/oidc/callback')
async def oidc_callback(req:Request,code:str='',state:str=''):
    import httpx
    from authlib.jose import jwt
    if not code or not state:raise HTTPException(400,'OIDC authorization failed')
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        c.execute('SELECT * FROM auth_states WHERE state_hash=%s FOR UPDATE',(digest(state),));r=c.fetchone()
        if not r or r['expires']<time.time():raise HTTPException(400,'OIDC state expired')
        c.execute('DELETE FROM auth_states WHERE state_hash=%s',(digest(state),))
    meta=await oidc_metadata();base=os.environ.get('PUBLIC_URL','').rstrip('/')
    data={'grant_type':'authorization_code','code':code,'redirect_uri':base+'/api/oidc/callback','client_id':os.environ['OIDC_CLIENT_ID'],'code_verifier':r['verifier']}
    if os.getenv('OIDC_CLIENT_SECRET'):data['client_secret']=os.environ['OIDC_CLIENT_SECRET']
    async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
        token_response=await client.post(meta['token_endpoint'],data=data);token_response.raise_for_status();token=token_response.json()
        if not token.get('id_token'):raise HTTPException(502,'OIDC provider omitted ID token')
        jwks_response=await client.get(meta['jwks_uri']);jwks_response.raise_for_status();jwks=jwks_response.json()
    claims=jwt.decode(token['id_token'],jwks,claims_options={'iss':{'essential':True,'value':meta['issuer']},'aud':{'essential':True,'value':os.environ['OIDC_CLIENT_ID']},'nonce':{'essential':True,'value':r['nonce']},'exp':{'essential':True},'iat':{'essential':True},'sub':{'essential':True}})
    claims.validate(leeway=30)
    issuer=str(claims['iss']);sub=str(claims['sub'])
    # Authentik's profile scope provides preferred_username and group names.
    # Keep the subject as the immutable identity key; username is display/login.
    display_name=str(claims.get('preferred_username') or claims.get('email','').split('@')[0] or '').strip()
    if not display_name:display_name='oidc_'+hashlib.sha256((issuer+sub).encode()).hexdigest()[:16]
    admin_groups={g.strip() for g in os.getenv('OIDC_ADMIN_GROUPS','open-wallpaper-admins').split(',') if g.strip()}
    claim_groups=claims.get('groups',[])
    if isinstance(claim_groups,str):claim_groups=[claim_groups]
    is_oidc_admin=bool(admin_groups.intersection(str(g) for g in claim_groups if isinstance(g,(str,int))))
    with db() as c:
        c.execute('SELECT * FROM users WHERE oidc_issuer=%s AND oidc_sub=%s',(issuer,sub));user=c.fetchone()
        if not user:
            if os.getenv('OIDC_AUTO_PROVISION','0')!='1':raise HTTPException(403,'OIDC account not provisioned; ask an administrator')
            # Avoid taking over an existing local account with the same name.
            c.execute('SELECT id FROM users WHERE username=%s',(display_name,));collision=c.fetchone()
            if collision:display_name='oidc_'+hashlib.sha256((issuer+sub).encode()).hexdigest()[:16]
            uid=uuid4().hex;c.execute('INSERT INTO users(id,username,role,oidc_issuer,oidc_sub) VALUES(%s,%s,%s,%s,%s)',(uid,display_name,'admin' if is_oidc_admin else 'user',issuer,sub))
        else:
            if not user['enabled']:raise HTTPException(403,'Account disabled')
            uid=user['id']
            updates=[];values=[]
            if user['username'].startswith('oidc_') and user['username']!=display_name:
                c.execute('SELECT id FROM users WHERE username=%s AND id<>%s',(display_name,uid))
                if not c.fetchone():updates.append('username=%s');values.append(display_name)
            oidc_role='admin' if is_oidc_admin else 'user'
            if user['role']!=oidc_role:updates.append('role=%s');values.append(oidc_role)
            if updates:c.execute('UPDATE users SET '+','.join(updates)+' WHERE id=%s',(*values,uid))
    response=login_response(uid)
    response.status_code=303;response.headers['location']='/';return response

class FolderGrantInput(BaseModel):
    user_id:str
    view:bool=False
    use:bool=False
    upload:bool=False
    edit:bool=False
    delete:bool=False
    manage:bool=False

@app.get('/api/folders/{ident}/access')
def folder_access(ident:str,u:dict=Depends(require('users.manage'))):
    with db() as c:
        folder_path(c,ident)
        c.execute('SELECT * FROM folder_grants WHERE folder_id=%s',(ident,));return [dict(x) for x in c.fetchall()]

@app.put('/api/folders/{ident}/access')
def set_folder_access(ident:str,body:FolderGrantInput,u:dict=Depends(require('users.manage'))):
    with db() as c:
        folder_path(c,ident)
        c.execute('SELECT id FROM users WHERE id=%s',(body.user_id,));recipient=c.fetchone()
        if not recipient:raise HTTPException(404,'User not found')
        rights=[int(getattr(body,r)) for r in FOLDER_RIGHTS]
        c.execute('INSERT INTO folder_grants VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE can_view=VALUES(can_view),can_use=VALUES(can_use),can_upload=VALUES(can_upload),can_edit=VALUES(can_edit),can_delete=VALUES(can_delete),can_manage=VALUES(can_manage)',(ident,body.user_id,*rights))
    return {'ok':True}

@app.delete('/api/folders/{ident}/access/{uid}')
def delete_folder_access(ident:str,uid:str,u:dict=Depends(require('users.manage'))):
    with db() as c:
        folder_path(c,ident)
        c.execute('DELETE FROM folder_grants WHERE folder_id=%s AND user_id=%s',(ident,uid))
    return {'ok':True}

@app.get('/api/media')
def media_list(u:dict=Depends(require('media.view'))):
    sync_media()
    with db() as c:
        c.execute('SELECT * FROM media ORDER BY name')
        return [clean_media(r) for r in c.fetchall() if folder_rights(c,u,r['folder_id'])['view']]
@app.post('/api/media')
async def upload(file:UploadFile=File(...),folder_id:str|None=Form(None),u:dict=Depends(require('media.upload'))):
    name=Path(file.filename or '').name;suffix=Path(name).suffix.lower()
    if suffix not in TYPES:raise HTTPException(400,'Unsupported file type')
    mime,kind=TYPES[suffix];ident=uuid4().hex;size=0
    with db() as c:
        folder_check(c,u,folder_id,'upload')
        directory=MEDIA/folder_path(c,folder_id)
    directory.mkdir(parents=True,exist_ok=True);dest=unique_file(directory,name)
    try:
        with dest.open('xb') as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_BYTES:raise HTTPException(413,'Maximum upload size is 100 MB')
                out.write(chunk)
        if not size:raise HTTPException(400,'Empty file')
        with db() as c:c.execute('INSERT INTO media(id,name,filename,kind,mime,folder_id) VALUES(%s,%s,%s,%s,%s,%s)',(ident,dest.name,str(dest.relative_to(MEDIA)),kind,mime,folder_id))
    except Exception:dest.unlink(missing_ok=True);raise
    return {'id':ident,'url':'/api/media/'+ident+'/file'}
@app.get('/api/media/{ident}/file')
def media_file(ident:str,req:Request):
    # Device content is protected by its token, and admin by its session.
    try:
        u=admin(req)
        with db() as c:media_check(c,u,ident,'view')
    except HTTPException as exc:
        if exc.status_code!=401:raise
        d=device(req)
        with db() as c:
            payload=device_payload(c,d)
            if ident not in media_ids_for_payload(payload):raise HTTPException(404,'Media not assigned to device')
            media_check(c,device_owner(c,d),ident,'use')
    with db() as c:c.execute('SELECT * FROM media WHERE id=%s',(ident,));row=c.fetchone()
    if not row:raise HTTPException(404,'Not found')
    return FileResponse(MEDIA/row['filename'],media_type=row['mime'],headers={'Cache-Control':'private, max-age=3600'})
@app.get('/api/folders')
def folders(u:dict=Depends(require('media.view'))):
    sync_media()
    with db() as c:
        permitted,nav=visible_folder_ids(c,u)
        c.execute('SELECT * FROM folders ORDER BY name')
        return [{**dict(x),'navigation_only':x['id'] not in permitted} for x in c.fetchall() if x['id'] in nav]
@app.post('/api/folders')
def add_folder(body:FolderInput,u:dict=Depends(require('folders.manage'))):
    ident=uuid4().hex;name=folder_name(body.name)
    with db() as c:
        if body.parent_id:
            c.execute('SELECT 1 FROM folders WHERE id=%s',(body.parent_id,))
            if not c.fetchone():raise HTTPException(404,'Parent folder not found')
        folder_check(c,u,body.parent_id,'edit')
        target=MEDIA/folder_path(c,body.parent_id)/name
        if target.exists():raise HTTPException(409,'Folder already exists')
        target.mkdir(parents=True)
        c.execute('INSERT INTO folders VALUES(%s,%s,%s)',(ident,name,body.parent_id))
    return {'id':ident}
@app.put('/api/folders/{ident}')
def rename_folder(ident:str,body:FolderInput,u:dict=Depends(require('folders.manage'))):
    name=folder_name(body.name)
    with db() as c:
        folder_check(c,u,ident,'edit');folder_check(c,u,body.parent_id,'edit')
        old=folder_path(c,ident);parent=folder_path(c,body.parent_id);new=parent/name
        if parent==old or old in parent.parents:raise HTTPException(400,'Folder cycle')
        if new!=old and (MEDIA/new).exists():raise HTTPException(409,'Destination folder exists')
        (MEDIA/old).mkdir(parents=True,exist_ok=True)
        (MEDIA/new).parent.mkdir(parents=True,exist_ok=True)
        if new!=old:(MEDIA/old).rename(MEDIA/new)
        c.execute('UPDATE folders SET name=%s,parent_id=%s WHERE id=%s',(name,body.parent_id,ident))
        prefix=str(old)+'/'
        c.execute('SELECT id,filename FROM media')
        for row in c.fetchall():
            if row['filename'].startswith(prefix):
                c.execute('UPDATE media SET filename=%s WHERE id=%s',(str(new/row['filename'][len(prefix):]),row['id']))
    return {'ok':True}

@app.delete('/api/folders/{ident}')
def remove_folder(ident:str,u:dict=Depends(require('folders.manage'))):
    with db() as c:
        folder_check(c,u,ident,'delete')
        c.execute('SELECT 1 FROM folders WHERE parent_id=%s',(ident,))
        if c.fetchone():raise HTTPException(409,'Move or delete subfolders first')
        rel=folder_path(c,ident)
        c.execute('SELECT id,filename FROM media WHERE folder_id=%s',(ident,))
        for row in c.fetchall():
            src=MEDIA/row['filename'];dest=unique_file(MEDIA,src.name)
            if src.exists():src.rename(dest)
            c.execute('UPDATE media SET filename=%s,name=%s,folder_id=NULL WHERE id=%s',(dest.name,dest.name,row['id']))
        folder=MEDIA/rel
        if folder.exists():
            try:folder.rmdir()
            except OSError:raise HTTPException(409,'Folder contains unindexed files')
        c.execute('DELETE FROM folders WHERE id=%s',(ident,))
    return {'ok':True}

@app.post('/api/media/move')
def move_media(body:MoveMedia,u:dict=Depends(require('folders.manage'))):
    with db() as c:
        folder_check(c,u,body.folder_id,'edit')
        directory=MEDIA/folder_path(c,body.folder_id);directory.mkdir(parents=True,exist_ok=True)
        for ident in set(body.ids):
            c.execute('SELECT filename FROM media WHERE id=%s',(ident,));row=c.fetchone()
            if not row:continue
            media_check(c,u,ident,'edit')
            src=MEDIA/row['filename']
            if src.parent==directory:
                c.execute('UPDATE media SET folder_id=%s WHERE id=%s',(body.folder_id,ident));continue
            dest=unique_file(directory,src.name)
            if not src.exists():raise HTTPException(404,'Media file missing')
            src.rename(dest)
            c.execute('UPDATE media SET filename=%s,name=%s,folder_id=%s WHERE id=%s',(str(dest.relative_to(MEDIA)),dest.name,body.folder_id,ident))
    return {'ok':True}

@app.post('/api/media/bulk-delete')
def bulk_delete(body:BulkDelete,u:dict=Depends(require('media.delete'))):
    removed=[]
    with db() as c:
        for ident in set(body.ids):
            c.execute('SELECT filename FROM media WHERE id=%s',(ident,));row=c.fetchone()
            if row:
                media_check(c,u,ident,'delete')
                c.execute('DELETE FROM media WHERE id=%s',(ident,))
                removed.append(row['filename'])
    with db() as c:
        for name in removed:
            c.execute('SELECT 1 FROM media WHERE filename=%s',(name,))
            if not c.fetchone():
                (MEDIA/name).unlink(missing_ok=True)
    return {'deleted':len(removed)}
@app.delete('/api/media/{ident}')
def delete_media(ident:str,u:dict=Depends(require('media.delete'))):
    with db() as c:
        c.execute('SELECT filename FROM media WHERE id=%s',(ident,));row=c.fetchone()
        if not row:raise HTTPException(404)
        media_check(c,u,ident,'delete')
        c.execute('DELETE FROM media WHERE id=%s',(ident,))
    with db() as c:
        c.execute('SELECT 1 FROM media WHERE filename=%s',(row['filename'],))
        if not c.fetchone():
            (MEDIA/row['filename']).unlink(missing_ok=True)
    return {'ok':True}

def validate_scene(scene:Scene,user):
    for layer in scene.layers:
        if layer.get('type') not in ('image','video','web','clock','playlist','folder'):raise HTTPException(400,'Invalid layer type')
        if layer['type'] in ('image','video'):
            ident=layer.get('media_id')
            with db() as c:
                media_check(c,user,ident,'use')
                c.execute('SELECT kind FROM media WHERE id=%s',(ident,));r=c.fetchone()
            if not r or r['kind']!=layer['type']:raise HTTPException(400,'Invalid media reference')
        if layer['type']=='folder':
            with db() as c:folder_check(c,user,layer.get('folder_id'),'use')
        if layer['type']=='playlist':
            with db() as c:c.execute('SELECT 1 FROM playlists WHERE id=%s',(layer.get('playlist_id'),));r=c.fetchone()
            if not r:raise HTTPException(400,'Invalid playlist reference')
        if layer['type']=='web':
            # Untrusted remote websites are not embedded by the server.
            raise HTTPException(400,'Web layers are reserved for a sandboxed renderer in a future release')
@app.get('/api/scenes')
def scenes(u:dict=Depends(admin)):
    with db() as c:
        result=[]
        for r in visible(c,u,'scene'):
            manifest=json.loads(r['manifest'])
            manifest['layers']=[layer for layer in manifest.get('layers',[]) if layer_allowed(c,u,layer)]
            result.append({'id':r['id'],'name':r['name'],'manifest':manifest})
        return result
@app.post('/api/scenes')
def create_scene(scene:Scene,u:dict=Depends(admin)):
    ensure_create(u,'scene')
    validate_scene(scene,u);ident=uuid4().hex
    with db() as c:
        for layer in scene.layers:
            if layer.get('type')=='playlist':resource_access(c,u,'playlist',layer.get('playlist_id'))
    manifest={'schemaVersion':'1.0','id':ident,'name':scene.name,'canvas':scene.canvas,'layers':scene.layers}
    with db() as c:c.execute('INSERT INTO scenes(id,name,manifest,owner_id) VALUES(%s,%s,%s,%s)',(ident,scene.name,json.dumps(manifest),u['id']))
    return manifest
@app.put('/api/scenes/{ident}')
def update_scene(ident:str,scene:Scene,u:dict=Depends(admin)):
    validate_scene(scene,u)
    with db() as c:
        for layer in scene.layers:
            if layer.get('type')=='playlist':resource_access(c,u,'playlist',layer.get('playlist_id'))
    manifest={'schemaVersion':'1.0','id':ident,'name':scene.name,'canvas':scene.canvas,'layers':scene.layers}
    with db() as c:
        resource_access(c,u,'scene',ident,edit=True)
        c.execute('UPDATE scenes SET name=%s,manifest=%s WHERE id=%s',(scene.name,json.dumps(manifest),ident))
        if not c.rowcount:raise HTTPException(404,'Scene not found')
    return manifest
@app.delete('/api/scenes/{ident}')
def delete_scene(ident:str,u:dict=Depends(admin)):
    with db() as c:
        resource_access(c,u,'scene',ident,edit=True)
        c.execute('DELETE FROM resource_shares WHERE kind=%s AND resource_id=%s',('scene',ident))
        c.execute('UPDATE devices SET scene_id=NULL WHERE scene_id=%s',(ident,))
        c.execute('DELETE FROM scenes WHERE id=%s',(ident,))
    return {'ok':True}
def descendant_ids(c,folder_ids):
    c.execute('SELECT id,parent_id FROM folders');rows=[dict(r) for r in c.fetchall()]
    known={r['id'] for r in rows}
    if any(fid not in known for fid in folder_ids):raise HTTPException(400,'Unknown folder selection')
    selected=set(folder_ids)
    while True:
        more={r['id'] for r in rows if r['parent_id'] in selected}
        if more <= selected:break
        selected |= more
    return selected

def resolve_items(c,items):
    if isinstance(items,list):items={'media_ids':items,'folder_ids':[]}
    ids=list(dict.fromkeys(items.get('media_ids',[])))
    folder_ids=items.get('folder_ids',[])
    if folder_ids:
        children=descendant_ids(c,folder_ids)
        c.execute('SELECT id,folder_id FROM media ORDER BY filename')
        for r in c.fetchall():
            if r['folder_id'] in children and r['id'] not in ids:ids.append(r['id'])
    return ids

def playlist_response(c,r,user=None):
    items=json.loads(r['items'])
    if isinstance(items,list):items={'media_ids':items,'folder_ids':[]}
    ids=resolve_items(c,items)
    if user:
        ids=filter_media_ids(c,user,ids)
        selected=filter_media_ids(c,user,items.get('media_ids',[]))
        selected_folders=[fid for fid in items.get('folder_ids',[]) if folder_rights(c,user,fid)['use']]
    else:selected=items.get('media_ids',[]);selected_folders=items.get('folder_ids',[])
    return {'id':r['id'],'name':r['name'],'media_ids':ids,'selected_media_ids':selected,'folder_ids':selected_folders,'interval_seconds':r['interval_seconds'],'shuffle':bool(r['shuffle'])}

@app.get('/api/playlists')
def list_playlists(u:dict=Depends(admin)):
    with db() as c:return [playlist_response(c,r,u) for r in visible(c,u,'playlist')]
def validate_playlist(p:Playlist,user):
    with db() as c:
        c.execute('SELECT id FROM media WHERE id IN ('+','.join('%s' for _ in p.media_ids)+')',p.media_ids)
        found={r['id'] for r in c.fetchall()}
    if len(found)!=len(set(p.media_ids)):raise HTTPException(400,'Playlist references missing media')
    with db() as c:
        for fid in p.folder_ids:folder_check(c,user,fid,'use')
        for ident in p.media_ids:media_check(c,user,ident,'use')
    if not p.media_ids and not p.folder_ids:raise HTTPException(400,'Choose files or folders')
@app.post('/api/playlists')
def create_playlist(p:Playlist,u:dict=Depends(admin)):
    ensure_create(u,'playlist')
    validate_playlist(p,u);ident=uuid4().hex
    with db() as c:c.execute('INSERT INTO playlists(id,name,items,interval_seconds,shuffle,owner_id) VALUES(%s,%s,%s,%s,%s,%s)',(ident,p.name,json.dumps({"media_ids":p.media_ids,"folder_ids":p.folder_ids}),p.interval_seconds,int(p.shuffle),u['id']))
    return {'id':ident}
@app.put('/api/playlists/{ident}')
def update_playlist(ident:str,p:Playlist,u:dict=Depends(admin)):
    validate_playlist(p,u)
    with db() as c:
        resource_access(c,u,'playlist',ident,edit=True)
        c.execute('UPDATE playlists SET name=%s,items=%s,interval_seconds=%s,shuffle=%s WHERE id=%s',(p.name,json.dumps({"media_ids":p.media_ids,"folder_ids":p.folder_ids}),p.interval_seconds,int(p.shuffle),ident))
        if not c.rowcount:raise HTTPException(404)
    return {'ok':True}
@app.delete('/api/playlists/{ident}')
def delete_playlist(ident:str,u:dict=Depends(admin)):
    with db() as c:
        resource_access(c,u,'playlist',ident,edit=True)
        c.execute('DELETE FROM resource_shares WHERE kind=%s AND resource_id=%s',('playlist',ident))
        c.execute('UPDATE devices SET playlist_id=NULL WHERE playlist_id=%s',(ident,))
        c.execute('DELETE FROM playlists WHERE id=%s',(ident,))
    return {'ok':True}
@app.get('/api/devices')
def devices(u:dict=Depends(admin)):
    with db() as c:return [{k:r[k] for k in ('id','name','scene_id','playlist_id','created')} for r in visible(c,u,'device')]
@app.post('/api/pairing/qr')
def create_qr_pairing(req:Request,u:dict=Depends(require('devices.pair'))):
    import qrcode
    from urllib.parse import quote
    token=secrets.token_urlsafe(32)
    expires=int(time.time())+300
    with db() as c:
        c.execute('DELETE FROM qr_invites WHERE expires<%s',(int(time.time()),))
        c.execute('INSERT INTO qr_invites(token_hash,expires,owner_id) VALUES(%s,%s,%s)',(digest(token),expires,u['id']))
    base=os.environ.get('PUBLIC_URL','').strip().rstrip('/') or str(req.base_url).rstrip('/')
    if not (base.startswith('http://') or base.startswith('https://')):raise HTTPException(500,'Invalid PUBLIC_URL')
    payload='openwallpaper://pair?server='+quote(base,safe='')+'&token='+token
    img=qrcode.make(payload)
    output=io.BytesIO();img.save(output,format='PNG')
    return {'image':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode(),'expires_in':300,'server':base}

class QRClaim(BaseModel):
    token:str
    name:str=Field(default='Android device',max_length=80)

@app.post('/api/pairing/qr/claim')
def claim_qr_pairing(body:QRClaim):
    now=int(time.time())
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        c.execute('SELECT expires,owner_id FROM qr_invites WHERE token_hash=%s FOR UPDATE',(digest(body.token),));row=c.fetchone()
        if not row or row['expires']<now:raise HTTPException(404,'QR code expired or already used')
        c.execute('DELETE FROM qr_invites WHERE token_hash=%s',(digest(body.token),))
        device_token=secrets.token_urlsafe(36);ident=uuid4().hex
        c.execute('INSERT INTO devices(id,name,token_hash,scene_id,created,playlist_id,owner_id) VALUES(%s,%s,%s,%s,%s,%s,%s)',(ident,body.name,digest(device_token),None,now,None,row['owner_id']))
    return {'token':device_token,'device_id':ident}

@app.post('/api/pairing')
def pairing(body:dict):
    name=str(body.get('name','Android device'))[:80]
    code=secrets.token_urlsafe(12)
    with db() as c:
        c.execute('DELETE FROM pairing WHERE expires<%s',(int(time.time()),))
        c.execute('INSERT INTO pairing VALUES(%s,%s,%s)',(digest(code),name,int(time.time())+600))
    return {'code':code,'expires_in':600}
@app.post('/api/pairing/approve')
def approve(body:Pair,u:dict=Depends(require('devices.pair'))):
    with db() as c:
        c.execute('SELECT * FROM pairing WHERE code_hash=%s',(digest(body.code),));row=c.fetchone()
        if not row or row['expires']<time.time():raise HTTPException(404,'Code expired or invalid')
        token=secrets.token_urlsafe(36);ident=uuid4().hex
        c.execute('INSERT INTO devices(id,name,token_hash,scene_id,created,owner_id) VALUES(%s,%s,%s,%s,%s,%s)',(ident,row['device_name'],digest(token),None,int(time.time()),u['id']))
        c.execute('DELETE FROM pairing WHERE code_hash=%s',(digest(body.code),))
    # Device receives token through one-time polling, implemented in /api/pairing/claim.
    with db() as c:c.execute('INSERT INTO claims VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE token=VALUES(token),expires=VALUES(expires)',(digest(body.code),token,int(time.time())+600))
    return {'ok':True,'device_id':ident}
@app.post('/api/pairing/claim')
def claim(body:Pair):
    with db() as c:
        c.execute('SELECT * FROM claims WHERE code_hash=%s',(digest(body.code),));r=c.fetchone()
        if not r or r['expires']<time.time():return {'pending':True}
        c.execute('DELETE FROM claims WHERE code_hash=%s',(digest(body.code),))
    return {'pending':False,'token':r['token']}
@app.put('/api/devices/{ident}/scene')
def assign(ident:str,body:DeviceAssign,u:dict=Depends(admin)):
    with db() as c:
        resource_access(c,u,'device',ident,edit=True)
        ensure_references(c,u,body.scene_id,body.playlist_id)
        if body.scene_id:
            c.execute('SELECT 1 FROM scenes WHERE id=%s',(body.scene_id,))
            if not c.fetchone():raise HTTPException(404,'Scene not found')
        if body.playlist_id:
            c.execute('SELECT 1 FROM playlists WHERE id=%s',(body.playlist_id,))
            if not c.fetchone():raise HTTPException(404,'Playlist not found')
        if body.scene_id and body.playlist_id:raise HTTPException(400,'Choose scene or playlist')
        c.execute('UPDATE devices SET scene_id=%s,playlist_id=%s WHERE id=%s',(body.scene_id,body.playlist_id,ident))
        if not c.rowcount:raise HTTPException(404,'Device not found')
    return {'ok':True}
@app.delete('/api/devices/{ident}')
def revoke(ident:str,u:dict=Depends(admin)):
    with db() as c:
        resource_access(c,u,'device',ident,edit=True)
        c.execute('DELETE FROM devices WHERE id=%s',(ident,))
    return {'ok':True}
def expanded_playlist(c,ident):
    c.execute('SELECT * FROM playlists WHERE id=%s',(ident,));row=c.fetchone()
    return playlist_response(c,row) if row else None

def device_owner(c,d):
    c.execute('SELECT * FROM users WHERE id=%s AND enabled=1',(d['owner_id'],));row=c.fetchone()
    if not row:raise HTTPException(403,'Device owner disabled or missing')
    return dict(row)

def layer_allowed(c,user,layer):
    kind=layer.get('type')
    if kind in ('image','video'):
        try:media_check(c,user,layer.get('media_id'),'use');return True
        except HTTPException:return False
    if kind=='folder':return folder_rights(c,user,layer.get('folder_id'))['use']
    if kind=='playlist':
        try:resource_access(c,user,'playlist',layer.get('playlist_id'));return True
        except HTTPException:return False
    return True

def device_payload(c,d):
    if d['scene_id']:c.execute('SELECT manifest FROM scenes WHERE id=%s',(d['scene_id'],));scene_row=c.fetchone()
    else:scene_row=None
    owner=device_owner(c,d)
    scene=json.loads(scene_row['manifest']) if scene_row else None
    if scene:scene['layers']=[x for x in scene.get('layers',[]) if layer_allowed(c,owner,x)]
    direct=expanded_playlist(c,d['playlist_id']) if d['playlist_id'] else None
    if direct:direct['media_ids']=filter_media_ids(c,owner,direct['media_ids'])
    linked={}
    if scene:
        for layer in scene.get('layers',[]):
            if layer.get('type')=='playlist':
                pid=layer.get('playlist_id')
                try:resource_access(c,owner,'playlist',pid)
                except HTTPException:continue
                linked[pid]=expanded_playlist(c,pid)
                if linked[pid]:linked[pid]['media_ids']=filter_media_ids(c,owner,linked[pid]['media_ids'])
            elif layer.get('type')=='folder':
                fid=layer.get('folder_id');pid='folder:'+str(fid)
                linked[pid]={'id':pid,'name':'Folder','media_ids':filter_media_ids(c,owner,resolve_items(c,{'folder_ids':[fid]})),'interval_seconds':max(3,int(layer.get('interval_seconds',30))),'shuffle':False}
                layer['type']='playlist';layer['playlist_id']=pid
    ids=media_ids_for_payload({'scene':scene,'playlist':direct,'playlists':linked})
    c.execute('SELECT id,kind FROM media');kinds={r['id']:r['kind'] for r in c.fetchall() if r['id'] in ids}
    return {'device_id':d['id'],'scene':scene,'playlist':direct,'playlists':linked,'media_types':kinds}

def media_ids_for_payload(payload):
    ids=set()
    if payload['scene']:
        for layer in payload['scene'].get('layers',[]):
            if layer.get('media_id'):ids.add(layer['media_id'])
    for p in [payload['playlist'],*payload['playlists'].values()]:
        if p:ids.update(p['media_ids'])
    return ids

@app.get('/api/device/config')
def config(req:Request,d:dict=Depends(device)):
    sync_media()
    with db() as c:return device_payload(c,d)
@app.get('/api/device/media/{ident}')
def device_media(ident:str,req:Request,d:dict=Depends(device)):
    with db() as c:
        c.execute('SELECT * FROM media WHERE id=%s',(ident,));row=c.fetchone()
        allowed=media_ids_for_payload(device_payload(c,d))
        if not row or ident not in allowed:raise HTTPException(404)
        media_check(c,device_owner(c,d),ident,'use')
    return FileResponse(MEDIA/row['filename'],media_type=row['mime'])
app.mount('/',StaticFiles(directory=str(WEB),html=True),name='web')
