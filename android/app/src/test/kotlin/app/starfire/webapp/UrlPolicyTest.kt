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
}
