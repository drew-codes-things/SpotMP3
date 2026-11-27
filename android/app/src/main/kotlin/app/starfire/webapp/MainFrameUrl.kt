package app.starfire.webapp

object MainFrameUrl {
    fun isSame(errorUrl: String, currentUrl: String?): Boolean {
        if (currentUrl == null) return true
        return normalised(errorUrl) == normalised(currentUrl)
    }

    private fun normalised(url: String) = url.substringBefore('#').trimEnd('/')
}
