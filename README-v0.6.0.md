# Open Wallpaper v0.6.0 — MySQL-only preview

**Fresh database release:** SQLite data is not migrated. Existing user accounts, device pairing, scenes, and playlists must be recreated. Back up your old volume before switching. Keep your existing media files; no conversion is required.

## Deploy using the bundled MySQL 8 service

1. Copy `.env.example` to `.env` and set two strong, URL-safe passwords.
2. Replace `REPLACE_WITH_GITHUB_OWNER` in `compose.yaml` with the correct GHCR owner, or use `docker compose -f compose.yaml -f compose.build.yaml up -d --build` to build locally.
3. Start with `docker compose up -d` (or the build command above).
4. Open `http://localhost:8080` and create the administrator account.

MySQL data is persisted in `mysql-data`; the application data/media is persisted in `wallpaper-data`.

## External MySQL server

For an existing MySQL 8+ instance, create an **empty, dedicated database** (for example `open_wallpaper`) and a user with privileges to create tables and read/write the database. Set `DATABASE_URL=mysql://user:password@mysql-host:3306/open_wallpaper` in the wallpaper-server environment. Remove the `mysql` service and `depends_on` from your local Compose override. Do not run an unrelated database dump against the app database. URL-encode special characters in passwords.

The supplied `wallpapers` schema is **not imported or modified**. A separate external catalog adapter is not included in this preview.

## Indexing and media API

The server initializes MySQL tables on startup, then schedules media indexing in a background thread. The media endpoint defaults to 500 records and accepts `?limit=500&offset=0` (maximum 2000). Index progress is available at `GET /api/index/status` for signed-in users; administrators can request another scan using `POST /api/index/rescan`. Indexing adds records for newly discovered files and does not delete or move physical files. Indexing does not currently reconcile deleted or moved files, and `offset` pagination is not ideal for multi-million-row libraries.

**Current limitations:** This preview has not been end-to-end tested against a running MySQL server. The dashboard currently requests one page of media; a complete large-library browser requires client-side pagination and more scalable folder-permission queries. Run on a backup/test instance before replacing production.
