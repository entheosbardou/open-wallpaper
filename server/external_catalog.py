"""Optional read-only adapter for the legacy `wallpapers.files` catalog.

Never executes writes against the external connection. Files are indexed into the
application's own tables; application folder ACLs continue to apply normally.
"""
import logging
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4
from urllib.parse import urlparse, unquote

import pymysql
from server.mysql_store import db

LOG = logging.getLogger(__name__)


def enabled():
    return os.getenv('EXTERNAL_CATALOG_ENABLED', 'false').lower() in ('1', 'true', 'yes')


def connect():
    url = os.getenv('EXTERNAL_CATALOG_URL', '')
    p = urlparse(url)
    if p.scheme not in ('mysql', 'mysql+pymysql') or not p.hostname or not p.path.strip('/'):
        raise ValueError('EXTERNAL_CATALOG_URL must be mysql://user:password@host:3306/wallpapers')
    return pymysql.connect(host=p.hostname, port=p.port or 3306,
        user=unquote(p.username or ''), password=unquote(p.password or ''),
        database=unquote(p.path.lstrip('/')), charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        connect_timeout=10, read_timeout=60)


def safe_relative(raw):
    """Reject absolute paths, traversal, NULs and Windows drive paths."""
    if not isinstance(raw, str) or '\x00' in raw or '\\' in raw:
        return None
    p = PurePosixPath(raw)
    if p.is_absolute() or any(part in ('..', '') for part in raw.split('/')) or ':' in raw.split('/')[0]:
        return None
    return p if p.parts and str(p) != '.' else None


def import_catalog(media_root, types, batch_size=250):
    """Stream legacy file rows in primary-key order; no full-table memory load.

    The catalog path is relative to EXTERNAL_CATALOG_MEDIA_ROOT, which is a
    container-visible directory beneath the application's media root.
    """
    root = Path(media_root).resolve()
    configured = os.getenv('EXTERNAL_CATALOG_MEDIA_ROOT', str(root))
    catalog_root = Path(configured).resolve()
    if catalog_root != root and root not in catalog_root.parents:
        raise ValueError('EXTERNAL_CATALOG_MEDIA_ROOT must be inside /app/data/media')
    prefix = catalog_root.relative_to(root)
    if not catalog_root.is_dir():
        raise ValueError('External catalog media root does not exist in the container')

    seen = 0
    last_id = 0
    folders = {(): None}
    with db() as c:
        c.execute('REPLACE INTO index_state(name,last_started,last_finished,last_error,files_seen) VALUES(?,UNIX_TIMESTAMP(),NULL,NULL,0)', ('external_catalog',))
    try:
        conn = connect()
        try:
            while True:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT id, relative_path FROM files WHERE id > %s AND is_present = 1 ORDER BY id LIMIT %s', (last_id, batch_size))
                    rows = cursor.fetchall()
                if not rows:
                    break
                last_id = rows[-1]['id']
                with db() as c:
                    for item in rows:
                        relative = safe_relative(item['relative_path'])
                        if relative is None or relative.suffix.lower() not in types:
                            continue
                        path = catalog_root.joinpath(*relative.parts)
                        # Only expose files physically present under the configured root.
                        if not path.is_file() or not path.resolve().is_relative_to(catalog_root):
                            continue
                        app_relative = prefix / relative
                        parts = app_relative.parts[:-1]
                        parent = None
                        for depth in range(1, len(parts) + 1):
                            key = parts[:depth]
                            if key not in folders:
                                row = c.execute('SELECT id FROM folders WHERE parent_id <=> ? AND name=? LIMIT 1', (parent, parts[depth-1])).fetchone()
                                if row:
                                    folders[key] = row['id']
                                else:
                                    ident = uuid4().hex
                                    c.execute('INSERT INTO folders(id,name,parent_id) VALUES(?,?,?)', (ident,parts[depth-1],parent))
                                    folders[key] = ident
                            parent = folders[key]
                        mime, kind = types[relative.suffix.lower()]
                        c.execute('INSERT IGNORE INTO media(id,name,filename,kind,mime,folder_id) VALUES(?,?,?,?,?,?)',
                            (uuid4().hex, relative.name, app_relative.as_posix(), kind, mime, parent))
                        seen += 1
                with db() as c:
                    c.execute('UPDATE index_state SET files_seen=? WHERE name=?', (seen,'external_catalog'))
        finally:
            conn.close()
        with db() as c:
            c.execute('UPDATE index_state SET last_finished=UNIX_TIMESTAMP(),files_seen=? WHERE name=?', (seen,'external_catalog'))
    except Exception as exc:
        LOG.exception('External catalog import failed')
        with db() as c:
            c.execute('UPDATE index_state SET last_error=?,last_finished=UNIX_TIMESTAMP() WHERE name=?', (str(exc)[:2000],'external_catalog'))
