package app.starfire.webapp

import java.net.URI

class UrlPolicy(allowedHosts: Set<String>) {
    private val hosts = allowedHosts.map { it.lowercase() }.toSet()

    fun staysInApp(url: String): Boolean {
        val parsed = parse(url) ?: return false
        return parsed.scheme.equals(HTTPS, ignoreCase = true) && parsed.host?.lowercase() in hosts
    }

    fun opensExternally(url: String): Boolean {
        val scheme = parse(url)?.scheme?.lowercase() ?: return false
        return scheme in EXTERNAL_SCHEMES
    }

    private fun parse(url: String): URI? = try {
        URI(url)
    } catch (invalid: java.net.URISyntaxException) {
        null
    }

    private companion object {
        const val HTTPS = "https"
        val EXTERNAL_SCHEMES = setOf("http", "https", "mailto", "tel")
    }
}
