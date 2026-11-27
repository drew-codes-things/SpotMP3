package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class UrlPolicyTest {
    private val policy = UrlPolicy(setOf("drive.example.test", "files.example.test"))

    @Test
    fun allowedHostsStayInApp() {
        assertTrue(policy.staysInApp("https://drive.example.test/signin/"))
        assertTrue(policy.staysInApp("https://FILES.example.test/a"))
    }

    @Test
    fun otherHostsLeaveTheApp() {
        assertFalse(policy.staysInApp("https://evil.example.test/"))
        assertFalse(policy.staysInApp("https://drive.example.test.evil.test/"))
        assertFalse(policy.staysInApp("https://evil.test/@drive.example.test"))
    }

    @Test
    fun plainHttpAndOtherSchemesNeverStayInApp() {
        assertFalse(policy.staysInApp("http://drive.example.test/"))
        assertFalse(policy.staysInApp("javascript:alert(1)"))
        assertFalse(policy.staysInApp("intent://drive.example.test#Intent;end"))
        assertFalse(policy.staysInApp("not a url"))
    }

    @Test
    fun onlyWebAndContactSchemesOpenExternally() {
        assertTrue(policy.opensExternally("https://evil.test/"))
        assertTrue(policy.opensExternally("mailto:a@b.test"))
        assertTrue(policy.opensExternally("tel:123"))
        assertFalse(policy.opensExternally("intent://x#Intent;end"))
        assertFalse(policy.opensExternally("file:///etc/passwd"))
        assertFalse(policy.opensExternally("javascript:alert(1)"))
    }

    @Test
    fun emptyAllowListKeepsEverythingOutOfTheApp() {
        assertFalse(UrlPolicy(emptySet()).staysInApp("https://drive.example.test/"))
    }

    @Test
    fun charactersJavaUriRejectsAreStillDecidedByHost() {
        val illegal = listOf("|", "{", "}", "^", "`", "\\", "[", "]")
        for (character in illegal) {
            val query = "https://drive.example.test/search?q=a${character}b"
            val fragment = "https://drive.example.test/#/album/${character}id"
            val path = "https://drive.example.test/files/${character}2024/"
            val foreign = "https://other.example.org/article?ids=1${character}2"
            assertTrue(policy.staysInApp(query), "query $character")
            assertTrue(policy.staysInApp(fragment), "fragment $character")
            assertTrue(policy.staysInApp(path), "path $character")
            assertFalse(policy.staysInApp(foreign), "foreign $character")
            assertTrue(policy.opensExternally(foreign), "external $character")
        }
    }

    @Test
    fun illegalCharactersInTheHostPartStillFailClosed() {
        assertFalse(policy.staysInApp("https://evil.test\\@drive.example.test/"))
        assertFalse(policy.staysInApp("https://drive.example.test\\@evil.test/"))
    }

    @Test
    fun malformedPercentSignsAndExtraHashesAreStillDecidedByHost() {
        assertTrue(policy.staysInApp("https://drive.example.test/%zz|"))
        assertTrue(policy.staysInApp("https://drive.example.test/search?q=50%"))
        assertTrue(policy.staysInApp("https://drive.example.test/#a#b"))
        assertFalse(policy.staysInApp("https://other.example.org/#a#b"))
        assertTrue(policy.opensExternally("https://other.example.org/#a#b"))
        assertTrue(policy.opensExternally("https://other.example.org/%zz"))
    }

    @Test
    fun mailAndPhoneLinksWithIllegalCharactersStillOpenExternally() {
        assertTrue(policy.opensExternally("mailto:a@b.test?subject=a|b"))
        assertTrue(policy.opensExternally("tel:+44|1"))
        assertFalse(policy.staysInApp("mailto:a@b.test?subject=a|b"))
    }

    @Test
    fun validPercentEncodingIsLeftAlone() {
        assertTrue(policy.staysInApp("https://drive.example.test/a%20b?x=%7C"))
    }
}
