package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AddressValidatorTest {
    private fun valid(input: String) = AddressValidator.validate(input) as AddressResult.Valid

    private fun problem(input: String) = (AddressValidator.validate(input) as AddressResult.Invalid).problem

    @Test
    fun httpsAddressIsNormalised() {
        val result = valid("  HTTPS://Photos.Example.com  ")
        assertEquals("https://photos.example.com/", result.url)
        assertEquals("photos.example.com", result.host)
    }

    @Test
    fun missingSchemeDefaultsToHttps() {
        assertEquals("https://photos.example.com/", valid("photos.example.com").url)
    }

    @Test
    fun portAndPathAreKeptAndQueryIsDropped() {
        assertEquals("https://photos.example.com:8443/app", valid("https://photos.example.com:8443/app?x=1#top").url)
    }

    @Test
    fun emptyInputIsRejected() {
        assertEquals(AddressProblem.EMPTY, problem("   "))
    }

    @Test
    fun plainHttpIsRejectedEvenForLocalAddresses() {
        assertEquals(AddressProblem.NOT_HTTPS, problem("http://photos.example.com"))
        assertEquals(AddressProblem.NOT_HTTPS, problem("http://localhost:8080"))
        assertEquals(AddressProblem.NOT_HTTPS, problem("http://10.0.0.5"))
    }

    @Test
    fun otherSchemesAreRejected() {
        assertEquals(AddressProblem.NOT_HTTPS, problem("ftp://photos.example.com"))
        assertEquals(AddressProblem.NOT_HTTPS, problem("file:///etc/passwd"))
        assertEquals(AddressProblem.NOT_A_URL, problem("javascript:alert(1)"))
    }

    @Test
    fun credentialsInTheAddressAreRejected() {
        assertEquals(AddressProblem.HAS_CREDENTIALS, problem("https://user:secret@photos.example.com"))
        assertEquals(AddressProblem.HAS_CREDENTIALS, problem("https://user@photos.example.com"))
    }

    @Test
    fun hostMustBeARealName() {
        assertEquals(AddressProblem.NO_HOST, problem("https://"))
        assertEquals(AddressProblem.BAD_HOST, problem("https://localhost"))
        assertEquals(AddressProblem.BAD_HOST, problem("https://198.51.100.4"))
        assertEquals(AddressProblem.BAD_HOST, problem("https://[::1]"))
        assertEquals(AddressProblem.BAD_HOST, problem("https://-bad.example.com"))
        assertEquals(AddressProblem.BAD_HOST, problem("https://photos_x.example.com"))
    }

    @Test
    fun garbageIsRejected() {
        assertEquals(AddressProblem.NOT_A_URL, problem("not a url"))
        assertEquals(AddressProblem.NOT_A_URL, problem("https://exa mple.com"))
        assertEquals(AddressProblem.NOT_A_URL, problem("https://photos.example.com:99999999999"))
    }

    @Test
    fun extraHostsAcceptNamesAndAddressesSeparatedByCommasOrSpaces() {
        val result = AddressValidator.parseExtraHosts("Files.Example.com, https://cdn.example.com/x\nfiles.example.com") as ExtraHostsResult.Valid
        assertEquals(listOf("files.example.com", "cdn.example.com"), result.hosts)
    }

    @Test
    fun emptyExtraHostsAreAllowed() {
        assertEquals(ExtraHostsResult.Valid(emptyList()), AddressValidator.parseExtraHosts("  "))
    }

    @Test
    fun badExtraHostNamesTheEntry() {
        val result = AddressValidator.parseExtraHosts("files.example.com, http://cdn.example.com") as ExtraHostsResult.Invalid
        assertEquals("http://cdn.example.com", result.entry)
        assertEquals(AddressProblem.NOT_HTTPS, result.problem)
    }

    @Test
    fun allowListIsConfiguredHostPlusExtras() {
        val hosts = AddressValidator.allowedHosts("https://drive.example.com/", listOf("files.example.com"))
        assertEquals(setOf("drive.example.com", "files.example.com"), hosts)
        assertTrue("evil.example.com" !in hosts)
    }

    @Test
    fun allowListWithoutExtrasIsTheConfiguredHostOnly() {
        assertEquals(setOf("photos.example.com"), AddressValidator.allowedHosts("https://photos.example.com:8443/a/", emptyList()))
    }

    @Test
    fun slashIsOnlyAddedToAnEmptyPath() {
        assertEquals("https://photos.example.com/index.html", valid("https://photos.example.com/index.html").url)
        assertEquals("https://photos.example.com/app/index.php", valid("https://photos.example.com/app/index.php?x=1").url)
        assertEquals("https://photos.example.com/", valid("https://photos.example.com").url)
        assertEquals("https://photos.example.com/app/", valid("https://photos.example.com/app/").url)
    }
}
