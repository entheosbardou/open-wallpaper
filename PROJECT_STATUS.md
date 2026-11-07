# Project status

## 2026-11-05 — Screen switching responsiveness in source

- Scene and playlist picker trees now remain mounted while switching tabs. They rebuild when media or Gallery data changes, or when an edit explicitly requires it. This preserves picker scroll and expansion state during ordinary navigation.
- Initial data loads and Gallery catalog updates redraw scene and playlist pickers only when their tabs are open. Picker selection uses sets, and filtering uses an ID lookup map. The earlier 150-item library limit and search delay were removed after the user clarified that switching screens was the main issue. JavaScript syntax and diff checks passed; browser performance and live deployment were not measured.

## 2026-11-05 — Library browsing layout in source

- The dashboard opens the library in Unsorted and displays media inside a bounded, independently scrolling grid. Gallery pagination stays inside that grid. Grid redraws retain its scroll position, while choosing another folder starts at the top. This is a local source change; no deployment or browser validation was performed.

## 2026-11-06 — Android media preview and manual sync progress

- The Android activity now previews the first assigned cached image or looping video and reports file count and byte progress during manual sync. A Stop sync button cancels the active connection and discards its partial download while retaining the last completed configuration. This is a media preview, not a composite rendering of scene layers. Source only; an Android build and device check have not been run.

## 2026-11-05 19:06 MST — Gallery playlist tablet sync confirmed

- The user confirmed that the tablet successfully synced the Gallery playlist after the Gallery batch lookup and the paired Open Wallpaper change were deployed. Open Wallpaper checks assigned IDs through Gallery's collection/category authorization endpoint in batches of up to 500 and serves approved files from `GALLERY_MEDIA_ROOT`. This is user-reported end-to-end success; the exact deployed Open Wallpaper image digest and individual denied-file behavior were not independently checked here.

## 2026-11-05 — Gallery batch lookup in source

- Device authorization now sends up to 500 assigned file IDs in one request to Gallery's new `/api/external/media/resolve` endpoint. Gallery returns current collection/category permission decisions and relative paths; Open Wallpaper continues to serve approved bytes from `GALLERY_MEDIA_ROOT`. The paired Gallery API source change is required before this Open Wallpaper revision can be deployed. Neither source change has been deployed or tablet tested.

## 2026-11-05 — Gallery playlist sync timeout follow-up

- The first catalog-based device authorization implementation made one Gallery HTTP request per assigned file. A 25-image playlist could exceed the Android client's 20-second configuration read timeout. Nearby file IDs are now checked in bounded catalog pages of at most 250 IDs, preserving individual allow/deny decisions. The reported tablet timeout has not yet been retested with this source change deployed.

## 2026-11-05 — Gallery tablet delivery fix in source

- The live tablet had 25 assigned Gallery images and a readable `GALLERY_MEDIA_ROOT` mount, but Gallery returned HTTP 401 for its stored device grant (`Gallery identity needs to be refreshed by the user`). The owner's refreshed Gallery catalog request returned the assigned image and its relative path, and that file was present on the mount.
- Device configuration and media requests now use the owner's refreshed Gallery identity to check each assigned file through `/api/external/media`. Open Wallpaper serves approved bytes from `GALLERY_MEDIA_ROOT`. This is a local source change; it has not been built, deployed, or verified on the tablet.

## 2026-11-05 — Dashboard sign-in responsiveness in source

- After session verification, the dashboard now opens before loading the media library. Gallery collection discovery runs after the local library renders, so a slow Gallery request no longer holds the initial view. This improves perceived sign-in time; the underlying media index and OIDC requests can still take time. This is a local source change, not a deployment or measured live latency fix.

## 2026-11-05 — Gallery category discovery in Open Wallpaper source

- Open Wallpaper now reads category names from the Gallery collection response and exposes category folders before fetching images. Category selection requests a category-filtered catalog page. This requires Gallery to add a `categories` map to `/api/external/collections` and honor `category` on `/api/external/media`; those Gallery API changes are outside this repository. No deployment or live validation was performed for this source change.

## 2026-11-05 — Gallery collection loading in source

- The dashboard now fetches accessible Gallery collection names before image data and fetches paged images when a collection is opened. This source change depends on matching Gallery API changes in the Gallery repository; neither repository was deployed.

## 2026-11-05 — Gallery collection browsing in source

- The dashboard groups Gallery media by collection path and category. The library folder picker opens child menus on hover and selects a collection on click; scene and playlist pickers retain expandable folders. Gallery collection and category choices remain read-only. The catalog loads 250 items per page, so later items appear after **Load more Gallery media**. This is a local source change; no image was published or live deployment performed.
- Scene and playlist media pickers provide search, image/video filtering, name sorting, and select-visible controls. Scenes can add selected media as layers; playlists include selected media. These dashboard changes are local source only.
- Gallery collection and category branches in both pickers can select all accessible items across catalog pages. Playlist selection adds those file IDs to the current edit; scene selection creates a saved slideshow playlist and adds it as a layer. The selection is a snapshot of current items. Open Wallpaper splits device grants into batches of 500 Gallery items to meet Gallery's per-request limit; existing single-grant records remain readable.
- The dashboard stores the in-progress scene and playlist edit in tab-scoped session storage and restores it after an unexpected page reload for the same signed-in account. Signing out clears that draft. The dashboard itself only requests a reload on sign-out; the cause of any other page reload has not been established.

The original source-review snapshot below had only a date, without time or timezone. Later timestamped entries record subsequent deployment and verification evidence. Each entry describes its own observation time, not continuous health.

## 2026-11-04 23:20 MST — Optional Gallery integration connected

- Current source revision `f90e467` is on `main` and `origin/main`. The user reports the Android APK workflow passed, a new Docker image was published and deployed, and Gallery media is now visible in Open Wallpaper. The exact APK run and deployed image digest were not independently recorded here.
- The `live-wallpaper` Portainer stack on `linux-docker` was configured with Gallery's HTTPS API URL, the shared Authentik issuer/client, a stable client instance ID, and a private Fernet key. The NAS wallpaper root is mounted read-only at `/app/data/external/gallery`, separate from local media. The stack file was backed up as `docker-compose.yml.pre-gallery-20261104-224211.bak` on `linux-docker`. A one-time check showed HTTP 200 from `/api/status`, `gallery_enabled: true`, and a readable mount with `RW=false`.
- Authentik initially issued no refresh token. After its provider enabled the Refresh token grant and `offline_access` mapping, a fresh sign-in stored one encrypted Gallery credential in Open Wallpaper MySQL. The catalog client was corrected in this repository to send a refreshed signed ID token, which Gallery accepts. A direct signed request from the container returned HTTP 200 with an item; the user later confirmed Gallery media appears in the dashboard.
- The integration uses additive `gallery_user_credentials` and `gallery_device_grants` MySQL tables, provider-qualified `gallery:<file-id>` IDs, and a separate read-only external mount. Local media remains in its existing storage. Device assignment/grant creation, permission revocation, outage caching, and Android playback remain to be verified end to end. `current-changes.md` is reset for the next session and remains untracked.

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
