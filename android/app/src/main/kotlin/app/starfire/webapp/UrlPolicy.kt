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
        val tailStart = tailStart(url) ?: return url
        return url.substring(0, tailStart) + encodeTail(url.substring(tailStart))
    }

    private fun tailStart(url: String): Int? {
        val markerAt = url.indexOf(AUTHORITY_MARKER)
        if (markerAt >= 0) return url.indexOfAny(AUTHORITY_END, markerAt + AUTHORITY_MARKER.length).takeIf { it >= 0 }
        return url.indexOf(':').takeIf { it >= 0 }?.plus(1)
    }

    private fun encodeTail(tail: String): String {
        val encoded = StringBuilder()
        var seenHash = false
        tail.forEachIndexed { index, character ->
            val needsEncoding = when (character) {
                '%' -> !hasTwoHexDigitsAt(tail, index + 1)
                '#' -> seenHash.also { seenHash = true }
                else -> character in ILLEGAL
            }
            if (needsEncoding) encoded.append("%%%02X".format(character.code)) else encoded.append(character)
        }
        return encoded.toString()
    }

    private fun hasTwoHexDigitsAt(text: String, start: Int) =
        start + 1 < text.length && text[start].isHexDigit() && text[start + 1].isHexDigit()

    private fun Char.isHexDigit() = this in '0'..'9' || this in 'a'..'f' || this in 'A'..'F'

    private companion object {
        const val HTTPS = "https"
        const val AUTHORITY_MARKER = "://"
        val AUTHORITY_END = charArrayOf('/', '?', '#')
        val ILLEGAL = setOf('|', '{', '}', '^', '`', '\\', '[', ']', '"', '<', '>', ' ')
        val EXTERNAL_SCHEMES = setOf("http", "https", "mailto", "tel")
    }
}
