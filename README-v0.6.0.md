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


## Optional existing `wallpapers` MySQL catalog

Disabled by default. Ordinary deployments use the built-in filesystem indexer.
To import media paths from a pre-existing `wallpapers.files` catalog, configure:

```env
EXTERNAL_CATALOG_ENABLED=true
EXTERNAL_CATALOG_URL=mysql://catalog_reader:URL_ENCODED_PASSWORD@mysql.thelinclan.com:3306/wallpapers
EXTERNAL_CATALOG_MEDIA_ROOT=/app/data/media
```

Mount the existing wallpaper files inside the container at the configured media root.
`EXTERNAL_CATALOG_MEDIA_ROOT` must be the same as, or a subdirectory of, `/app/data/media`.
For example, with `- /mnt/nas-data/wallpapers:/app/data/media:ro`, use
`/app/data/media`. If the catalog paths are relative to a nested directory, set
`EXTERNAL_CATALOG_MEDIA_ROOT` to that nested directory. The application database
(`DATABASE_URL`) remains separate from the catalog database.

Create a read-only catalog account using your own MySQL administrator:

```sql
CREATE USER 'catalog_reader'@'%' IDENTIFIED BY 'CHOOSE_A_STRONG_PASSWORD';
GRANT SELECT ON wallpapers.files TO 'catalog_reader'@'%';
```

The adapter uses keyset pagination on `files.id`, imports only `is_present=1`
rows with supported extensions, and checks that each file exists under the
configured container-visible root. It writes ONLY to Open Wallpaper's own MySQL
application database, never to `wallpapers`. Imported folders use the existing
Open Wallpaper folder ACL rules. Login and API startup do not wait for import.

**Preview limitations:** This initial adapter reads the legacy `files` table,
not `fm_assets`/`fm_asset_locations` or `fm_change_events`. Re-running an import
adds newly discovered files, but does not synchronize deletions, renames, or
metadata changes. Files already indexed remain in the application catalog even
if removed from the external catalog. For large collections, indexing may take
time because each candidate is checked on the mounted filesystem. This is not
a live SQL-backed media browser. Do not enable until catalog paths and media
mounts have been verified.
