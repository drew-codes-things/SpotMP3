package app.starfire.webapp

import android.content.ContentResolver
import android.os.SystemClock
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class DownloadSaver(
    resolver: ContentResolver,
    private val onFinished: (String, SaveResult) -> Unit,
    private val reply: (String) -> Unit,
) {
    private val worker = Executors.newSingleThreadScheduledExecutor()
    private val sessions = DownloadSessions(MediaStoreDownloadStore(resolver), SessionEvents())

    init {
        worker.scheduleWithFixedDelay({ sessions.sweep(SystemClock.elapsedRealtime()) }, SWEEP_SECONDS, SWEEP_SECONDS, TimeUnit.SECONDS)
    }

    fun arm(): Int? = sessions.arm(SystemClock.elapsedRealtime())

    fun handle(message: DownloadMessage) {
        worker.execute { sessions.handle(message, SystemClock.elapsedRealtime()) }
    }

    fun abortAll() {
        worker.execute { sessions.abortAll() }
    }

    fun shutdown() {
        worker.execute { sessions.abortAll() }
        worker.shutdown()
    }

    private inner class SessionEvents : DownloadListener {
        override fun onAck(id: Int) = reply("ack:$id")

        override fun onStop(id: Int) = reply("stop:$id")

        override fun onFinished(id: Int, fileName: String, result: SaveResult) = onFinished(fileName, result)
    }

    private companion object {
        const val SWEEP_SECONDS = 10L
    }
}
