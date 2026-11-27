package app.starfire.webapp

import android.content.ContentResolver
import android.content.ContentValues
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import java.io.OutputStream

class MediaStoreDownloadStore(private val resolver: ContentResolver) : DownloadStore {
    override fun create(fileName: String, mimeType: String): StoredDownload {
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, mimeType)
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.Downloads.IS_PENDING, PENDING)
        }
        val uri = checkNotNull(resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)) { "MediaStore refused the new download" }
        val stream = try {
            checkNotNull(resolver.openOutputStream(uri)) { "MediaStore gave no output stream" }
        } catch (failure: Exception) {
            resolver.delete(uri, null, null)
            throw failure
        }
        return Stored(uri, stream)
    }

    private inner class Stored(private val uri: Uri, private val stream: OutputStream) : StoredDownload {
        override fun write(bytes: ByteArray) = stream.write(bytes)

        override fun publish() {
            stream.close()
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, DONE) }, null, null)
        }

        override fun discard() {
            try {
                stream.close()
            } finally {
                resolver.delete(uri, null, null)
            }
        }
    }

    private companion object {
        const val PENDING = 1
        const val DONE = 0
    }
}
