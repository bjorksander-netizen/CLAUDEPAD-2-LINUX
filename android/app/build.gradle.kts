plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.bjorn.claudepad"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bjorn.claudepad"
        minSdk = 24
        targetSdk = 34
        versionCode = 21
        versionName = "3.7"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Sengaja TIDAK ditandatangani di sini. Penandatanganan ditangani
            // sepenuhnya oleh CI (.github/workflows/build-apk.yml): pakai
            // keystore produksi bila rahasia disetel, selain itu debug keystore
            // CI. Ini menghindari "re-sign" yang rapuh pada APK sudah-tertanda.
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.activity:activity-ktx:1.8.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // Architecture Components — ViewModel + lifecycle-aware StateFlow collection
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")

    // v3.2: Enkripsi penyimpanan token (EncryptedSharedPreferences)
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
}

// Catatan font:
// JetBrains Mono diletakkan di src/main/res/font/jetbrains_mono.ttf.
// Di CI, file itu diunduh oleh workflow sebelum Gradle dijalankan.
// Untuk build lokal, jalankan skrip android/fetch-font.sh (atau .bat),
// atau biarkan kosong — aplikasi otomatis memakai monospace bawaan sistem
// (lihat Fonts.kt), sehingga build tetap berhasil tanpa file font.
