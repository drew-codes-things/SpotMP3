package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DownloadMessageTest {
    @Test
    fun startCarriesSizeTypeAndName() {
        assertEquals(DownloadMessage.Start(1234, "application/zip", "map.zip"), DownloadMessage.parse("S\n1234\napplication/zip\nmap.zip"))
    }

    @Test
    fun fileNameMayContainNewlinesWithoutBreakingTheHeader() {
        assertEquals(DownloadMessage.Start(5, "a/b", "x\ny"), DownloadMessage.parse("S\n5\na/b\nx\ny"))
    }

    @Test
    fun startNeedsANumericSize() {
        assertNull(DownloadMessage.parse("S\nbig\napplication/zip\nmap.zip"))
        assertNull(DownloadMessage.parse("S\n12"))
    }

    @Test
    fun chunkCarriesBase64Only() {
        assertEquals(DownloadMessage.Chunk("QUJD"), DownloadMessage.parse("C\nQUJD"))
        assertNull(DownloadMessage.parse("C\nnot base64!"))
    }

    @Test
    fun oversizedChunksAreRefused() {
        assertNull(DownloadMessage.parse("C\n" + "A".repeat(DownloadMessage.MAX_CHUNK_CHARS + 4)))
    }

    @Test
    fun endAndAbortAreSingleLetters() {
        assertEquals(DownloadMessage.End, DownloadMessage.parse("E"))
        assertEquals(DownloadMessage.Abort, DownloadMessage.parse("X"))
    }

    @Test
    fun unknownMessagesAreIgnored() {
        assertNull(DownloadMessage.parse(""))
        assertNull(DownloadMessage.parse("Z\nhello"))
        assertNull(DownloadMessage.parse("Estuff"))
    }
}
