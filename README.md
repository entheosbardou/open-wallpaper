# Open Wallpaper

Self-hosted wallpaper server and experimental Android live wallpaper client. Open Wallpaper uses MySQL 8.4 as its only database and stores uploaded media separately in a persistent Docker volume.

## Clean MySQL installation

1. Install Docker Compose.
2. Copy `.env.example` to `.env` and set strong, unique values for `DB_PASSWORD` and `MYSQL_ROOT_PASSWORD`.
3. Choose the server image:

   To use the published GHCR image, start the stack:

   ```sh
   docker compose up -d
   ```

   To build from this checkout for local testing, use the build overlay:

   ```sh
   docker compose -f compose.yaml -f compose.build.yaml up -d --build
   ```

4. Open <http://localhost:8080> and create the administrator account.

The Compose stack creates a MySQL database named `open_wallpaper` and persists it in the `wallpaper-mysql` volume. Application media is stored in `wallpaper-data`. Back up both volumes before changing or removing them. `docker compose down -v` deletes the database and media volumes.

**This is a clean installation. Existing SQLite data will not carry over. No SQLite import or conversion is provided.** Media files placed under `/app/data/media` are indexed by the new server, but scenes, playlists, user accounts, sharing, permissions, and paired-device records must be recreated.

## Configuration

Database settings are provided by Compose using `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. The defaults in `compose.yaml` connect the application to the MySQL service. Set the two passwords in `.env`; Compose refuses to start when they are missing.

Optional application variables include `PUBLIC_URL` for external pairing links and the existing OIDC settings below. The Gallery integration is separately enabled with a Compose overlay.

## Accounts and access

The **Users & access** dashboard tab is available to administrators. Administrators can create local accounts, enable or disable accounts, assign `admin` or `user` roles, and override user permissions. Regular users see their own scenes, playlists, and devices, plus scenes and playlists explicitly shared with them.

To share a saved scene or playlist, open it and select **Share**. Enter the recipient's user ID; `*` shares with all authenticated users. Choose whether to allow editing. Sharing requires the `sharing.manage` permission and ownership (or administrator role).

Default regular-user permissions: media view/upload, scene and playlist creation, device pairing, and sharing. Media deletion and folder management use separate permissions.

Administrators can grant folder-specific `view`, `use`, `upload`, `edit`, `delete`, and `manage` permissions. Grants inherit to subfolders; an explicit child grant overrides inherited rights. A parent of an accessible child can appear as a navigation-only container without exposing its files. Folder restrictions apply to listings, searches, direct media requests, uploads, moves, deletion, playlist expansion, and Android device endpoints. Unauthorized direct media requests return 404.

## OpenID Connect

Configure the server service in Compose:

```yaml
environment:
  PUBLIC_URL: https://live-wallpaper.example.com
  OIDC_ISSUER: https://auth.example.com/application/o/open-wallpaper/
  OIDC_CLIENT_ID: your-client-id
  OIDC_CLIENT_SECRET: your-client-secret
  OIDC_AUTO_PROVISION: "1"
  OIDC_ADMIN_GROUPS: open-wallpaper-admins
```

Register `https://live-wallpaper.example.com/api/oidc/callback` as the provider's exact redirect URI. The issuer must match its discovery document issuer, and OIDC endpoints must use HTTPS. The authorization-code flow uses PKCE, server-side state and nonce, provider JWKS validation, and issuer/audience checks. `OIDC_AUTO_PROVISION=1` creates accounts using the OIDC `preferred_username` claim (falling back to the email name); existing auto-generated OIDC usernames are updated on the next sign-in when the name is available and unused. `OIDC_ADMIN_GROUPS` is a comma-separated list of OIDC `groups` claim values that control app admin role; the default is `open-wallpaper-admins`. On each OIDC sign-in, membership grants admin and absence from the configured groups demotes the account to regular user. Configure Authentik to include the `groups` claim in the ID token. Otherwise, an administrator must pre-link accounts. Local administrator login remains available for recovery.

## Optional Gallery media

Gallery integration is disabled unless the `compose.gallery.yaml` overlay is used. It does not change the behavior or storage of Open Wallpaper's local media.

1. In `.env`, set `GALLERY_API_URL` to Gallery's HTTPS origin, `GALLERY_CLIENT_INSTANCE` to a unique stable ID for this Open Wallpaper installation, and `GALLERY_MEDIA_SOURCE` to the host directory whose paths mirror Gallery's `relative_path` values. Also set the OIDC variables and `PUBLIC_URL`.
2. Use the same OIDC client ID and secret in Open Wallpaper and Gallery's external-media configuration. The identity provider must issue refresh tokens and include Gallery's `gallery_groups` claim in refreshed ID tokens. Open Wallpaper requests `offline_access` only when the Gallery overlay is enabled.
3. Generate a Fernet key (for example, `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) and set it as `GALLERY_TOKEN_ENCRYPTION_KEY`. Keep this key stable and private; Open Wallpaper encrypts Gallery refresh tokens and device grants in its MySQL database with it. Losing or changing the key makes those stored credentials unreadable and requires users to sign in again and reassign Gallery media.
4. Start the stack with `docker compose -f compose.yaml -f compose.gallery.yaml up -d` (add `-f compose.build.yaml` when building from this checkout). The Gallery files are mounted read-only at `/app/data/external/gallery`, separately from `/app/data/media`.

When a user signs in through OIDC, Open Wallpaper stores that user's encrypted refresh token. Assigning a scene or playlist containing Gallery items creates a separate Gallery grant for the paired device. If the assigned scene or playlist later changes, the grant is refreshed at the next device check-in. The device receives only its Open Wallpaper device token. Gallery media is rechecked when the device syncs; items Gallery denies are omitted individually and the remaining scene or playlist continues. Confirmed denials remain excluded through Gallery outages and server restarts. If Gallery is unavailable, the device keeps other assigned Gallery references and uses cached files, while new Gallery downloads fail; local media can still sync. Reconnect the device after an outage to refresh its assignment and authorization. A device grant is limited to 500 Gallery files.

Gallery-backed items use provider-qualified IDs and are read-only in Open Wallpaper. The Gallery mount is never indexed, uploaded to, moved, or deleted by Open Wallpaper. The integration uses Gallery's API and does not connect to Gallery's MySQL database. Open Wallpaper creates two additive tables, `gallery_user_credentials` and `gallery_device_grants` (including the last-known denied file IDs), on application startup; existing user, device, scene, playlist, and media rows are not transformed. Back up the Open Wallpaper database before enabling the integration on an existing installation.

The dashboard shows Gallery items under nested Gallery collections, then category folders within each collection. In the library folder picker, hover over a collection to open its child menu and click its name to show that collection. The scene and playlist media pickers use expandable folders. Gallery collections and categories are read-only. Open Wallpaper expects Gallery’s `/api/external/collections` response to include `categories`, an object mapping each collection key to an array of accessible category names (for example, `{"anime":["sfw","nsfw"]}`). It displays those folders before loading images. Selecting a category requests `/api/external/media?collection=<key>&category=<name>` so Gallery must filter the catalog by both values. Images load 250 at a time; use **Load more Gallery media** for later pages. Uploads still go to Open Wallpaper's local media library.

## Media library

Place images or videos in the persistent application volume under `media/`, including nested directories. Supported files are indexed on media and folder API requests. Folder moves, renames, and deletion update the on-disk media paths.

## Limitations

- Android video uses a dedicated playback surface and cannot composite clock/image layers over video yet.
- Playlist changes are polled about once a minute while the wallpaper is visible.
- Browser preview of playlist layers displays the first item and does not automatically rotate.
- No native Windows/Linux client or arbitrary HTML/JS scene renderer is available yet.
- Debug APK builds are not signed for production distribution.
- This release has not undergone an independent security audit.

## GitHub workflows

- `.github/workflows/android-apk.yml` builds a debug APK artifact.
- `.github/workflows/docker-publish.yml` publishes multi-architecture container images.
