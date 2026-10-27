plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Installation-specific values (app id, server addresses) come in as Gradle properties.
fun prop(name: String, fallback: String = ""): String =
    (project.findProperty(name) as String?) ?: fallback

// The LAN host is the only one allowed over plain HTTP.
val networkRes = layout.buildDirectory.dir("generated/vsres")
val writeNetworkConfig by tasks.registering {
    val host = prop("vsLanHost", "localhost")
    val out = networkRes
    inputs.property("host", host)
    outputs.dir(out)
    doLast {
        val file = out.get().file("xml/network_security.xml").asFile
        file.parentFile.mkdirs()
        file.writeText(
            """<?xml version="1.0" encoding="utf-8"?>
            |<network-security-config>
            |    <domain-config cleartextTrafficPermitted="true">
            |        <domain includeSubdomains="false">$host</domain>
            |    </domain-config>
            |</network-security-config>
            |""".trimMargin()
        )
    }
}
tasks.named("preBuild") { dependsOn(writeNetworkConfig) }

android {
    sourceSets["main"].res.srcDir(networkRes)
    namespace = "xyz.vibestream.app"
    compileSdk = 35

    defaultConfig {
        applicationId = prop("vsAppId", "xyz.vibestream.app")
        minSdk = 29
        targetSdk = 35
        versionCode = prop("vsBuild", "1").toInt()
        versionName = "1.0"
        buildConfigField("String", "PUBLIC_URL", "\"${prop("vsPublicUrl")}\"")
        buildConfigField("String", "LAN_URL", "\"${prop("vsLanUrl")}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.core.ktx)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.runtime)
    implementation(libs.lifecycle.process)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.navigation.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    debugImplementation(libs.compose.tooling)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.hls)
    implementation(libs.media3.ui)
    implementation(libs.media3.okhttp)
    implementation(libs.media3.transformer)
    implementation(libs.media3.effect)
    implementation(libs.coil.compose)
    implementation(libs.coil.okhttp)
    implementation(libs.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coroutines.android)
}
