import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from server import app as server


@pytest.fixture(scope="module", autouse=True)
def initialize_mysql():
    server.init()
    with server.db() as cursor:
        for table in (
            "claims", "folder_grants", "auth_states", "resource_shares", "user_permissions",
            "users", "folders", "media", "sessions", "scenes", "devices", "pairing",
            "playlists", "qr_invites",
        ):
            cursor.execute(f"TRUNCATE TABLE `{table}`")
    yield


def test_mysql_schema_uses_innodb():
    with server.db() as cursor:
        cursor.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (os.environ["DB_NAME"],))
        engines = {row["TABLE_NAME"]: row["ENGINE"] for row in cursor.fetchall()}
    assert {"users", "media", "folders", "folder_grants", "resource_shares", "devices"} <= engines.keys()
    assert all(engine == "InnoDB" for engine in engines.values())


def test_folder_grants_hide_contents_and_block_direct_media(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "MEDIA", tmp_path / "media")
    server.MEDIA.mkdir()
    admin_id, user_id, folder_id, media_id = "admin-a", "user-a", "secret-folder", "secret-media"
    secret_file = server.MEDIA / "restricted.jpg"
    secret_file.write_bytes(b"image")
    with server.db() as cursor:
        cursor.execute("INSERT INTO users(id,username,role,enabled) VALUES(%s,%s,%s,1)", (admin_id, "admin-test", "admin"))
        cursor.execute("INSERT INTO users(id,username,role,enabled) VALUES(%s,%s,%s,1)", (user_id, "reader-test", "user"))
        cursor.execute("INSERT INTO folders(id,name,parent_id) VALUES(%s,%s,NULL)", (folder_id, "Restricted"))
        cursor.execute("INSERT INTO media(id,name,filename,kind,mime,folder_id) VALUES(%s,%s,%s,%s,%s,%s)", (media_id, secret_file.name, secret_file.name, "image", "image/jpeg", folder_id))
        token = "reader-session-token"
        cursor.execute("INSERT INTO sessions(token_hash,expires,user_id) VALUES(%s,%s,%s)", (server.digest(token), 4_000_000_000, user_id))
    regular = {"id": user_id, "role": "user"}
    with server.db() as cursor:
        assert server.visible_folder_ids(cursor, regular) == (set(), set())
        assert server.filter_media_ids(cursor, regular, [media_id]) == []
        with pytest.raises(HTTPException) as exc:
            server.media_check(cursor, regular, media_id, "view")
        assert exc.value.status_code == 404
        assert server.folder_rights(cursor, {"id": admin_id, "role": "admin"}, folder_id)["view"]
    client = TestClient(server.app)
    assert client.get("/api/media", cookies={"session": token}).json() == []
    assert client.get(f"/api/media/{media_id}/file", cookies={"session": token}).status_code == 404


def test_permission_upsert_and_share_records():
    with server.db() as cursor:
        cursor.execute("INSERT INTO user_permissions VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE allowed=VALUES(allowed)", ("user-a", "media.view", 1))
        cursor.execute("INSERT INTO user_permissions VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE allowed=VALUES(allowed)", ("user-a", "media.view", 0))
        cursor.execute("SELECT allowed FROM user_permissions WHERE user_id=%s AND permission=%s", ("user-a", "media.view"))
        row = cursor.fetchone()
    assert row["allowed"] == 0

