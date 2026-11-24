// The Android app: the desktop app's screens (desktop/renderer) in a WebView, and its Python core
// (shugotracker) running on the phone through Chaquopy. No Nearby: there's no game traffic on a phone.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val versionNameEnv = System.getenv("SHUGO_VERSION") ?: "0.0.0-dev"
// 2.6.10 -> 20610: each release's code is higher than the last, so Android installs it as an update
val versionCodeEnv = versionNameEnv.split(".").mapNotNull { it.toIntOrNull() }.let {
    if (it.size >= 3) it[0] * 10000 + it[1] * 100 + it[2] else 1
}

android {
    namespace = "gg.cynica.shugotracker"
    compileSdk = 34
    defaultConfig {
        applicationId = "gg.cynica.shugotracker"
        minSdk = 26
        targetSdk = 34
        versionCode = versionCodeEnv
        versionName = versionNameEnv
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    signingConfigs {
        // Every release must be signed with the same key, or Android won't install it over the last one.
        // The key lives in the repo (android/shugo-release.jks); ANDROID_KEYSTORE_* can point at another.
        create("release") {
            storeFile = file(System.getenv("ANDROID_KEYSTORE_FILE") ?: "../shugo-release.jks")
            storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD") ?: "shugotracker"
            keyAlias = System.getenv("ANDROID_KEY_ALIAS") ?: "shugo"
            keyPassword = System.getenv("ANDROID_KEY_PASSWORD") ?: "shugotracker"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets["main"].assets.srcDir("build/web")
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip { install("requests") }
        extractPackages("shugotracker")                // (it reads its bundled data files from disk)
    }
    sourceSets { getByName("main") { srcDir("build/python-src") } }
}

dependencies {
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.core:core-ktx:1.13.1")
}

// The same code the desktop app ships, copied in at build time (one source of truth).
val syncPython by tasks.registering(Sync::class) {
    from(rootProject.file("../shugotracker")) { exclude("**/__pycache__/**", "**/*.pyc") }
    into(layout.buildDirectory.dir("python-src/shugotracker"))
}
val syncWeb by tasks.registering(Sync::class) {
    from(rootProject.file("../desktop/renderer"))
    into(layout.buildDirectory.dir("web/www"))
}
tasks.named("preBuild") { dependsOn(syncPython, syncWeb) }
