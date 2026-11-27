package app.starfire.webapp

import android.content.Context

class AddressStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun url(): String? = preferences.getString(KEY_URL, null) ?: BuildConfig.DEFAULT_URL.ifEmpty { null }

    fun extraHosts(): List<String> =
        splitHosts(preferences.getString(KEY_EXTRA_HOSTS, null) ?: BuildConfig.DEFAULT_EXTRA_HOSTS)

    fun save(url: String, extraHosts: List<String>) {
        preferences.edit()
            .putString(KEY_URL, url)
            .putString(KEY_EXTRA_HOSTS, extraHosts.joinToString(","))
            .apply()
    }

    private fun splitHosts(text: String) = text.split(",").map { it.trim() }.filter { it.isNotEmpty() }

    private companion object {
        const val PREFERENCES_NAME = "address"
        const val KEY_URL = "url"
        const val KEY_EXTRA_HOSTS = "extra_hosts"
    }
}
