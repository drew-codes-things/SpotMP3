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
        URI(encodeIllegalCharacters(url))
    } catch (invalid: java.net.URISyntaxException) {
        null
    }

    private fun encodeIllegalCharacters(url: String): String {
        val authorityStart = url.indexOf(AUTHORITY_MARKER).takeIf { it >= 0 }?.plus(AUTHORITY_MARKER.length) ?: return url
        val authorityEnd = url.indexOfAny(AUTHORITY_END, authorityStart).takeIf { it >= 0 } ?: return url
        val rest = buildString { url.substring(authorityEnd).forEach { append(if (it in ILLEGAL) "%%%02X".format(it.code) else it) } }
        return url.substring(0, authorityEnd) + rest
    }

    private companion object {
        const val HTTPS = "https"
        const val AUTHORITY_MARKER = "://"
        val AUTHORITY_END = charArrayOf('/', '?', '#')
        val ILLEGAL = setOf('|', '{', '}', '^', '`', '\\', '[', ']', '"', '<', '>', ' ')
        val EXTERNAL_SCHEMES = setOf("http", "https", "mailto", "tel")
    }
}
