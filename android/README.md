# Open Wallpaper Android client (prototype)

Android 10+ Kotlin app implementing `WallpaperService` and connecting to the **v0.3.0 server API**.

## Build an APK

1. Open the `android/` directory in Android Studio (with Android SDK 35 installed).
2. Allow Gradle to sync, then choose **Build → Build APK(s)**.
3. APK output: `app/build/outputs/apk/debug/app-debug.apk`.

Alternatively, with a local Gradle installation and SDK: `gradle assembleDebug`.

## Use

1. Start the server; open the app and enter the server URL (e.g. `http://192.168.1.20:8080`, **not** `localhost`).
2. Tap **Connect and get pairing code**.
3. Sign into the server dashboard, open Devices and approve the pairing code.
4. Tap **Check pairing approval** in the Android app, then **Sync assigned scene** after assigning a scene on the server.
5. Tap **Set live wallpaper**.

## Supported / limitations

- Supports still image layers (cover fit, z-order and opacity) and a clock overlay. Images are decoded each draw; this is a simple first prototype, not an optimized renderer.
- Supports **one looping video layer** per scene, but does not composite additional image/clock layers on top of the video.
- GIFs display as still frames. HTML/web layers and playlists are not supported by this client yet.
- Sync while visible every 60 seconds; media downloaded to app-private cache; downloaded scenes continue offline.
- The app deliberately accepts cleartext HTTP for **trusted local-network testing**. Do not expose the server directly to the public Internet without HTTPS and hardening.
- Pairing codes expire after 10 minutes; the client currently requires tapping **Check pairing approval** after approval.
- Unoptimized Canvas redraw may consume memory/CPU with large image files; performance testing is required.
- This source is **not a compiled APK**. A GitHub Actions workflow can compile a debug APK automatically.
