package app.starfire.webapp

import java.net.URI

object DownloadPolicy {
    const val MAX_BYTES = 200L * 1024 * 1024
    const val FALLBACK_FILE_NAME = "download"
    const val FALLBACK_MIME_TYPE = "application/octet-stream"
    private const val MAX_FILE_NAME_LENGTH = 120
    private const val MAX_EXTENSION_LENGTH = 10
    private const val NO_PORT = -1
    private const val DEFAULT_HTTPS_PORT = 443
    private const val DEFAULT_PORT_SUFFIX = ":443"
    private const val REPLACEMENT = '_'
    private val unsafeFileNameCharacters = setOf('<', '>', ':', '"', '|', '?', '*')
    private val invisibleFormattingCharacters = Regex("[\\u061C\\u200B-\\u200F\\u202A-\\u202E\\u2060-\\u2064\\u2066-\\u2069\\uFEFF]")
    private val mimeToken = "[a-z0-9][a-z0-9!#$&^_.+-]*"
    private val mimeType = Regex("$mimeToken/$mimeToken")

    fun isWithinLimit(bytes: Long): Boolean = bytes in 0..MAX_BYTES

    fun sanitizeFileName(raw: String?): String {
        val lastSegment = invisibleFormattingCharacters.replace(raw.orEmpty(), "").substringAfterLast('/').substringAfterLast('\\')
        val replaced = lastSegment.map { if (it.isISOControl() || it in unsafeFileNameCharacters) REPLACEMENT else it }
        val cleaned = String(replaced.toCharArray()).trim().trimStart('.').trim()
        if (cleaned.isEmpty()) return FALLBACK_FILE_NAME
        return shorten(cleaned)
    }

    fun sanitizeMimeType(raw: String?): String {
        val candidate = raw.orEmpty().substringBefore(';').trim().lowercase()
        return if (mimeType.matches(candidate)) candidate else FALLBACK_MIME_TYPE
    }

    fun originRules(startUrl: String, extraHosts: List<String>): Set<String> {
        val uri = try {
            URI(startUrl)
        } catch (invalid: java.net.URISyntaxException) {
            return emptySet()
        }
        val host = uri.host ?: return emptySet()
        val port = if (uri.port == NO_PORT || uri.port == DEFAULT_HTTPS_PORT) "" else ":${uri.port}"
        return linkedSetOf("https://${host.lowercase()}$port").apply { extraHosts.forEach { add("https://${it.lowercase()}") } }
    }

    fun isAllowedOrigin(origin: String, rules: Set<String>): Boolean = withoutDefaultPort(origin) in rules.map(::withoutDefaultPort)

    private fun withoutDefaultPort(origin: String) = origin.lowercase().removeSuffix(DEFAULT_PORT_SUFFIX)

    private fun shorten(name: String): String {
        if (name.length <= MAX_FILE_NAME_LENGTH) return name
        val extension = name.substringAfterLast('.', "").takeIf { it.length in 1..MAX_EXTENSION_LENGTH }?.let { ".$it" }.orEmpty()
        return name.substring(0, name.length - extension.length).take(MAX_FILE_NAME_LENGTH - extension.length) + extension
    }
}
