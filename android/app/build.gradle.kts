plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
 namespace = "org.openwallpaper.client"
 compileSdk = 35
 defaultConfig { applicationId = "org.openwallpaper.client"; minSdk = 29; targetSdk = 35; versionCode = 3; versionName = "0.4.2" }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
	implementation("androidx.core:core:1.13.1")
}
