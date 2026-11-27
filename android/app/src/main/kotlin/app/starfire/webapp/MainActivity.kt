package app.starfire.webapp

import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.Bitmap
import android.graphics.drawable.Icon
import android.net.http.SslError
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.os.SystemClock
import android.text.TextUtils
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var container: FrameLayout
    private lateinit var startUrl: String
    private lateinit var urlPolicy: UrlPolicy
    private lateinit var originRules: Set<String>
    private lateinit var downloadSaver: DownloadSaver
    private var pendingFileChooser: ValueCallback<Array<Uri>>? = null
    private val crashLimiter = CrashLimiter(MAX_RENDERER_CRASHES, RENDERER_CRASH_WINDOW_MILLIS)
    private var offlineShown = false
    private var clearHistoryWhenFinished = false
    private var fullscreenView: View? = null
    private var fullscreenCallback: WebChromeClient.CustomViewCallback? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = AddressStore(this)
        startUrl = requireNotNull(store.url()) { "MainActivity started before an address was set" }
        urlPolicy = UrlPolicy(AddressValidator.allowedHosts(startUrl, store.extraHosts()))
        originRules = DownloadPolicy.originRules(startUrl, store.extraHosts())
        downloadSaver = DownloadSaver(contentResolver) { result -> runOnUiThread { toast(saveMessage(result)) } }
        publishChangeAddressShortcut()
        container = FrameLayout(this)
        setContentView(container)
        CookieManager.getInstance().setAcceptCookie(true)
        attachNewWebView()
        val restored = savedInstanceState != null && webView.restoreState(savedInstanceState) != null
        if (!restored) webView.loadUrl(startUrl)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun attachNewWebView() {
        webView = WebView(this)
        container.addView(webView, 0, MATCH_PARENT_LAYOUT)
        addDownloadListener()
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            mediaPlaybackRequiresUserGesture = false
        }
        webView.setBackgroundColor(BACKGROUND_COLOR)
        webView.webViewClient = AppWebViewClient()
        webView.webChromeClient = AppChromeClient()
        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            startDownload(url, userAgent, contentDisposition, mimeType)
        }
    }

    private fun addDownloadListener() {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return
        WebViewCompat.addWebMessageListener(webView, DownloadScript.LISTENER_NAME, originRules) { _, message, sourceOrigin, isMainFrame, replyProxy ->
            if (!isMainFrame || !DownloadPolicy.isAllowedOrigin(sourceOrigin.toString(), originRules)) return@addWebMessageListener
            val parsed = message.data?.let(DownloadMessage::parse) ?: return@addWebMessageListener
            downloadSaver.handle(parsed) { runOnUiThread { replyProxy.postMessage(STOP_MESSAGE) } }
        }
    }

    private fun startBlobDownload(url: String, contentDisposition: String, mimeType: String) {
        val blobOriginIsAllowed = urlPolicy.staysInApp(url.removePrefix(BLOB_PREFIX))
        if (!blobOriginIsAllowed || !WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            toast(R.string.download_unsupported)
            return
        }
        val fileName = DownloadPolicy.sanitizeFileName(URLUtil.guessFileName(url, contentDisposition, mimeType))
        webView.evaluateJavascript(DownloadScript.forBlob(url, fileName), null)
        toast(R.string.download_started)
    }

    private fun saveMessage(result: DownloadSaver.SaveResult) = when (result) {
        DownloadSaver.SaveResult.SAVED -> R.string.download_saved
        DownloadSaver.SaveResult.TOO_LARGE -> R.string.download_too_large
        DownloadSaver.SaveResult.FAILED -> R.string.download_failed
    }

    private fun replaceCrashedWebView() {
        val crashedTooOften = crashLimiter.recordAndCheckExceeded(SystemClock.elapsedRealtime())
        hideFullscreen()
        pendingFileChooser?.onReceiveValue(null)
        pendingFileChooser = null
        container.removeView(webView)
        webView.destroy()
        attachNewWebView()
        if (crashedTooOften) showOfflinePage(webView, R.string.offline_crash_message) else webView.loadUrl(startUrl)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
    }

    override fun onPause() {
        webView.onPause()
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onDestroy() {
        downloadSaver.shutdown()
        container.removeAllViews()
        webView.destroy()
        super.onDestroy()
    }

    @Deprecated("Back handling on API 29 to 35 goes through onBackPressed")
    override fun onBackPressed() {
        when {
            fullscreenView != null -> hideFullscreen()
            offlineShown -> super.onBackPressed()
            webView.canGoBack() -> webView.goBack()
            else -> super.onBackPressed()
        }
    }

    @Deprecated("File chooser results arrive here")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != FILE_CHOOSER_REQUEST) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        pendingFileChooser?.onReceiveValue(pickedFiles(resultCode, data))
        pendingFileChooser = null
    }

    private fun pickedFiles(resultCode: Int, data: Intent?): Array<Uri>? {
        if (resultCode != RESULT_OK || data == null) return null
        val clip = data.clipData
        val clipUris = if (clip == null) emptyList() else (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri?.toString() }
        val picked = FileChooserResult.pickedUris(clipUris, data.data?.toString())
        return if (picked.isEmpty()) null else picked.map(Uri::parse).toTypedArray()
    }

    private fun startDownload(url: String, userAgent: String, contentDisposition: String, mimeType: String) {
        if (url.startsWith(BLOB_PREFIX)) return startBlobDownload(url, contentDisposition, mimeType)
        if (!URLUtil.isHttpsUrl(url)) {
            toast(R.string.download_unsupported)
            return
        }
        val fileName = URLUtil.guessFileName(url, contentDisposition, mimeType)
        val request = DownloadManager.Request(Uri.parse(url))
            .setMimeType(mimeType)
            .addRequestHeader("User-Agent", userAgent)
            .setTitle(fileName)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)
        if (urlPolicy.staysInApp(url)) {
            CookieManager.getInstance().getCookie(url)?.let { request.addRequestHeader("Cookie", it) }
        }
        val manager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        manager.enqueue(request)
        toast(R.string.download_started)
    }

    private fun openExternally(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (missing: ActivityNotFoundException) {
            toast(R.string.no_app_for_link)
        }
    }

    private fun showFullscreen(view: View, callback: WebChromeClient.CustomViewCallback) {
        fullscreenView = view
        fullscreenCallback = callback
        webView.visibility = View.GONE
        container.addView(view, MATCH_PARENT_LAYOUT)
    }

    private fun hideFullscreen() {
        fullscreenView?.let { container.removeView(it) }
        fullscreenView = null
        fullscreenCallback?.onCustomViewHidden()
        fullscreenCallback = null
        webView.visibility = View.VISIBLE
    }

    private fun publishChangeAddressShortcut() {
        val intent = Intent(this, SetupActivity::class.java).setAction(Intent.ACTION_VIEW)
        val shortcut = ShortcutInfo.Builder(this, CHANGE_ADDRESS_SHORTCUT_ID)
            .setShortLabel(getString(R.string.change_address))
            .setIcon(Icon.createWithResource(this, R.mipmap.ic_launcher))
            .setIntent(intent)
            .build()
        getSystemService(ShortcutManager::class.java).dynamicShortcuts = listOf(shortcut)
    }

    private fun toast(message: Int) = Toast.makeText(this, message, Toast.LENGTH_SHORT).show()

    private inner class AppWebViewClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url.toString()
            if (url == CHANGE_ADDRESS_URL) {
                if (offlineShown && request.isForMainFrame && request.hasGesture()) {
                    startActivity(Intent(this@MainActivity, SetupActivity::class.java))
                }
                return true
            }
            if (urlPolicy.staysInApp(url)) return false
            if (urlPolicy.opensExternally(url)) openExternally(url) else if (request.hasGesture()) toast(R.string.link_not_opened)
            return true
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            showOfflinePage(view, R.string.offline_message)
        }

        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            handler.cancel()
            val failedMainFrame = MainFrameUrl.isSame(error.url, view.url)
            if (failedMainFrame && urlPolicy.staysInApp(error.url)) showOfflinePage(view, R.string.offline_tls_message)
        }

        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            if (!url.startsWith("https://") || !offlineShown) return
            offlineShown = false
            clearHistoryWhenFinished = true
        }

        override fun onPageFinished(view: WebView, url: String) {
            CookieManager.getInstance().flush()
            if (!clearHistoryWhenFinished) return
            clearHistoryWhenFinished = false
            view.clearHistory()
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            if (view === webView) replaceCrashedWebView()
            return true
        }
    }

    private inner class AppChromeClient : WebChromeClient() {
        override fun onShowFileChooser(
            webView: WebView,
            filePathCallback: ValueCallback<Array<Uri>>,
            fileChooserParams: FileChooserParams,
        ): Boolean {
            pendingFileChooser?.onReceiveValue(null)
            pendingFileChooser = filePathCallback
            return try {
                startActivityForResult(fileChooserParams.createIntent(), FILE_CHOOSER_REQUEST)
                true
            } catch (missing: ActivityNotFoundException) {
                pendingFileChooser = null
                filePathCallback.onReceiveValue(null)
                toast(R.string.no_file_picker)
                true
            }
        }

        override fun onShowCustomView(view: View, callback: CustomViewCallback) {
            hideFullscreen()
            showFullscreen(view, callback)
        }

        override fun onHideCustomView() = hideFullscreen()
    }

    private fun showOfflinePage(view: WebView, messageResource: Int) {
        offlineShown = true
        view.loadDataWithBaseURL(null, offlinePage(getString(messageResource)), "text/html", "utf-8", null)
    }

    private fun offlinePage(message: String): String {
        val retryUrl = TextUtils.htmlEncode(startUrl)
        val retry = getString(R.string.offline_retry)
        val change = getString(R.string.offline_change_address)
        return "<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head>" +
            "<body style=\"background:#19191c;color:#e8e8ec;font-family:sans-serif;text-align:center;padding:4em 1em\">" +
            "<p>$message</p><p><a style=\"color:#8ab4ff\" href=\"$retryUrl\">$retry</a></p>" +
            "<p><a style=\"color:#8ab4ff\" href=\"$CHANGE_ADDRESS_URL\">$change</a></p></body></html>"
    }

    private companion object {
        const val FILE_CHOOSER_REQUEST = 1
        const val MAX_RENDERER_CRASHES = 3
        const val RENDERER_CRASH_WINDOW_MILLIS = 60_000L
        const val BLOB_PREFIX = "blob:"
        const val STOP_MESSAGE = "stop"
        const val CHANGE_ADDRESS_URL = "starfire-app://change-address"
        const val CHANGE_ADDRESS_SHORTCUT_ID = "change_address"
        const val BACKGROUND_COLOR = 0xFF19191C.toInt()
        val MATCH_PARENT_LAYOUT = FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
    }
}
