# Project status

Updated: 2026-11-04 (date only; time and timezone were not recorded with this repository snapshot).

This file records a source review, not a live health check. Statements below describe the checked-out source and repository documentation as of the update date. They do not establish that a deployment, workflow, or device has been tested or is currently healthy.

## Implemented in source

- The server is a FastAPI application in `server/app.py`. It uses PyMySQL with MySQL and creates tables using `CREATE TABLE IF NOT EXISTS` during initialization. No SQLAlchemy/Alembic migration layer is present in the checked source.
- Compose defines MySQL 8.4 and the wallpaper server, waits for MySQL health before starting the server, reads required passwords from `.env`, and persists the MySQL database and application data in named volumes. The server image runs as an unprivileged user and stores media under `/app/data/media` by default.
- `compose.yaml` points to `ghcr.io/entheosbardou/open-wallpaper:latest`; `compose.build.yaml` is the local build overlay and tags the image `open-wallpaper:local`.
- The server source includes local account setup/login, optional OIDC routes, roles and permissions, resource sharing, folder grants, media and folder management, scenes, playlists, device registration and pairing, and device configuration/media endpoints.
- The dashboard is served from `web/index.html`. The Android Kotlin app supports manual pairing and QR pairing, scene/playlist sync, local media caching, and live-wallpaper playback.
- The Android manifest currently permits cleartext HTTP. Treat that as local-network testing behavior; use HTTPS for remote access.
- The Docker publish workflow is configured to publish Linux `amd64` and `arm64` images on pushes to `main`, version tags, or manual dispatch. The Android workflow is configured to build and upload a debug APK on manual dispatch or relevant Android/workflow changes.

## Source limitations and cautions

- Media indexing is currently performed synchronously by `sync_media()` during media/folder API requests and device configuration. It walks the media directory and reconciles records; it is not a background indexing service and does not provide a durable indexing queue or progress history.
- Media and folder list APIs load records into memory and do not implement server-side pagination. Do not describe the current implementation as verified for millions of files.
- Database initialization creates missing tables but does not evolve existing table definitions through versioned migrations. Schema changes to an existing installation need an explicit, reviewed upgrade plan.
- The server/database/media setup is for clean MySQL installations. No SQLite import or conversion exists.
- The Android client is experimental. Its renderer supports image and video playback, playlist rotation, and a clock layer, with limitations: video uses a dedicated playback surface and cannot composite clock/image overlays; other supported rendering combinations must be confirmed in the current client source before being promised.
- The Android app uses cleartext HTTP for trusted LAN testing; remote use requires HTTPS. The debug APK workflow does not sign production releases.
- No independent security audit is recorded in the repository snapshot.

## Verification and release state

- This source review inspected the server, dashboard, Android client and manifest, Docker configuration, workflow definitions, and README.
- No test suite, Docker build, APK build, workflow run, live deployment, device pairing, or end-to-end playback test was performed for this status update.
- The default Compose configuration references the published `latest` image. A local source build requires the build overlay. Source edits alone do not update or publish the image.
- Before a release, use the repository workflows as intended, inspect their results, then verify a clean Compose install with the published image and fresh volumes in a disposable environment. Test Android pairing and playback on a device over HTTPS for remote access.
- Back up both `wallpaper-mysql` and `wallpaper-data` before any operation that may replace or remove them. `docker compose down -v` removes named volumes and their data.
