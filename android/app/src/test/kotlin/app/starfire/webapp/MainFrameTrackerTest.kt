package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MainFrameTrackerTest {
    private val tracker = MainFrameTracker(UrlPolicy(setOf("a.example.com")))

    @Test
    fun aTappedLinkOnTheSameSiteIsTheMainFrameWhenItsCertificateFails() {
        assertTrue(tracker.onNavigationRequest("https://a.example.com/next", isForMainFrame = true))
        assertTrue(tracker.isMainFrameFailure("https://a.example.com/next", "https://a.example.com/"))
    }

    @Test
    fun subresourceFailuresStaySilent() {
        tracker.onNavigationRequest("https://a.example.com/next", isForMainFrame = true)
        assertFalse(tracker.isMainFrameFailure("https://a.example.com/img.png", "https://a.example.com/"))
    }

    @Test
    fun subframeNavigationsAreNotRecordedAsTheMainFrame() {
        assertTrue(tracker.onNavigationRequest("https://a.example.com/frame", isForMainFrame = false))
        assertFalse(tracker.isMainFrameFailure("https://a.example.com/frame", "https://a.example.com/"))
    }

    @Test
    fun linksLeavingTheAppAreNeverRecorded() {
        assertFalse(tracker.onNavigationRequest("https://evil.example.org/", isForMainFrame = true))
        assertFalse(tracker.isMainFrameFailure("https://evil.example.org/", "https://a.example.com/"))
    }

    @Test
    fun theFirstLoadIsTheMainFrameBeforeAnythingIsKnown() {
        assertTrue(tracker.isMainFrameFailure("https://a.example.com/", null))
    }

    @Test
    fun aCommittedPageCountsAsMainFrame() {
        tracker.onPageCommitted("https://a.example.com/page")
        assertTrue(tracker.isMainFrameFailure("https://a.example.com/page", "https://a.example.com/other"))
    }
}
