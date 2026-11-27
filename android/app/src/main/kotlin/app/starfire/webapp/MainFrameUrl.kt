package app.starfire.webapp

object MainFrameUrl {
    fun isSame(errorUrl: String, currentUrl: String?): Boolean {
        if (currentUrl == null) return true
        return normalised(errorUrl) == normalised(currentUrl)
    }

    fun matchesMainFrame(errorUrl: String, currentUrl: String?, pendingUrl: String?): Boolean {
        val known = listOfNotNull(currentUrl, pendingUrl)
        return known.isEmpty() || known.any { isSame(errorUrl, it) }
    }

    private fun normalised(url: String) = url.substringBefore('#').trimEnd('/')
}
