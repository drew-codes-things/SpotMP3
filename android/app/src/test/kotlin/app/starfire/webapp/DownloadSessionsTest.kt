package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DownloadSessionsTest {
    private class FakeFile(val store: FakeStore) : StoredDownload {
        val content = StringBuilder()
        var published = false
        var discarded = false

        override fun write(bytes: ByteArray) {
            if (store.failWrite) throw java.io.IOException("No space left on device")
            content.append(String(bytes))
        }

        override fun publish() {
            if (store.failPublish) throw IllegalStateException("update failed")
            published = true
        }

        override fun discard() {
            discarded = true
        }
    }

    private class FakeStore : DownloadStore {
        val files = mutableListOf<FakeFile>()
        var failCreate = false
        var failWrite = false
        var failPublish = false

        override fun create(fileName: String, mimeType: String): StoredDownload {
            if (failCreate) throw IllegalStateException("Failed to build unique file")
            return FakeFile(this).also { files.add(it) }
        }
    }

    private class Events : DownloadListener {
        val acks = mutableListOf<Int>()
        val stops = mutableListOf<Int>()
        val finished = mutableListOf<Triple<Int, String, SaveResult>>()
        override fun onAck(id: Int) {
            acks.add(id)
        }
        override fun onStop(id: Int) {
            stops.add(id)
        }
        override fun onFinished(id: Int, fileName: String, result: SaveResult) {
            finished.add(Triple(id, fileName, result))
        }
    }

    private val store = FakeStore()
    private val events = Events()
    private val sessions = DownloadSessions(store, events, maxBytes = 100)

    private fun start(id: Int, name: String, size: Long) = DownloadMessage.Start(id, size, "application/zip", name)

    private fun chunk(id: Int, text: String) = DownloadMessage.Chunk(id, java.util.Base64.getEncoder().encodeToString(text.toByteArray()))

    private fun armed(): Int = assertNotNull(sessions.arm(0))

    @Test
    fun interleavedDownloadsBothSaveIntact() {
        val a = armed()
        val b = armed()
        sessions.handle(start(a, "a.zip", 8), 1)
        sessions.handle(start(b, "b.zip", 8), 1)
        sessions.handle(chunk(a, "AAAA"), 2)
        sessions.handle(chunk(b, "BBBB"), 2)
        sessions.handle(chunk(b, "bbbb"), 3)
        sessions.handle(chunk(a, "aaaa"), 3)
        sessions.handle(DownloadMessage.End(a), 4)
        sessions.handle(DownloadMessage.End(b), 4)
        assertEquals(listOf("AAAAaaaa", "BBBBbbbb"), store.files.map { it.content.toString() })
        assertTrue(store.files.all { it.published && !it.discarded })
        assertEquals(listOf(SaveResult.SAVED, SaveResult.SAVED), events.finished.map { it.third })
        assertEquals(listOf("a.zip", "b.zip"), events.finished.map { it.second })
    }

    @Test
    fun everyAcceptedChunkIsAcknowledged() {
        val id = armed()
        sessions.handle(start(id, "a.zip", 8), 1)
        sessions.handle(chunk(id, "AAAA"), 2)
        sessions.handle(chunk(id, "BBBB"), 3)
        assertEquals(listOf(id, id, id), events.acks)
    }

    @Test
    fun aStartWithAnIdNativeCodeDidNotIssueIsIgnored() {
        sessions.handle(start(99, "x.zip", 4), 1)
        assertEquals(0, store.files.size)
        assertEquals(0, events.finished.size)
        assertEquals(0, events.stops.size)
    }

    @Test
    fun anIdCanOnlyStartOnce() {
        val id = armed()
        sessions.handle(start(id, "a.zip", 4), 1)
        sessions.handle(start(id, "again.zip", 4), 2)
        assertEquals(1, store.files.size)
    }

    @Test
    fun declaredSizeAboveTheLimitIsRefusedAndTheSenderIsStopped() {
        val id = armed()
        sessions.handle(start(id, "big.zip", 101), 1)
        assertEquals(0, store.files.size)
        assertEquals(listOf(id), events.stops)
        assertEquals(SaveResult.TOO_LARGE, events.finished.single().third)
    }

    @Test
    fun negativeDeclaredSizeIsRefused() {
        val id = armed()
        sessions.handle(start(id, "x.zip", -1), 1)
        assertEquals(SaveResult.TOO_LARGE, events.finished.single().third)
    }

    @Test
    fun anEndWithFewerBytesThanDeclaredFailsAndDeletesTheFile() {
        val id = armed()
        sessions.handle(start(id, "short.zip", 10), 1)
        sessions.handle(chunk(id, "AAAA"), 2)
        sessions.handle(DownloadMessage.End(id), 3)
        assertTrue(store.files.single().discarded)
        assertTrue(!store.files.single().published)
        assertEquals(SaveResult.FAILED, events.finished.single().third)
        assertEquals("short.zip", events.finished.single().second)
    }

    @Test
    fun moreBytesThanDeclaredFailsTheDownload() {
        val id = armed()
        sessions.handle(start(id, "x.zip", 4), 1)
        sessions.handle(chunk(id, "AAAAAA"), 2)
        assertTrue(store.files.single().discarded)
        assertEquals(SaveResult.FAILED, events.finished.single().third)
    }

    @Test
    fun bytesWrittenAboveTheLimitAbortEvenIfTheDeclaredSizeLied() {
        val id = armed()
        sessions.handle(start(id, "liar.zip", 100), 1)
        sessions.handle(chunk(id, "A".repeat(60)), 2)
        sessions.handle(chunk(id, "A".repeat(60)), 3)
        assertTrue(store.files.single().discarded)
        assertEquals(SaveResult.TOO_LARGE, events.finished.single().third)
    }

    @Test
    fun anInvalidMessageMidDownloadAbortsIt() {
        val id = armed()
        sessions.handle(start(id, "x.zip", 8), 1)
        sessions.handle(chunk(id, "AAAA"), 2)
        sessions.handle(DownloadMessage.Invalid(id), 3)
        assertTrue(store.files.single().discarded)
        assertEquals(SaveResult.FAILED, events.finished.single().third)
    }

    @Test
    fun badBase64AbortsTheDownload() {
        val id = armed()
        sessions.handle(start(id, "x.zip", 8), 1)
        sessions.handle(DownloadMessage.Chunk(id, "A"), 2)
        assertTrue(store.files.single().discarded)
        assertEquals(SaveResult.FAILED, events.finished.single().third)
    }

    @Test
    fun storeFailuresNeverEscapeAndLeaveNoPendingFile() {
        store.failCreate = true
        val first = armed()
        sessions.handle(start(first, "a.zip", 4), 1)
        assertEquals(SaveResult.FAILED, events.finished.last().third)
        store.failCreate = false
        store.failWrite = true
        val second = armed()
        sessions.handle(start(second, "b.zip", 4), 1)
        sessions.handle(chunk(second, "AAAA"), 2)
        assertTrue(store.files.last().discarded)
        assertEquals(SaveResult.FAILED, events.finished.last().third)
        store.failWrite = false
        store.failPublish = true
        val third = armed()
        sessions.handle(start(third, "c.zip", 4), 1)
        sessions.handle(chunk(third, "AAAA"), 2)
        sessions.handle(DownloadMessage.End(third), 3)
        assertTrue(store.files.last().discarded)
        assertEquals(SaveResult.FAILED, events.finished.last().third)
        assertEquals(3, events.finished.size)
    }

    @Test
    fun aFakeAbortFromThePageForAnUnknownIdIsIgnored() {
        sessions.handle(DownloadMessage.Abort(42), 1)
        sessions.handle(DownloadMessage.Invalid(42), 1)
        assertEquals(0, events.finished.size)
    }

    @Test
    fun idleDownloadsAreAbortedAfterAboutAMinute() {
        val id = armed()
        sessions.handle(start(id, "x.zip", 8), 1_000)
        sessions.handle(chunk(id, "AAAA"), 2_000)
        sessions.sweep(40_000)
        assertEquals(0, events.finished.size)
        sessions.sweep(62_001)
        assertTrue(store.files.single().discarded)
        assertEquals(SaveResult.FAILED, events.finished.single().third)
    }

    @Test
    fun anIdThatNeverStartsExpires() {
        val id = armed()
        sessions.sweep(61_000)
        sessions.handle(start(id, "late.zip", 4), 62_000)
        assertEquals(0, store.files.size)
    }

    @Test
    fun abortAllEndsEveryOpenDownload() {
        val a = armed()
        val b = armed()
        sessions.handle(start(a, "a.zip", 8), 1)
        sessions.handle(start(b, "b.zip", 8), 1)
        sessions.abortAll()
        assertTrue(store.files.all { it.discarded })
        assertEquals(2, events.finished.size)
        val c = armed()
        sessions.handle(start(c, "c.zip", 4), 2)
        assertEquals(3, store.files.size)
    }

    @Test
    fun onlyAFewDownloadsMayBeOpenAtOnce() {
        val ids = (1..4).map { sessions.arm(0) }
        assertTrue(ids.all { it != null })
        assertNull(sessions.arm(0))
    }
}
