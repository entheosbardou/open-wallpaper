# Codex instructions for Open Wallpaper

## Project scope

- This repository contains a self-hosted live-wallpaper server, web dashboard, and experimental Android wallpaper client. Keep work focused on these components and their shared APIs.
- Inspect the current implementation before changing it. The repository is an alpha/prototype; do not treat plans, README wording, or issue descriptions as proof that a feature exists.
- Keep source and generated artifacts together: when server, web, or Android source changes, update the corresponding files in this repository. Do not leave the source change only in a temporary copy or generated image.
- Do not deploy the application, publish an image or APK, push changes, or alter a live installation unless the user explicitly asks.

## Architecture and current implementation

- The backend is a single FastAPI application in `server/app.py`. It uses direct parameterized PyMySQL calls and creates its MySQL tables in `init()` with `CREATE TABLE IF NOT EXISTS` statements. The current code does not use SQLAlchemy or Alembic.
- MySQL 8.4 is the only supported application database. Keep the MySQL-only design; do not add SQLite support, compatibility layers, database fallbacks, or SQLite conversion tools.
- The web dashboard is served from `web/index.html`, which contains its HTML, CSS, and JavaScript.
- The Android application is Kotlin under `android/app/src/main/java/org/openwallpaper/client`. Maintain compatibility with the server's existing `/api` routes and payloads when changing either side.
- Docker Compose runs the server and MySQL. `compose.yaml` uses the published GHCR image; `compose.build.yaml` is a local build overlay. The Dockerfile builds the Python server image. The Android workflow/build instructions produce a debug APK; do not imply it is production signed.
- Do not add external media catalog or external catalog adapter behavior. The server owns its media index in its application database and stores media under `DATA_DIR/media`.

## Data and schema safety

- Preserve application data across routine upgrades. `init()` uses `CREATE TABLE IF NOT EXISTS`; it is not a versioned migration system and does not update existing table definitions. Do not imply otherwise or add destructive schema changes as startup side effects.
- Before changing an existing schema or performing a data migration, explain the exact tables and columns affected, the data transformation, and a backup and rollback approach. Wait for explicit user approval before applying it to persistent data.
- Never drop or recreate user data, database volumes, or media volumes unless the user explicitly requests that operation. Warn clearly when a requested command such as `docker compose down -v` would remove persistent volumes.
- Use MySQL-compatible parameterized SQL. Avoid interpolating user-controlled values into SQL; only interpolate identifiers that come from fixed internal allowlists.
- Keep database transactions bounded and consistent with the existing `db()` context manager. Keep file operations and database metadata updates aligned, and account for failures between filesystem and database changes.
- Preserve stable media IDs and scene, playlist, sharing, and device references during edits and media reconciliation. Never resolve an ambiguous file match by deleting or overwriting files. The current reconciler handles duplicate paths and unique-basename matches; retain conservative behavior and references when changing it.
- Media is stored below `DATA_DIR/media` (default `./data/media`, `/app/data/media` in the container). Preserve path containment and symlink protections. Do not assume the media directory is writable beyond the documented upload and management operations.

## Live wallpaper behavior and API compatibility

- Preserve existing server endpoints, request and response shapes, identifiers, and authentication behavior unless the task explicitly changes them. If an API change affects Android, update and verify both the server and client together.
- The server manages local users, sessions, optional OIDC login, roles, permissions, shared scenes/playlists, folder grants, devices, pairing, media, playlists, and scene manifests. Reuse the existing access checks rather than introducing route-specific shortcuts.
- Folder grants cover `view`, `use`, `upload`, `edit`, `delete`, and `manage`, with inherited rights and child overrides. Enforce authorization in the backend for listings, search, direct file requests, uploads, moves, deletion, playlist expansion, and device configuration/media endpoints. Unauthorized direct media access should remain hidden with 404 where the existing API does so.
- Preserve ownership and sharing checks for scenes, playlists, and devices. Validate media, folder, scene, and playlist references before saving or returning them to a user or device.
- Pairing credentials must remain unpredictable, short-lived, and single-use where implemented. Do not weaken TLS validation for OIDC. Avoid exposing passwords, session tokens, device tokens, OIDC secrets, or pairing tokens in logs or responses beyond their intended one-time use.
- Preserve CSRF protections for cookie-authenticated state-changing requests and existing origin validation behavior.
- Keep the Android client’s actual supported behavior in view: image and video playback, playlist rotation, clock/image layering limits, offline media cache, and pairing flows. Do not promise unsupported rendering behavior or silently change playback semantics.

## Media indexing and scale

- Keep media discovery scoped to relevant media and folder operations. Preserve correctness under concurrent requests and avoid duplicate records or broken references.
- Keep query result sizes and filesystem work appropriate for the implementation. When changing indexing, pagination, or progress behavior, update the API, dashboard, tests, and documentation together.
- Do not add monitoring, telemetry, analytics, alerting, recurring checks, or background status reporting unless the user explicitly requests it. Normal application logs and user-requested operation progress are allowed. A bounded one-time check to verify an authorized change is allowed; do not poll long-running work unless asked.

## Configuration and deployment

- Keep database configuration in environment variables (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`) and preserve the Compose service discovery and health dependency.
- Keep credentials and secrets out of committed files. Use `.env.example` for names and safe example values only; never place real secrets in Compose files, source, tests, build contexts, or outputs.
- Preserve persistent MySQL and application media volumes. Treat volume deletion, data replacement, production deployment, and image publication as consequential operations requiring explicit user instruction.
- Preserve reverse-proxy behavior and `PUBLIC_URL` use for externally generated pairing links. Do not hardcode domains, addresses, credentials, or machine-specific paths.
- Do not change Authentik/OIDC setup unless requested or required by an explicitly requested integration change.

## Testing and verification

- Use the existing pytest suite and its MySQL 8.4 setup for database-dependent verification. Never substitute SQLite for MySQL. Do not run destructive tests against user data or the production database.
- The existing `tests/test_mysql_access.py` fixture truncates application tables. Run it only with an explicitly disposable test database configured; inspect the test configuration before running it.
- Choose checks that cover the changed behavior. For authorization work, test both allowed and denied access, including direct media requests and device payloads as relevant. For API changes used by Android, verify the corresponding client behavior where possible.
- Do not add or run unrelated tests. Report only checks that were actually run and distinguish source changes, test results, builds, and deployments.
- Update `README.md` and focused tests when configuration, setup, API, database, or access-control behavior changes. Keep documented capabilities aligned with the current implementation.

## Working approach

1. Read the relevant server, web, Android, schema initialization, configuration, and test code before editing.
2. Identify API and data compatibility effects, especially authorization, media references, pairing, and Android playback.
3. Make the smallest complete change within the requested scope and update related source files in this repository.
4. Run focused checks when requested or needed to substantiate the result; never claim an unrun check passed.
5. Summarize what changed and what was verified. Keep deployment and publication claims separate from local source or build results.
