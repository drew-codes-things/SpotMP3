package app.starfire.webapp

import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.text.TextUtils
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
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

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var container: FrameLayout
    private lateinit var startUrl: String
    private lateinit var urlPolicy: UrlPolicy
    private var pendingFileChooser: ValueCallback<Array<Uri>>? = null
    private var fullscreenView: View? = null
    private var fullscreenCallback: WebChromeClient.CustomViewCallback? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = AddressStore(this)
        startUrl = requireNotNull(store.url()) { "MainActivity started before an address was set" }
        urlPolicy = UrlPolicy(AddressValidator.allowedHosts(startUrl, store.extraHosts()))
        publishChangeAddressShortcut()
        container = FrameLayout(this)
        webView = WebView(this)
        container.addView(webView, MATCH_PARENT_LAYOUT)
        setContentView(container)

        CookieManager.getInstance().setAcceptCookie(true)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = true
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            mediaPlaybackRequiresUserGesture = false
        }
        webView.setBackgroundColor(BACKGROUND_COLOR)
        webView.webViewClient = AppWebViewClient()
        webView.webChromeClient = AppChromeClient()
        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            startDownload(url, userAgent, contentDisposition, mimeType)
        }

        if (savedInstanceState == null) webView.loadUrl(startUrl) else webView.restoreState(savedInstanceState)
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
        container.removeAllViews()
        webView.destroy()
        super.onDestroy()
    }

    @Deprecated("Back handling on API 29 to 35 goes through onBackPressed")
    override fun onBackPressed() {
        when {
            fullscreenView != null -> hideFullscreen()
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
        pendingFileChooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
        pendingFileChooser = null
    }

    private fun startDownload(url: String, userAgent: String, contentDisposition: String, mimeType: String) {
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
        CookieManager.getInstance().getCookie(url)?.let { request.addRequestHeader("Cookie", it) }
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
                startActivity(Intent(this@MainActivity, SetupActivity::class.java))
                return true
            }
            if (urlPolicy.staysInApp(url)) return false
            if (urlPolicy.opensExternally(url)) openExternally(url)
            return true
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            view.loadDataWithBaseURL(null, offlinePage(), "text/html", "utf-8", null)
        }

        override fun onPageFinished(view: WebView, url: String) {
            CookieManager.getInstance().flush()
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
                false
            }
        }

        override fun onShowCustomView(view: View, callback: CustomViewCallback) {
            hideFullscreen()
            showFullscreen(view, callback)
        }

        override fun onHideCustomView() = hideFullscreen()
    }

    private fun offlinePage(): String {
        val retryUrl = TextUtils.htmlEncode(startUrl)
        val message = getString(R.string.offline_message)
        val retry = getString(R.string.offline_retry)
        val change = getString(R.string.offline_change_address)
        return "<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head>" +
            "<body style=\"background:#19191c;color:#e8e8ec;font-family:sans-serif;text-align:center;padding:4em 1em\">" +
            "<p>$message</p><p><a style=\"color:#8ab4ff\" href=\"$retryUrl\">$retry</a></p>" +
            "<p><a style=\"color:#8ab4ff\" href=\"$CHANGE_ADDRESS_URL\">$change</a></p></body></html>"
    }

    private companion object {
        const val FILE_CHOOSER_REQUEST = 1
        const val CHANGE_ADDRESS_URL = "starfire-app://change-address"
        const val CHANGE_ADDRESS_SHORTCUT_ID = "change_address"
        const val BACKGROUND_COLOR = 0xFF19191C.toInt()
        val MATCH_PARENT_LAYOUT = FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
    }
}
