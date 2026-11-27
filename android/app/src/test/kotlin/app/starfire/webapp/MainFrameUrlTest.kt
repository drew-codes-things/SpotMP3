package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MainFrameUrlTest {
    @Test
    fun sameAddressIsTheMainFrame() {
        assertTrue(MainFrameUrl.isSame("https://photos.example.com/", "https://photos.example.com/"))
        assertTrue(MainFrameUrl.isSame("https://photos.example.com", "https://photos.example.com/"))
        assertTrue(MainFrameUrl.isSame("https://photos.example.com/a", "https://photos.example.com/a#top"))
    }

    @Test
    fun nothingLoadedYetMeansTheErrorIsTheMainFrame() {
        assertTrue(MainFrameUrl.isSame("https://photos.example.com/", null))
    }

    @Test
    fun otherAddressesAreSubresources() {
        assertFalse(MainFrameUrl.isSame("https://files.example.com/img.png", "https://photos.example.com/"))
        assertFalse(MainFrameUrl.isSame("https://photos.example.com/img.png", "https://photos.example.com/"))
    }

    @Test
    fun aTappedLinkIsTheMainFrameWhileItIsPending() {
        assertTrue(MainFrameUrl.matchesMainFrame("https://a.example.com/next", "https://a.example.com/", "https://a.example.com/next"))
        assertFalse(MainFrameUrl.matchesMainFrame("https://a.example.com/img.png", "https://a.example.com/", "https://a.example.com/next"))
        assertTrue(MainFrameUrl.matchesMainFrame("https://a.example.com/", null, null))
    }
}
