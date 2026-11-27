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

    private class OpenIds {
        private val lock = Any()
        private val armedAt = HashMap<Int, Long>()
        private val open = HashSet<Int>()
        private var nextId = FIRST_ID

        fun arm(nowMillis: Long): Int? = synchronized(lock) {
            if (open.size >= MAX_OPEN_DOWNLOADS) {
                null
            } else {
                val id = nextId++
                armedAt[id] = nowMillis
                open.add(id)
                id
            }
        }

        fun claim(id: Int): Boolean = synchronized(lock) { armedAt.remove(id) != null }

        fun release(id: Int): Boolean = synchronized(lock) {
            armedAt.remove(id)
            open.remove(id)
        }

        fun expireArmed(nowMillis: Long) {
            synchronized(lock) {
                val expired = armedAt.filterValues { nowMillis - it > IDLE_MILLIS }.keys.toList()
                expired.forEach { armedAt.remove(it); open.remove(it) }
            }
        }

        fun releaseArmed() {
            synchronized(lock) {
                open.removeAll(armedAt.keys)
                armedAt.clear()
            }
        }
    }

    private class ChunkWindow {
        private val lock = Any()
        private val queued = HashMap<Int, Int>()

        fun admit(id: Int): Boolean = synchronized(lock) {
            val count = (queued[id] ?: 0) + 1
            queued[id] = count
            count <= MAX_UNACKNOWLEDGED_CHUNKS
        }

        fun processed(id: Int) {
            synchronized(lock) {
                val count = (queued[id] ?: return) - 1
                if (count <= 0) queued.remove(id) else queued[id] = count
            }
        }

        fun forget(id: Int) {
            synchronized(lock) { queued.remove(id) }
        }
    }

    private val openIds = OpenIds()
    private val window = ChunkWindow()
    private val sessions = HashMap<Int, Session>()

    fun arm(nowMillis: Long): Int? = openIds.arm(nowMillis)

    fun admit(message: DownloadMessage): Boolean = message !is DownloadMessage.Chunk || window.admit(message.id)

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
        openIds.expireArmed(nowMillis)
        sessions.filterValues { nowMillis - it.lastActivity > IDLE_MILLIS }.keys.forEach { fail(it, SaveResult.FAILED) }
    }

    @Synchronized
    fun abortAll() {
        openIds.releaseArmed()
        sessions.keys.toList().forEach { fail(it, SaveResult.FAILED) }
    }

    private fun begin(start: DownloadMessage.Start, nowMillis: Long) {
        if (!openIds.claim(start.id)) return
        val fileName = DownloadPolicy.sanitizeFileName(start.fileName)
        if (start.declaredBytes !in 0..maxBytes) {
            openIds.release(start.id)
            listener.onStop(start.id)
            return listener.onFinished(start.id, fileName, SaveResult.TOO_LARGE)
        }
        val stored = try {
            store.create(fileName, DownloadPolicy.sanitizeMimeType(start.mimeType))
        } catch (failure: Exception) {
            openIds.release(start.id)
            listener.onStop(start.id)
            return listener.onFinished(start.id, fileName, SaveResult.FAILED)
        }
        sessions[start.id] = Session(fileName, start.declaredBytes, stored, nowMillis)
        listener.onAck(start.id)
    }

    private fun append(chunk: DownloadMessage.Chunk, nowMillis: Long) {
        window.processed(chunk.id)
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
        openIds.release(id)
        window.forget(id)
        listener.onFinished(id, session.fileName, SaveResult.SAVED)
    }

    private fun fail(id: Int, result: SaveResult) {
        val wasOpen = openIds.release(id)
        val session = sessions.remove(id)
        window.forget(id)
        if (!wasOpen && session == null) return
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
        const val MAX_UNACKNOWLEDGED_CHUNKS = 4
        const val IDLE_MILLIS = 60_000L
    }
}
