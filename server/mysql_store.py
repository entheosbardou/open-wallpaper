"""MySQL 8 storage; no SQLite dependency or automatic legacy data migration."""
import os
from contextlib import contextmanager
from urllib.parse import urlparse, unquote
import pymysql


def connection():
    url=os.environ.get('DATABASE_URL','')
    if not url:
        raise RuntimeError('DATABASE_URL must be set to mysql://user:password@host:3306/database')
    parsed=urlparse(url)
    if parsed.scheme not in ('mysql','mysql+pymysql') or not parsed.hostname or not parsed.path.strip('/'):
        raise RuntimeError('DATABASE_URL must be a MySQL URL with a database name')
    return pymysql.connect(host=parsed.hostname,port=parsed.port or 3306,
        user=unquote(parsed.username or ''),password=unquote(parsed.password or ''),
        database=unquote(parsed.path.lstrip('/')),charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,autocommit=False,connect_timeout=10)

class Database:
    def __init__(self, con):self.con=con
    def execute(self, sql, params=()):
        cursor=self.con.cursor()
        cursor.execute(sql.replace('?', '%s'), params)
        return cursor

@contextmanager
def db():
    con=connection()
    try:
        yield Database(con)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:con.close()

SCHEMA=[
'''CREATE TABLE IF NOT EXISTS users (id VARCHAR(32) PRIMARY KEY, username VARCHAR(60) NOT NULL UNIQUE, salt VARCHAR(128), password_hash VARCHAR(256), role VARCHAR(16) NOT NULL DEFAULT 'user', enabled TINYINT NOT NULL DEFAULT 1, oidc_issuer VARCHAR(255), oidc_sub VARCHAR(255), UNIQUE KEY uq_oidc (oidc_issuer,oidc_sub))''',
'''CREATE TABLE IF NOT EXISTS sessions (token_hash CHAR(64) PRIMARY KEY, expires BIGINT NOT NULL, user_id VARCHAR(32), KEY ix_session_user (user_id))''',
'''CREATE TABLE IF NOT EXISTS folders (id VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL, parent_id VARCHAR(32), KEY ix_folder_parent (parent_id))''',
'''CREATE TABLE IF NOT EXISTS media (id VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL, filename VARCHAR(2048) NOT NULL, kind VARCHAR(32) NOT NULL, mime VARCHAR(128) NOT NULL, folder_id VARCHAR(32), UNIQUE KEY uq_media_filename (filename(768)), KEY ix_media_folder (folder_id), KEY ix_media_name (name))''',
'''CREATE TABLE IF NOT EXISTS scenes (id VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL, manifest LONGTEXT NOT NULL, owner_id VARCHAR(32), visibility VARCHAR(16) NOT NULL DEFAULT 'private')''',
'''CREATE TABLE IF NOT EXISTS devices (id VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL, token_hash CHAR(64) NOT NULL, scene_id VARCHAR(32), created BIGINT NOT NULL, playlist_id VARCHAR(32), owner_id VARCHAR(32), UNIQUE KEY uq_device_token (token_hash))''',
'''CREATE TABLE IF NOT EXISTS pairing (code_hash CHAR(64) PRIMARY KEY, device_name VARCHAR(255) NOT NULL, expires BIGINT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS qr_invites (token_hash CHAR(64) PRIMARY KEY, expires BIGINT NOT NULL, owner_id VARCHAR(32))''',
'''CREATE TABLE IF NOT EXISTS playlists (id VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL, items LONGTEXT NOT NULL, interval_seconds INT NOT NULL, shuffle TINYINT NOT NULL, owner_id VARCHAR(32), visibility VARCHAR(16) NOT NULL DEFAULT 'private')''',
'''CREATE TABLE IF NOT EXISTS user_permissions (user_id VARCHAR(32) NOT NULL, permission VARCHAR(80) NOT NULL, allowed TINYINT NOT NULL, PRIMARY KEY (user_id,permission))''',
'''CREATE TABLE IF NOT EXISTS resource_shares (kind VARCHAR(32) NOT NULL, resource_id VARCHAR(32) NOT NULL, recipient_id VARCHAR(32) NOT NULL, can_edit TINYINT NOT NULL DEFAULT 0, PRIMARY KEY (kind,resource_id,recipient_id))''',
'''CREATE TABLE IF NOT EXISTS auth_states (state_hash CHAR(64) PRIMARY KEY, nonce VARCHAR(255) NOT NULL, verifier VARCHAR(255) NOT NULL, expires BIGINT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS folder_grants (folder_id VARCHAR(32) NOT NULL, user_id VARCHAR(32) NOT NULL, can_view TINYINT NOT NULL DEFAULT 0, can_use TINYINT NOT NULL DEFAULT 0, can_upload TINYINT NOT NULL DEFAULT 0, can_edit TINYINT NOT NULL DEFAULT 0, can_delete TINYINT NOT NULL DEFAULT 0, can_manage TINYINT NOT NULL DEFAULT 0, PRIMARY KEY (folder_id,user_id))''',
'''CREATE TABLE IF NOT EXISTS claims (code_hash CHAR(64) PRIMARY KEY, token VARCHAR(255) NOT NULL, expires BIGINT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS index_state (name VARCHAR(64) PRIMARY KEY, last_started BIGINT, last_finished BIGINT, last_error TEXT, files_seen BIGINT NOT NULL DEFAULT 0)'''
]

def initialize_schema():
    with db() as c:
        for statement in SCHEMA:c.execute(statement)
