package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DownloadMessageTest {
    @Test
    fun startCarriesIdSizeTypeAndName() {
        assertEquals(DownloadMessage.Start(7, 1234, "application/zip", "map.zip"), DownloadMessage.parse("S\n7\n1234\napplication/zip\nmap.zip"))
    }

    @Test
    fun fileNameMayContainNewlinesWithoutBreakingTheHeader() {
        assertEquals(DownloadMessage.Start(1, 5, "a/b", "x\ny"), DownloadMessage.parse("S\n1\n5\na/b\nx\ny"))
    }

    @Test
    fun startWithABadSizeIsInvalidButKeepsItsId() {
        assertEquals(DownloadMessage.Invalid(3), DownloadMessage.parse("S\n3\nbig\napplication/zip\nmap.zip"))
        assertEquals(DownloadMessage.Invalid(3), DownloadMessage.parse("S\n3\n12"))
    }

    @Test
    fun chunkCarriesIdAndBase64Only() {
        assertEquals(DownloadMessage.Chunk(2, "QUJD"), DownloadMessage.parse("C\n2\nQUJD"))
        assertEquals(DownloadMessage.Invalid(2), DownloadMessage.parse("C\n2\nnot base64!"))
    }

    @Test
    fun oversizedChunksAreInvalid() {
        assertEquals(DownloadMessage.Invalid(2), DownloadMessage.parse("C\n2\n" + "A".repeat(DownloadMessage.MAX_CHUNK_CHARS + 4)))
    }

    @Test
    fun endAndAbortCarryTheId() {
        assertEquals(DownloadMessage.End(4), DownloadMessage.parse("E\n4"))
        assertEquals(DownloadMessage.Abort(4), DownloadMessage.parse("X\n4"))
    }

    @Test
    fun messagesWithoutAnIdAreIgnored() {
        assertNull(DownloadMessage.parse(""))
        assertNull(DownloadMessage.parse("E"))
        assertNull(DownloadMessage.parse("X"))
        assertNull(DownloadMessage.parse("E\nabc"))
        assertNull(DownloadMessage.parse("C\nQUJD"))
        assertNull(DownloadMessage.parse("Z\n1\nhello"))
        assertNull(DownloadMessage.parse("Estuff"))
    }
}
