package app.starfire.webapp

import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import javax.net.ssl.SSLException

enum class Reachability {
    REACHABLE, UNKNOWN_HOST, TLS_PROBLEM, TIMEOUT, UNREACHABLE;

    companion object {
        private const val TIMEOUT_MILLIS = 8000

        fun classify(failure: IOException): Reachability = when (failure) {
            is UnknownHostException -> UNKNOWN_HOST
            is SSLException -> TLS_PROBLEM
            is SocketTimeoutException -> TIMEOUT
            else -> UNREACHABLE
        }

        fun check(url: String): Reachability {
            val connection = URL(url).openConnection() as HttpURLConnection
            return try {
                connection.requestMethod = "HEAD"
                connection.connectTimeout = TIMEOUT_MILLIS
                connection.readTimeout = TIMEOUT_MILLIS
                connection.instanceFollowRedirects = false
                connection.responseCode
                REACHABLE
            } catch (failure: IOException) {
                classify(failure)
            } finally {
                connection.disconnect()
            }
        }
    }
}
