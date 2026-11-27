package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DownloadPolicyTest {
    @Test
    fun sizeLimitIsTwoHundredMegabytes() {
        assertEquals(200L * 1024 * 1024, DownloadPolicy.MAX_BYTES)
        assertTrue(DownloadPolicy.isWithinLimit(0))
        assertTrue(DownloadPolicy.isWithinLimit(DownloadPolicy.MAX_BYTES))
        assertFalse(DownloadPolicy.isWithinLimit(DownloadPolicy.MAX_BYTES + 1))
        assertFalse(DownloadPolicy.isWithinLimit(-1))
    }

    @Test
    fun pathPartsAreRemovedFromFileNames() {
        assertEquals("passwd", DownloadPolicy.sanitizeFileName("../../etc/passwd"))
        assertEquals("c.txt", DownloadPolicy.sanitizeFileName("a/b\\c.txt"))
        assertEquals("map.zip", DownloadPolicy.sanitizeFileName("/sdcard/Download/map.zip"))
    }

    @Test
    fun unsafeCharactersAreReplaced() {
        assertEquals("a_b_c_.zip", DownloadPolicy.sanitizeFileName("a<b>c?.zip"))
        assertEquals("tab_name.txt", DownloadPolicy.sanitizeFileName("tab\tname.txt"))
        assertEquals("nul_x.bin", DownloadPolicy.sanitizeFileName("nul\u0000x.bin"))
        assertEquals("quote_.txt", DownloadPolicy.sanitizeFileName("quote\".txt"))
    }

    @Test
    fun leadingDotsAndSpacesAreStripped() {
        assertEquals("hidden", DownloadPolicy.sanitizeFileName("..hidden"))
        assertEquals("name.txt", DownloadPolicy.sanitizeFileName("  name.txt  "))
    }

    @Test
    fun emptyOrBlankNamesFallBack() {
        assertEquals(DownloadPolicy.FALLBACK_FILE_NAME, DownloadPolicy.sanitizeFileName(null))
        assertEquals(DownloadPolicy.FALLBACK_FILE_NAME, DownloadPolicy.sanitizeFileName(""))
        assertEquals(DownloadPolicy.FALLBACK_FILE_NAME, DownloadPolicy.sanitizeFileName("../"))
        assertEquals(DownloadPolicy.FALLBACK_FILE_NAME, DownloadPolicy.sanitizeFileName("..."))
    }

    @Test
    fun longNamesAreShortenedAndKeepTheirExtension() {
        val result = DownloadPolicy.sanitizeFileName("x".repeat(300) + ".zip")
        assertEquals(120, result.length)
        assertTrue(result.endsWith(".zip"))
    }

    @Test
    fun mimeTypesMustLookLikeMimeTypes() {
        assertEquals("application/zip", DownloadPolicy.sanitizeMimeType("Application/Zip"))
        assertEquals("audio/ogg", DownloadPolicy.sanitizeMimeType("audio/ogg; codecs=vorbis"))
        assertEquals(DownloadPolicy.FALLBACK_MIME_TYPE, DownloadPolicy.sanitizeMimeType(""))
        assertEquals(DownloadPolicy.FALLBACK_MIME_TYPE, DownloadPolicy.sanitizeMimeType("text/html\nx"))
        assertEquals(DownloadPolicy.FALLBACK_MIME_TYPE, DownloadPolicy.sanitizeMimeType("*/*"))
        assertEquals(DownloadPolicy.FALLBACK_MIME_TYPE, DownloadPolicy.sanitizeMimeType(null))
    }

    @Test
    fun originRulesAreTheConfiguredOriginsOnly() {
        val rules = DownloadPolicy.originRules("https://photos.example.com:8443/app/", listOf("files.example.com"))
        assertEquals(setOf("https://photos.example.com:8443", "https://files.example.com"), rules)
        assertFalse("*" in rules)
    }

    @Test
    fun originRulesWithoutPortOrExtras() {
        assertEquals(setOf("https://photos.example.com"), DownloadPolicy.originRules("https://photos.example.com/", emptyList()))
    }

    @Test
    fun onlyListedOriginsAreAccepted() {
        val rules = setOf("https://photos.example.com")
        assertTrue(DownloadPolicy.isAllowedOrigin("https://photos.example.com", rules))
        assertTrue(DownloadPolicy.isAllowedOrigin("HTTPS://Photos.Example.com", rules))
        assertFalse(DownloadPolicy.isAllowedOrigin("https://evil.example.com", rules))
        assertFalse(DownloadPolicy.isAllowedOrigin("http://photos.example.com", rules))
        assertFalse(DownloadPolicy.isAllowedOrigin("null", rules))
        assertFalse(DownloadPolicy.isAllowedOrigin("https://photos.example.com.evil.test", rules))
    }

    @Test
    fun defaultHttpsPortIsDroppedFromRulesAndComparison() {
        val rules = DownloadPolicy.originRules("https://photos.example.com:443/", emptyList())
        assertEquals(setOf("https://photos.example.com"), rules)
        assertTrue(DownloadPolicy.isAllowedOrigin("https://photos.example.com", rules))
        assertTrue(DownloadPolicy.isAllowedOrigin("https://photos.example.com:443", rules))
        assertFalse(DownloadPolicy.isAllowedOrigin("https://photos.example.com:8443", rules))
    }

    @Test
    fun unparseableStartAddressGivesNoRulesInsteadOfCrashing() {
        assertEquals(emptySet(), DownloadPolicy.originRules("https://exa mple.com/", emptyList()))
        assertEquals(emptySet(), DownloadPolicy.originRules("not a url", emptyList()))
    }

    @Test
    fun directionOverridesAndZeroWidthCharactersAreRemovedFromNames() {
        assertEquals("photogpj.apk", DownloadPolicy.sanitizeFileName("photo\u202Egpj.apk"))
        assertEquals("ab.zip", DownloadPolicy.sanitizeFileName("a\u200Bb\u200E.zip"))
        assertEquals("ab.zip", DownloadPolicy.sanitizeFileName("a\u2066b\uFEFF.zip"))
        assertEquals(DownloadPolicy.FALLBACK_FILE_NAME, DownloadPolicy.sanitizeFileName("\u202E\u200B"))
    }
}
