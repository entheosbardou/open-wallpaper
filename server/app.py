import hashlib, hmac, json, mimetypes, os, secrets, sqlite3, time, base64, io
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA=Path(os.environ.get('DATA_DIR','./data')); DATA.mkdir(parents=True,exist_ok=True)
MEDIA=DATA/'media'; MEDIA.mkdir(exist_ok=True)
WEB=Path(__file__).resolve().parent.parent/'web'
MAX_BYTES=100*1024*1024
TYPES={'.jpg':('image/jpeg','image'),'.jpeg':('image/jpeg','image'),'.png':('image/png','image'),'.webp':('image/webp','image'),'.gif':('image/gif','image'),'.mp4':('video/mp4','video'),'.webm':('video/webm','video')}
app=FastAPI(title='Open Wallpaper Server',version='0.4.0',docs_url=None,redoc_url=None)

@contextmanager
def db():
    con=sqlite3.connect(DATA/'app.sqlite3',timeout=10)
    con.row_factory=sqlite3.Row
    try: yield con; con.commit()
    finally: con.close()

def init():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,name TEXT NOT NULL,filename TEXT NOT NULL,kind TEXT NOT NULL,mime TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scenes(id TEXT PRIMARY KEY,name TEXT NOT NULL,manifest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL,scene_id TEXT,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS pairing(code_hash TEXT PRIMARY KEY,device_name TEXT NOT NULL,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS playlists(id TEXT PRIMARY KEY,name TEXT NOT NULL,items TEXT NOT NULL,interval_seconds INTEGER NOT NULL,shuffle INTEGER NOT NULL); ''')
        c.execute('CREATE TABLE IF NOT EXISTS qr_invites(token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY,name TEXT NOT NULL,parent_id TEXT REFERENCES folders(id) ON DELETE RESTRICT)')
        for table,column in [('media','folder_id TEXT'),('devices','playlist_id TEXT')]:
            if column.split()[0] not in [r[1] for r in c.execute(f'PRAGMA table_info({table})')]: c.execute(f'ALTER TABLE {table} ADD COLUMN {column}')
init()

def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def hash_password(p,s): return hashlib.scrypt(p.encode(),salt=bytes.fromhex(s),n=2**14,r=8,p=1).hex()
def bearer(req):
    h=req.headers.get('authorization','')
    return h[7:] if h.startswith('Bearer ') else ''
def admin(req:Request):
    token=req.cookies.get('session','') or bearer(req)
    with db() as c: row=c.execute('SELECT expires FROM sessions WHERE token_hash=?',(digest(token),)).fetchone() if token else None
    if not row or row['expires']<time.time(): raise HTTPException(401,'Sign in required')
def device(req:Request):
    token=bearer(req)
    with db() as c: row=c.execute('SELECT * FROM devices WHERE token_hash=?',(digest(token),)).fetchone() if token else None
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
    media_ids:list[str]=Field(min_length=1,max_length=500)
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
def health(): return {'status':'ok','version':'0.4.0'}
@app.get('/api/status')
def status():
    with db() as c: return {'setup_required':c.execute('SELECT 1 FROM admin').fetchone() is None}
@app.post('/api/setup')
def setup(body:Credentials):
    with db() as c:
        if c.execute('SELECT 1 FROM admin').fetchone(): raise HTTPException(409,'Already configured')
        salt=secrets.token_hex(16)
        c.execute('INSERT INTO admin VALUES(1,?,?,?)',(body.username,salt,hash_password(body.password,salt)))
    return {'ok':True}
@app.post('/api/login')
def login(body:Credentials):
    with db() as c:
        row=c.execute('SELECT * FROM admin WHERE username=?',(body.username,)).fetchone()
        if not row or not hmac.compare_digest(row['password_hash'],hash_password(body.password,row['salt'])): raise HTTPException(401,'Invalid credentials')
        token=secrets.token_urlsafe(36)
        c.execute('INSERT INTO sessions VALUES(?,?)',(digest(token),int(time.time())+86400*7))
    resp=JSONResponse({'ok':True});resp.set_cookie('session',token,httponly=True,samesite='strict',secure=False,max_age=86400*7,path='/');return resp
@app.post('/api/logout')
def logout(req:Request, _:None=Depends(admin)):
    with db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(digest(req.cookies.get('session','')),))
    resp=JSONResponse({'ok':True});resp.delete_cookie('session');return resp

@app.get('/api/media')
def media_list(_:None=Depends(admin)):
    with db() as c:return [clean_media(r) for r in c.execute('SELECT * FROM media ORDER BY name')]
@app.post('/api/media')
async def upload(file:UploadFile=File(...),_:None=Depends(admin)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in TYPES:raise HTTPException(400,'Unsupported file type')
    mime,kind=TYPES[suffix];ident=uuid4().hex;dest=MEDIA/(ident+suffix);size=0
    try:
        with dest.open('wb') as f:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_BYTES:raise HTTPException(413,'Maximum upload size is 100 MB')
                f.write(chunk)
        if size==0:raise HTTPException(400,'Empty file')
        with db() as c:c.execute('INSERT INTO media(id,name,filename,kind,mime) VALUES(?,?,?,?,?)',(ident,Path(file.filename).name[:200],dest.name,kind,mime))
    except Exception:
        dest.unlink(missing_ok=True);raise
    return {'id':ident,'url':'/api/media/'+ident+'/file'}
@app.get('/api/media/{ident}/file')
def media_file(ident:str,req:Request):
    # Device content is protected by its token, and admin by its session.
    try:admin(req)
    except HTTPException:device(req)
    with db() as c:row=c.execute('SELECT * FROM media WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'Not found')
    return FileResponse(MEDIA/row['filename'],media_type=row['mime'],headers={'Cache-Control':'private, max-age=3600'})
@app.get('/api/folders')
def folders(_:None=Depends(admin)):
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM folders ORDER BY name')]
@app.post('/api/folders')
def add_folder(body:FolderInput,_:None=Depends(admin)):
    ident=uuid4().hex
    with db() as c:
        if body.parent_id and not c.execute('SELECT 1 FROM folders WHERE id=?',(body.parent_id,)).fetchone():raise HTTPException(404,'Parent folder not found')
        c.execute('INSERT INTO folders VALUES(?,?,?)',(ident,body.name,body.parent_id))
    return {'id':ident}
@app.put('/api/folders/{ident}')
def rename_folder(ident:str,body:FolderInput,_:None=Depends(admin)):
    with db() as c:
        if body.parent_id==ident:raise HTTPException(400,'Cannot parent folder to itself')
        parent=body.parent_id
        while parent:
            if parent==ident:raise HTTPException(400,'Folder cycle')
            row=c.execute('SELECT parent_id FROM folders WHERE id=?',(parent,)).fetchone()
            if not row:raise HTTPException(404,'Parent folder not found')
            parent=row['parent_id']
        cur=c.execute('UPDATE folders SET name=?,parent_id=? WHERE id=?',(body.name,body.parent_id,ident))
        if not cur.rowcount:raise HTTPException(404)
    return {'ok':True}
@app.delete('/api/folders/{ident}')
def remove_folder(ident:str,_:None=Depends(admin)):
    with db() as c:
        if c.execute('SELECT 1 FROM folders WHERE parent_id=?',(ident,)).fetchone():raise HTTPException(409,'Move or delete subfolders first')
        c.execute('UPDATE media SET folder_id=NULL WHERE folder_id=?',(ident,))
        cur=c.execute('DELETE FROM folders WHERE id=?',(ident,))
        if not cur.rowcount:raise HTTPException(404)
    return {'ok':True}
@app.post('/api/media/move')
def move_media(body:MoveMedia,_:None=Depends(admin)):
    with db() as c:
        if body.folder_id and not c.execute('SELECT 1 FROM folders WHERE id=?',(body.folder_id,)).fetchone():raise HTTPException(404,'Folder not found')
        for ident in set(body.ids):c.execute('UPDATE media SET folder_id=? WHERE id=?',(body.folder_id,ident))
    return {'ok':True}

@app.post('/api/media/bulk-delete')
def bulk_delete(body:BulkDelete,_:None=Depends(admin)):
    removed=[]
    with db() as c:
        for ident in set(body.ids):
            row=c.execute('SELECT filename FROM media WHERE id=?',(ident,)).fetchone()
            if row:
                c.execute('DELETE FROM media WHERE id=?',(ident,))
                removed.append(row['filename'])
    for name in removed:(MEDIA/name).unlink(missing_ok=True)
    return {'deleted':len(removed)}
@app.delete('/api/media/{ident}')
def delete_media(ident:str,_:None=Depends(admin)):
    with db() as c:
        row=c.execute('SELECT filename FROM media WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404)
        c.execute('DELETE FROM media WHERE id=?',(ident,))
    (MEDIA/row['filename']).unlink(missing_ok=True)
    return {'ok':True}

def validate_scene(scene:Scene):
    for layer in scene.layers:
        if layer.get('type') not in ('image','video','web','clock','playlist'):raise HTTPException(400,'Invalid layer type')
        if layer['type'] in ('image','video'):
            ident=layer.get('media_id')
            with db() as c:r=c.execute('SELECT kind FROM media WHERE id=?',(ident,)).fetchone()
            if not r or r['kind']!=layer['type']:raise HTTPException(400,'Invalid media reference')
        if layer['type']=='playlist':
            with db() as c:r=c.execute('SELECT 1 FROM playlists WHERE id=?',(layer.get('playlist_id'),)).fetchone()
            if not r:raise HTTPException(400,'Invalid playlist reference')
        if layer['type']=='web':
            # Untrusted remote websites are not embedded by the server.
            raise HTTPException(400,'Web layers are reserved for a sandboxed renderer in a future release')
@app.get('/api/scenes')
def scenes(_:None=Depends(admin)):
    with db() as c:return [{'id':r['id'],'name':r['name'],'manifest':json.loads(r['manifest'])} for r in c.execute('SELECT * FROM scenes ORDER BY name')]
@app.post('/api/scenes')
def create_scene(scene:Scene,_:None=Depends(admin)):
    validate_scene(scene);ident=uuid4().hex
    manifest={'schemaVersion':'1.0','id':ident,'name':scene.name,'canvas':scene.canvas,'layers':scene.layers}
    with db() as c:c.execute('INSERT INTO scenes VALUES(?,?,?)',(ident,scene.name,json.dumps(manifest)))
    return manifest
@app.put('/api/scenes/{ident}')
def update_scene(ident:str,scene:Scene,_:None=Depends(admin)):
    validate_scene(scene)
    manifest={'schemaVersion':'1.0','id':ident,'name':scene.name,'canvas':scene.canvas,'layers':scene.layers}
    with db() as c:
        cur=c.execute('UPDATE scenes SET name=?,manifest=? WHERE id=?',(scene.name,json.dumps(manifest),ident))
        if not cur.rowcount:raise HTTPException(404,'Scene not found')
    return manifest
@app.delete('/api/scenes/{ident}')
def delete_scene(ident:str,_:None=Depends(admin)):
    with db() as c:
        c.execute('UPDATE devices SET scene_id=NULL WHERE scene_id=?',(ident,))
        c.execute('DELETE FROM scenes WHERE id=?',(ident,))
    return {'ok':True}
@app.get('/api/playlists')
def list_playlists(_:None=Depends(admin)):
    with db() as c:return [{'id':r['id'],'name':r['name'],'media_ids':json.loads(r['items']),'interval_seconds':r['interval_seconds'],'shuffle':bool(r['shuffle'])} for r in c.execute('SELECT * FROM playlists ORDER BY name')]
def validate_playlist(p:Playlist):
    with db() as c:
        found={r['id'] for r in c.execute('SELECT id FROM media WHERE id IN ('+','.join('?' for _ in p.media_ids)+')',p.media_ids)}
    if len(found)!=len(set(p.media_ids)):raise HTTPException(400,'Playlist references missing media')
@app.post('/api/playlists')
def create_playlist(p:Playlist,_:None=Depends(admin)):
    validate_playlist(p);ident=uuid4().hex
    with db() as c:c.execute('INSERT INTO playlists VALUES(?,?,?,?,?)',(ident,p.name,json.dumps(p.media_ids),p.interval_seconds,int(p.shuffle)))
    return {'id':ident}
@app.put('/api/playlists/{ident}')
def update_playlist(ident:str,p:Playlist,_:None=Depends(admin)):
    validate_playlist(p)
    with db() as c:
        cur=c.execute('UPDATE playlists SET name=?,items=?,interval_seconds=?,shuffle=? WHERE id=?',(p.name,json.dumps(p.media_ids),p.interval_seconds,int(p.shuffle),ident))
        if not cur.rowcount:raise HTTPException(404)
    return {'ok':True}
@app.delete('/api/playlists/{ident}')
def delete_playlist(ident:str,_:None=Depends(admin)):
    with db() as c:
        c.execute('UPDATE devices SET playlist_id=NULL WHERE playlist_id=?',(ident,))
        c.execute('DELETE FROM playlists WHERE id=?',(ident,))
    return {'ok':True}
@app.get('/api/devices')
def devices(_:None=Depends(admin)):
    with db() as c:return [{k:r[k] for k in ('id','name','scene_id','playlist_id','created')} for r in c.execute('SELECT * FROM devices')]
@app.post('/api/pairing/qr')
def create_qr_pairing(req:Request,_:None=Depends(admin)):
    import qrcode
    from urllib.parse import quote
    token=secrets.token_urlsafe(32)
    expires=int(time.time())+300
    with db() as c:
        c.execute('DELETE FROM qr_invites WHERE expires<?',(int(time.time()),))
        c.execute('INSERT INTO qr_invites VALUES(?,?)',(digest(token),expires))
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
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT expires FROM qr_invites WHERE token_hash=?',(digest(body.token),)).fetchone()
        if not row or row['expires']<now:raise HTTPException(404,'QR code expired or already used')
        c.execute('DELETE FROM qr_invites WHERE token_hash=?',(digest(body.token),))
        device_token=secrets.token_urlsafe(36);ident=uuid4().hex
        c.execute('INSERT INTO devices(id,name,token_hash,scene_id,created,playlist_id) VALUES(?,?,?,?,?,?)',(ident,body.name,digest(device_token),None,now,None))
    return {'token':device_token,'device_id':ident}

@app.post('/api/pairing')
def pairing(body:dict):
    name=str(body.get('name','Android device'))[:80]
    code=secrets.token_urlsafe(12)
    with db() as c:
        c.execute('DELETE FROM pairing WHERE expires<?',(int(time.time()),))
        c.execute('INSERT INTO pairing VALUES(?,?,?)',(digest(code),name,int(time.time())+600))
    return {'code':code,'expires_in':600}
@app.post('/api/pairing/approve')
def approve(body:Pair,_:None=Depends(admin)):
    with db() as c:
        row=c.execute('SELECT * FROM pairing WHERE code_hash=?',(digest(body.code),)).fetchone()
        if not row or row['expires']<time.time():raise HTTPException(404,'Code expired or invalid')
        token=secrets.token_urlsafe(36);ident=uuid4().hex
        c.execute('INSERT INTO devices(id,name,token_hash,scene_id,created) VALUES(?,?,?,?,?)',(ident,row['device_name'],digest(token),None,int(time.time())))
        c.execute('DELETE FROM pairing WHERE code_hash=?',(digest(body.code),))
    # Device receives token through one-time polling, implemented in /api/pairing/claim.
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS claims(code_hash TEXT PRIMARY KEY, token TEXT NOT NULL, expires INTEGER NOT NULL)');c.execute('INSERT INTO claims VALUES(?,?,?)',(digest(body.code),token,int(time.time())+600))
    return {'ok':True,'device_id':ident}
@app.post('/api/pairing/claim')
def claim(body:Pair):
    with db() as c:
        try:r=c.execute('SELECT * FROM claims WHERE code_hash=?',(digest(body.code),)).fetchone()
        except sqlite3.OperationalError:r=None
        if not r or r['expires']<time.time():return {'pending':True}
        c.execute('DELETE FROM claims WHERE code_hash=?',(digest(body.code),))
    return {'pending':False,'token':r['token']}
@app.put('/api/devices/{ident}/scene')
def assign(ident:str,body:DeviceAssign,_:None=Depends(admin)):
    with db() as c:
        if body.scene_id and not c.execute('SELECT 1 FROM scenes WHERE id=?',(body.scene_id,)).fetchone():raise HTTPException(404,'Scene not found')
        if body.playlist_id and not c.execute('SELECT 1 FROM playlists WHERE id=?',(body.playlist_id,)).fetchone():raise HTTPException(404,'Playlist not found')
        if body.scene_id and body.playlist_id:raise HTTPException(400,'Choose scene or playlist')
        cur=c.execute('UPDATE devices SET scene_id=?,playlist_id=? WHERE id=?',(body.scene_id,body.playlist_id,ident))
        if not cur.rowcount:raise HTTPException(404,'Device not found')
    return {'ok':True}
@app.delete('/api/devices/{ident}')
def revoke(ident:str,_:None=Depends(admin)):
    with db() as c:c.execute('DELETE FROM devices WHERE id=?',(ident,))
    return {'ok':True}
def expanded_playlist(c,ident):
    row=c.execute('SELECT * FROM playlists WHERE id=?',(ident,)).fetchone()
    return {'id':row['id'],'name':row['name'],'media_ids':json.loads(row['items']),'interval_seconds':row['interval_seconds'],'shuffle':bool(row['shuffle'])} if row else None

def device_payload(c,d):
    scene_row=c.execute('SELECT manifest FROM scenes WHERE id=?',(d['scene_id'],)).fetchone() if d['scene_id'] else None
    scene=json.loads(scene_row['manifest']) if scene_row else None
    direct=expanded_playlist(c,d['playlist_id']) if d['playlist_id'] else None
    linked={}
    if scene:
        for layer in scene.get('layers',[]):
            if layer.get('type')=='playlist':
                pid=layer.get('playlist_id')
                linked[pid]=expanded_playlist(c,pid)
    ids=media_ids_for_payload({'scene':scene,'playlist':direct,'playlists':linked})
    kinds={r['id']:r['kind'] for r in c.execute('SELECT id,kind FROM media') if r['id'] in ids}
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
    with db() as c:return device_payload(c,d)
@app.get('/api/device/media/{ident}')
def device_media(ident:str,req:Request,d:dict=Depends(device)):
    with db() as c:
        row=c.execute('SELECT * FROM media WHERE id=?',(ident,)).fetchone()
        allowed=media_ids_for_payload(device_payload(c,d))
    if not row or ident not in allowed:raise HTTPException(404)
    return FileResponse(MEDIA/row['filename'],media_type=row['mime'])
app.mount('/',StaticFiles(directory=str(WEB),html=True),name='web')
