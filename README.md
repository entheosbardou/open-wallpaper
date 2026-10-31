# Open Wallpaper v0.4.0

Self-hosted wallpaper server and experimental Android live wallpaper client.

## Quick start

For users downloading a published GHCR image, set the GitHub owner in `compose.yaml`, then run:

```bash
docker compose up -d
```

For local source builds:

```bash
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Open http://localhost:8080 and create the administrator account.

## New in v0.4.0

- Create folders and nested subfolders in the Media Library. Select media in bulk and move it between folders; deleting a folder moves its media to Unsorted.
- Assign a **scene or playlist** directly to a paired device.
- Add existing playlists as layers inside scenes.
- Android client downloads all referenced playlist media and rotates it at the playlist interval; shuffle is supported.
- Existing SQLite databases are migrated automatically (adds folder and device playlist columns).

## Upgrade and data

**Keep your existing Docker volume.** Database migrations preserve media, scenes, playlists and paired devices. Back up the volume before upgrading. Android devices need the newly built APK to play playlist assignments and playlist layers.

## Limitations

- Android video uses a dedicated playback surface and cannot composite clock/image layers over video yet.
- Playlist changes are polled approximately once a minute while the wallpaper is visible. Playback timing starts with the wallpaper engine, not a server-wide synchronized clock.
- Image playback currently decodes images during redraw and may use significant memory or battery for very large images.
- Browser preview of playlist layers displays the first item; it does not automatically rotate.
- No native Windows/Linux client or arbitrary HTML/JS scene renderer yet.
- Debug APK builds are not signed for production distribution.
- For trusted LAN testing only until TLS, CSRF protections and deployment hardening are added.

## GitHub workflows

- `.github/workflows/android-apk.yml` builds a debug APK artifact.
- `.github/workflows/docker-publish.yml` publishes multi-architecture GHCR images.

\n## QR pairing (v0.4.1)\n\n1. Open the server dashboard from a URL reachable by the tablet (for example `http://192.168.1.20:8080`).\n2. Go to Devices → Generate pairing QR.\n3. Open the updated Android APK → Scan pairing QR code, grant camera access, and scan.\n4. Assign a scene or playlist to the newly paired device, then sync.\n\nQR invites expire after five minutes and can be claimed only once. Anyone who can scan the code can claim it, so keep the dashboard private. The Android app requires camera access to scan. If the dashboard uses `localhost`, set the optional `PUBLIC_URL` environment variable on the Docker service to the reachable base URL (including `http://` or `https://`), then restart. Manual pairing remains available; this release also fixes its polling and device insertion bugs.\n\nThe Android client adds the ZXing embedded scanner dependency. GitHub Actions will download it during APK compilation.\n
## v0.4.2 QR scanner repair

Android requests CAMERA permission before opening the embedded ZXing scanner, and registers an `openwallpaper://pair` VIEW/BROWSABLE intent filter so external QR apps can offer Open Wallpaper as a handler. Some stock camera apps do not open non-HTTP custom links; in that case use the in-app Scan button or a QR scanner that supports custom URI schemes. The device must reach the server URL encoded in the QR code.

## v0.4.3 scene layer editor fix

Fixed layer creation on LAN HTTP deployments by replacing direct `crypto.randomUUID()` calls with a secure random UUID fallback using `crypto.getRandomValues()`. This affects media, playlist, clock, and create-from-selected scene layers. Rebuild/redeploy the Docker server and hard-refresh the dashboard; the Android APK does not need rebuilding for this change.
