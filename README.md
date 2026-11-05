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

**This is a clean installation. Existing SQLite data will not carry over. No database import, conversion, or migration is provided.** Media files placed under `/app/data/media` are indexed by the new server, but scenes, playlists, user accounts, sharing, permissions, and paired-device records must be recreated.

## Configuration

Database settings are provided by Compose using `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. The defaults in `compose.yaml` connect the application to the MySQL service. Set the two passwords in `.env`; Compose refuses to start when they are missing.

Optional application variables include `PUBLIC_URL` for external pairing links and the existing OIDC settings below. OIDC behavior and provider setup are unchanged.

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
