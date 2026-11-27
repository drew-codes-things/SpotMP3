package app.starfire.webapp

import java.util.Base64

enum class SaveResult { SAVED, TOO_LARGE, FAILED }

interface StoredDownload {
    fun write(bytes: ByteArray)
    fun publish()
    fun discard()
}

interface DownloadStore {
    fun create(fileName: String, mimeType: String): StoredDownload
}

interface DownloadListener {
    fun onAck(id: Int)
    fun onStop(id: Int)
    fun onFinished(id: Int, fileName: String, result: SaveResult)
}

class DownloadSessions(
    private val store: DownloadStore,
    private val listener: DownloadListener,
    private val maxBytes: Long = DownloadPolicy.MAX_BYTES,
) {
    private class Session(val fileName: String, val declaredBytes: Long, val stored: StoredDownload, var lastActivity: Long) {
        var writtenBytes = 0L
    }

    private val armedAt = HashMap<Int, Long>()
    private val sessions = HashMap<Int, Session>()
    private var nextId = FIRST_ID

    @Synchronized
    fun arm(nowMillis: Long): Int? {
        if (armedAt.size + sessions.size >= MAX_OPEN_DOWNLOADS) return null
        val id = nextId++
        armedAt[id] = nowMillis
        return id
    }

    @Synchronized
    fun handle(message: DownloadMessage, nowMillis: Long) {
        when (message) {
            is DownloadMessage.Start -> begin(message, nowMillis)
            is DownloadMessage.Chunk -> append(message, nowMillis)
            is DownloadMessage.End -> finish(message.id)
            is DownloadMessage.Abort -> fail(message.id, SaveResult.FAILED)
            is DownloadMessage.Invalid -> fail(message.id, SaveResult.FAILED)
        }
    }

    @Synchronized
    fun sweep(nowMillis: Long) {
        armedAt.entries.removeAll { nowMillis - it.value > IDLE_MILLIS }
        sessions.filterValues { nowMillis - it.lastActivity > IDLE_MILLIS }.keys.forEach { fail(it, SaveResult.FAILED) }
    }

    @Synchronized
    fun abortAll() {
        armedAt.clear()
        sessions.keys.toList().forEach { fail(it, SaveResult.FAILED) }
    }

    private fun begin(start: DownloadMessage.Start, nowMillis: Long) {
        if (armedAt.remove(start.id) == null) return
        val fileName = DownloadPolicy.sanitizeFileName(start.fileName)
        if (start.declaredBytes !in 0..maxBytes) {
            listener.onStop(start.id)
            return listener.onFinished(start.id, fileName, SaveResult.TOO_LARGE)
        }
        val stored = try {
            store.create(fileName, DownloadPolicy.sanitizeMimeType(start.mimeType))
        } catch (failure: Exception) {
            listener.onStop(start.id)
            return listener.onFinished(start.id, fileName, SaveResult.FAILED)
        }
        sessions[start.id] = Session(fileName, start.declaredBytes, stored, nowMillis)
        listener.onAck(start.id)
    }

    private fun append(chunk: DownloadMessage.Chunk, nowMillis: Long) {
        val session = sessions[chunk.id] ?: return
        val bytes = try {
            Base64.getDecoder().decode(chunk.base64)
        } catch (failure: IllegalArgumentException) {
            return fail(chunk.id, SaveResult.FAILED)
        }
        session.writtenBytes += bytes.size
        if (session.writtenBytes > maxBytes) return fail(chunk.id, SaveResult.TOO_LARGE)
        if (session.writtenBytes > session.declaredBytes) return fail(chunk.id, SaveResult.FAILED)
        try {
            session.stored.write(bytes)
        } catch (failure: Exception) {
            return fail(chunk.id, SaveResult.FAILED)
        }
        session.lastActivity = nowMillis
        listener.onAck(chunk.id)
    }

    private fun finish(id: Int) {
        val session = sessions[id] ?: return
        if (session.writtenBytes != session.declaredBytes) return fail(id, SaveResult.FAILED)
        try {
            session.stored.publish()
        } catch (failure: Exception) {
            return fail(id, SaveResult.FAILED)
        }
        sessions.remove(id)
        listener.onFinished(id, session.fileName, SaveResult.SAVED)
    }

    private fun fail(id: Int, result: SaveResult) {
        val wasArmed = armedAt.remove(id) != null
        val session = sessions.remove(id)
        if (!wasArmed && session == null) return
        listener.onStop(id)
        val discarded = session?.let { discard(it.stored) } ?: true
        listener.onFinished(id, session?.fileName ?: DownloadPolicy.FALLBACK_FILE_NAME, if (discarded) result else SaveResult.FAILED)
    }

    private fun discard(stored: StoredDownload): Boolean = try {
        stored.discard()
        true
    } catch (failure: Exception) {
        false
    }

    private companion object {
        const val FIRST_ID = 1
        const val MAX_OPEN_DOWNLOADS = 4
        const val IDLE_MILLIS = 60_000L
    }
}
