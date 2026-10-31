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

