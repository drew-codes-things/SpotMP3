package app.starfire.webapp

import android.content.ContentResolver
import android.content.ContentValues
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import java.io.IOException
import java.io.OutputStream
import java.util.concurrent.Executors

class DownloadSaver(private val resolver: ContentResolver, private val onResult: (SaveResult) -> Unit) {
    enum class SaveResult { SAVED, TOO_LARGE, FAILED }

    private val worker = Executors.newSingleThreadExecutor()
    private var target: Uri? = null
    private var output: OutputStream? = null
    private var writtenBytes = 0L

    fun handle(message: DownloadMessage, stopSender: () -> Unit) {
        worker.execute {
            when (message) {
                is DownloadMessage.Start -> begin(message, stopSender)
                is DownloadMessage.Chunk -> append(message.base64, stopSender)
                DownloadMessage.End -> finish()
                DownloadMessage.Abort -> discard(SaveResult.FAILED)
            }
        }
    }

    fun shutdown() {
        worker.execute { deleteTarget() }
        worker.shutdown()
    }

    private fun begin(start: DownloadMessage.Start, stopSender: () -> Unit) {
        deleteTarget()
        if (!DownloadPolicy.isWithinLimit(start.declaredBytes)) {
            stopSender()
            return onResult(SaveResult.TOO_LARGE)
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, DownloadPolicy.sanitizeFileName(start.fileName))
            put(MediaStore.Downloads.MIME_TYPE, DownloadPolicy.sanitizeMimeType(start.mimeType))
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.Downloads.IS_PENDING, PENDING)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        val stream = uri?.let { resolver.openOutputStream(it) }
        if (uri == null || stream == null) {
            uri?.let { resolver.delete(it, null, null) }
            stopSender()
            return onResult(SaveResult.FAILED)
        }
        target = uri
        output = stream
        writtenBytes = 0
    }

    private fun append(base64: String, stopSender: () -> Unit) {
        val stream = output ?: return
        try {
            val bytes = Base64.decode(base64, Base64.NO_WRAP)
            writtenBytes += bytes.size
            if (writtenBytes > DownloadPolicy.MAX_BYTES) {
                stopSender()
                return discard(SaveResult.TOO_LARGE)
            }
            stream.write(bytes)
        } catch (failure: IOException) {
            stopSender()
            discard(SaveResult.FAILED)
        } catch (failure: IllegalArgumentException) {
            stopSender()
            discard(SaveResult.FAILED)
        }
    }

    private fun finish() {
        val uri = target ?: return
        try {
            output?.close()
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, DONE) }, null, null)
            clear()
            onResult(SaveResult.SAVED)
        } catch (failure: IOException) {
            discard(SaveResult.FAILED)
        }
    }

    private fun discard(result: SaveResult) {
        val closedCleanly = deleteTarget()
        onResult(if (closedCleanly) result else SaveResult.FAILED)
    }

    private fun deleteTarget(): Boolean {
        val closedCleanly = try {
            output?.close()
            true
        } catch (failure: IOException) {
            false
        }
        target?.let { resolver.delete(it, null, null) }
        clear()
        return closedCleanly
    }

    private fun clear() {
        target = null
        output = null
        writtenBytes = 0
    }

    private companion object {
        const val PENDING = 1
        const val DONE = 0
    }
}
