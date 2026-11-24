package gg.cynica.shugotracker

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.content.FileProvider
import androidx.webkit.WebViewAssetLoader
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** The page (the desktop app's screens) talks to the Python core through AndroidCore.send; the core answers
 *  through Poster.post, which hands each message back to the page. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var core: PyObject
    private val pool = Executors.newFixedThreadPool(4)

    inner class Poster {
        @Suppress("unused")            // called from Python
        fun post(line: String) {
            web.post { web.evaluateJavascript("window.__shugoIn && window.__shugoIn(${JSONObject.quote(line)})", null) }
        }

        /** Updates: hand the downloaded APK to Android's installer (it asks you to confirm). */
        @Suppress("unused")            // called from Python
        fun install(path: String) {
            val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.files", File(path))
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    inner class Bridge {
        @JavascriptInterface
        fun send(line: String) { pool.execute { core.callAttr("send", line) } }

        @JavascriptInterface
        fun openUrl(url: String) { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        core = Python.getInstance().getModule("shugotracker.mobile")
        core.callAttr("start", filesDir.absolutePath, Poster())
        // the page is served from https://appassets.androidplatform.net/ (ES modules don't load from file://)
        val assets = WebViewAssetLoader.Builder().addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build()
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.setBackgroundColor(0xFF0A0D13.toInt())
        web.addJavascriptInterface(Bridge(), "AndroidCore")
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assets.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == "appassets.androidplatform.net") return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))     // links open in the browser
                return true
            }
        }
        val q = intent.getStringExtra("q")?.let { "?q=" + Uri.encode(it) } ?: ""     // (a search to start with: CI's check)
        web.loadUrl("https://appassets.androidplatform.net/assets/www/index.html$q")
    }

    @Deprecated("Back: the page goes back a screen; on the main list, the app closes")
    override fun onBackPressed() {
        web.evaluateJavascript("window.__shugoBack ? window.__shugoBack() : false") { handled ->
            if (handled != "true") finish()
        }
    }
}
