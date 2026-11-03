# Open Wallpaper v0.6.0 (MySQL-only preview)

**Start with [README-v0.6.0.md](README-v0.6.0.md).** Older instructions below describe historical releases and SQLite upgrades, which do not apply to v0.6.0.

---

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

## Media folders and automatic import (v0.4.4)

Place images or videos in the persistent Docker data volume under `media/`, including nested directories. The server discovers supported files when the Media or Folders API is loaded and adds them to the database without duplicating previously imported paths. Existing media IDs and playlist/scene references are retained.

Selecting a folder in the dashboard before uploading now writes files to that folder on disk, preserving the original filename (adding `(1)`, `(2)` etc. on collisions). Moving, renaming, and deleting folders in the dashboard also updates the physical files. Deleting a folder moves its media to the root Unsorted area. Back up the Docker data volume before upgrading.

## Media index repair (v0.4.5)

Opening Media Library performs a serialized filesystem reconciliation. Before the first repair, the server creates `data/app.sqlite3.before-media-repair-v045.bak` using SQLite's online backup API. Exact duplicate file paths are consolidated, and old paths are consolidated with a new path only when the physical filename is unambiguous. Scene and playlist media references are remapped to the surviving ID. Physical media files are never deleted by repair. Ambiguous same-name files are left alone rather than guessed. Keep a separate backup of the Docker volume before upgrading.

## Folder-aware playlists and scenes (v0.4.6)

Playlists can select files and entire folders recursively. Folder selections are stored by folder ID and expanded on each device config request, so new media discovered under those folders is included automatically. Scene Studio supports dynamic folder slideshow layers and adding a folder's current contents as individual static layers (40-layer scene limit). File pickers display relative folder paths. Legacy playlists remain compatible.


### Android reverse-proxy HTTPS pairing diagnostics (v0.4.8)
Android now displays TLS, DNS, timeout, HTTP status and reverse-proxy redirect details instead of `Error: null`. POST redirects are not silently followed (which can lose the request body). For external HTTPS pairing, configure `PUBLIC_URL=https://your.domain` on the server, use a publicly trusted full-chain certificate, and ensure the reverse proxy forwards `/api/*` without redirecting POST requests. Do not disable Android certificate verification.

## v0.5.0 — Multi-user access (security preview)

**Back up `/app/data` before upgrading.** The server creates a one-time SQLite snapshot at
`/app/data/app.sqlite3.before-multiuser-v050.bak` before applying the additive migration.
The existing local administrator, sessions, scenes, playlists and paired devices are retained;
legacy content is assigned to the existing administrator. New scenes and playlists are private.

### Accounts and permissions

The **Users & access** dashboard tab is available to administrators. Administrators can create
local accounts, enable/disable accounts, assign `admin` or `user` roles, and override each
user's permissions. Admins can view and manage all content. Regular users see their own
scenes, playlists and devices, plus scenes/playlists explicitly shared with them.

To share a saved scene or playlist, open it and click **Share**. Enter the recipient's user
ID; `*` shares with all authenticated users. Choose whether to allow editing. Sharing
requires the `sharing.manage` permission and ownership (or admin role).

Default regular-user permissions: media view/upload, scene and playlist creation,
device pairing, and sharing. Media library is shared among users; media deletion and folder
management are restricted by separate permissions. Disable `media.upload` if users should
only consume shared assets.

### OpenID Connect

Configure the container with:

```yaml
services:
  open-wallpaper:
    environment:
      - PUBLIC_URL=https://live-wallpaper.thelinclan.com
      - OIDC_ISSUER=https://auth.example.com/application/o/open-wallpaper/
      - OIDC_CLIENT_ID=your-client-id
      - OIDC_CLIENT_SECRET=your-client-secret
      - OIDC_AUTO_PROVISION=1
```

Register `https://live-wallpaper.thelinclan.com/api/oidc/callback` as the provider's
**exact redirect URI**. The issuer must match the provider's discovery document issuer,
and its endpoints must use HTTPS. This uses the authorization-code flow with PKCE,
server-side state and nonce, provider JWKS validation and issuer/audience checks.
`OIDC_AUTO_PROVISION=1` creates new OIDC users with the regular-user role. Leave it unset
to allow only pre-linked accounts. Admins can pre-link a local user via
`PATCH /api/users/{id}` with `oidc_issuer` and `oidc_sub` matching the provider's
subject identifier; **never guess or use email as the subject**. Local administrator
login remains available for recovery. This release supports one OIDC issuer.

**Important:** Do not put this behind a public hostname until you have tested user isolation,
provider configuration and your proxy. This release has automated smoke tests but has
not undergone an independent security audit or production OIDC integration test.

## v0.5.1 — Folder access controls (security preview)

Administrators can configure folder-specific user permissions under **Users & access → Folder access**. Regular users have no access to folders until explicitly granted. The six permissions are `view`, `use`, `upload`, `edit`, `delete`, and `manage`. Grants inherit to subfolders; an explicit child grant overrides the inherited rights. A parent of an accessible child can appear as a navigation-only container without exposing its files. Administrators retain full access.

Folder restrictions are enforced on media/folder listings, file retrieval, uploads, moves, deletion, scene and playlist creation, playlist expansion, and Android device media/config endpoints. Unauthorized direct media requests return 404. The server creates the `folder_grants` table automatically and does not delete existing media. **Back up the database before deploying.** Test access with a non-administrator account and an already paired Android device before exposing the instance publicly.

**Compatibility note:** The server denies access to unfiled/root media for regular users; move such files into a folder and grant access to that folder. This release is not independently security-audited.
