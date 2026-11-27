import java.util.Properties

plugins {
    id("com.android.application")
    kotlin("android")
}

val appKey = "spotmp3"
val appLabel = "SpotMP3"
val exampleUrl = "https://spotmp3.example.com"

val privateAddressFile = rootProject.file("private-address.properties")
val hasPrivateAddress = privateAddressFile.exists()
val safeAddressText = Regex("[A-Za-z0-9.,:/_~%+=&?#@ -]*")

fun loadPrivateAddress(): Pair<String, String> {
    if (!hasPrivateAddress) return "" to ""
    val properties = Properties().apply { privateAddressFile.inputStream().use { load(it) } }
    val url = properties.getProperty("url", "").trim()
    val extraHosts = properties.getProperty("extraHosts", "").trim()
    if (!url.startsWith("https://")) {
        throw GradleException("${privateAddressFile.name} needs a line like url=https://$appKey.example.com/ (see private-address.example.properties)")
    }
    if (!safeAddressText.matches(url) || !safeAddressText.matches(extraHosts)) {
        throw GradleException("${privateAddressFile.name} contains characters that are not allowed in an address")
    }
    return url to extraHosts
}

val (privateUrl, privateExtraHosts) = loadPrivateAddress()

val homeDirectory = File(System.getProperty("user.home"))
val keystoreFile = System.getenv("STARFIRE_KEYSTORE")?.let(::File) ?: File(homeDirectory, ".starfire-$appKey-release.jks")
val keystorePassword = System.getenv("STARFIRE_KEYSTORE_PASSWORD")
    ?: File(homeDirectory, ".starfire-$appKey-release.pass").takeIf { it.exists() }?.readText()?.trim()
val keystoreAlias = System.getenv("STARFIRE_KEY_ALIAS") ?: "starfire-$appKey"
val hasReleaseKey = keystoreFile.exists() && keystorePassword != null
val allowDebugSigning = project.hasProperty("allowDebugSigning")
val releaseArtifactTask = Regex("^(assemble|package|bundle|sign|install)\\w*Release(?!Classes|Resources|Assets|JniLibs)\\w*$")

android {
    namespace = "app.starfire.webapp"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.starfire.$appKey"
        minSdk = 29
        targetSdk = 35
        versionCode = 4
        versionName = "1.1.2"
        buildConfigField("String", "EXAMPLE_URL", "\"$exampleUrl\"")
        resValue("string", "app_name", appLabel)
    }

    flavorDimensions += "edition"
    productFlavors {
        create("public") {
            dimension = "edition"
            buildConfigField("String", "DEFAULT_URL", "\"\"")
            buildConfigField("String", "DEFAULT_EXTRA_HOSTS", "\"\"")
        }
        create("private") {
            dimension = "edition"
            applicationIdSuffix = ".private"
            buildConfigField("String", "DEFAULT_URL", "\"$privateUrl\"")
            buildConfigField("String", "DEFAULT_EXTRA_HOSTS", "\"$privateExtraHosts\"")
        }
    }

    signingConfigs {
        create("starfire") {
            if (hasReleaseKey) {
                storeFile = keystoreFile
                storePassword = keystorePassword
                keyAlias = keystoreAlias
                keyPassword = keystorePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            signingConfig = when {
                hasReleaseKey -> signingConfigs.getByName("starfire")
                allowDebugSigning -> signingConfigs.getByName("debug")
                else -> null
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf("META-INF/versions/**", "META-INF/*.kotlin_module", "META-INF/LICENSE*", "META-INF/DEPENDENCIES")
    }
}

gradle.taskGraph.whenReady {
    val buildsRelease = allTasks.any { releaseArtifactTask.matches(it.name) }
    if (buildsRelease && !hasReleaseKey && !allowDebugSigning) {
        throw GradleException(
            "No release key found for $appKey. Provide ${keystoreFile.path} and its .pass file, set STARFIRE_KEYSTORE and STARFIRE_KEYSTORE_PASSWORD, or pass -PallowDebugSigning to sign with the debug key."
        )
    }
    if (buildsRelease && !hasReleaseKey) logger.lifecycle("Signing the release build with the debug key because -PallowDebugSigning was given")
}

androidComponents {
    beforeVariants(selector().withFlavor("edition" to "private")) { variant ->
        if (!hasPrivateAddress) {
            variant.enable = false
            logger.lifecycle("Private edition skipped: create private-address.properties from private-address.example.properties to enable it")
        }
    }
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    testImplementation(kotlin("test"))
    testImplementation("junit:junit:4.13.2")
}
