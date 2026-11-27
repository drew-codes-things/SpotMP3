package app.starfire.webapp

class MainFrameTracker(private val policy: UrlPolicy) {
    private var pendingUrl: String? = null

    fun onNavigationRequest(url: String, isForMainFrame: Boolean): Boolean {
        val staysInApp = policy.staysInApp(url)
        if (staysInApp && isForMainFrame) pendingUrl = url
        return staysInApp
    }

    fun onPageCommitted(url: String) {
        if (url.startsWith("https://")) pendingUrl = url
    }

    fun isMainFrameFailure(errorUrl: String, currentUrl: String?): Boolean =
        MainFrameUrl.matchesMainFrame(errorUrl, currentUrl, pendingUrl) && policy.staysInApp(errorUrl)
}
