plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
 namespace = "org.openwallpaper.client"
 compileSdk = 35
 defaultConfig { applicationId = "org.openwallpaper.client"; minSdk = 29; targetSdk = 35; versionCode = 1; versionName = "0.1.0" }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
}
