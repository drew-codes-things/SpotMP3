package app.starfire.webapp

sealed interface DownloadMessage {
    val id: Int

    data class Start(override val id: Int, val declaredBytes: Long, val mimeType: String, val fileName: String) : DownloadMessage
    data class Chunk(override val id: Int, val base64: String) : DownloadMessage
    data class End(override val id: Int) : DownloadMessage
    data class Abort(override val id: Int) : DownloadMessage
    data class Invalid(override val id: Int) : DownloadMessage

    companion object {
        const val MAX_CHUNK_CHARS = 400_000
        private const val SEPARATOR = '\n'
        private const val START = 'S'
        private const val CHUNK = 'C'
        private const val END = 'E'
        private const val ABORT = 'X'
        private const val START_FIELDS = 4
        private const val CHUNK_FIELDS = 2
        private val base64Text = Regex("[A-Za-z0-9+/]*={0,2}")

        fun parse(text: String): DownloadMessage? {
            if (text.length < 2 || text[1] != SEPARATOR) return null
            val body = text.substring(2)
            return when (text[0]) {
                START -> parseStart(body)
                CHUNK -> parseChunk(body)
                END -> body.toIntOrNull()?.let(::End)
                ABORT -> body.toIntOrNull()?.let(::Abort)
                else -> null
            }
        }

        private fun parseStart(body: String): DownloadMessage? {
            val parts = body.split(SEPARATOR, limit = START_FIELDS)
            val id = parts[0].toIntOrNull() ?: return null
            val declaredBytes = parts.getOrNull(1)?.toLongOrNull()
            if (parts.size < START_FIELDS || declaredBytes == null) return Invalid(id)
            return Start(id, declaredBytes, parts[2], parts[3])
        }

        private fun parseChunk(body: String): DownloadMessage? {
            val parts = body.split(SEPARATOR, limit = CHUNK_FIELDS)
            val id = parts[0].toIntOrNull() ?: return null
            val payload = parts.getOrNull(1) ?: return Invalid(id)
            if (payload.length > MAX_CHUNK_CHARS || !base64Text.matches(payload)) return Invalid(id)
            return Chunk(id, payload)
        }
    }
}
