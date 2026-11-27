package app.starfire.webapp

sealed interface DownloadMessage {
    data class Start(val declaredBytes: Long, val mimeType: String, val fileName: String) : DownloadMessage
    data class Chunk(val base64: String) : DownloadMessage
    data object End : DownloadMessage
    data object Abort : DownloadMessage

    companion object {
        const val MAX_CHUNK_CHARS = 400_000
        private const val START = "S\n"
        private const val CHUNK = "C\n"
        private const val END = "E"
        private const val ABORT = "X"
        private const val START_FIELDS = 3
        private val base64Text = Regex("[A-Za-z0-9+/]*={0,2}")

        fun parse(text: String): DownloadMessage? = when {
            text == END -> End
            text == ABORT -> Abort
            text.startsWith(START) -> parseStart(text.removePrefix(START))
            text.startsWith(CHUNK) -> parseChunk(text.removePrefix(CHUNK))
            else -> null
        }

        private fun parseStart(fields: String): DownloadMessage? {
            val parts = fields.split("\n", limit = START_FIELDS)
            if (parts.size < START_FIELDS) return null
            val declaredBytes = parts[0].toLongOrNull() ?: return null
            return Start(declaredBytes, parts[1], parts[2])
        }

        private fun parseChunk(payload: String): DownloadMessage? {
            if (payload.length > MAX_CHUNK_CHARS || !base64Text.matches(payload)) return null
            return Chunk(payload)
        }
    }
}
