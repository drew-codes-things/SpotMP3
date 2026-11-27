package app.starfire.webapp

import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import kotlin.test.Test
import kotlin.test.assertEquals

class ReachabilityTest {
    @Test
    fun failuresAreSortedIntoUserFacingCauses() {
        assertEquals(Reachability.UNKNOWN_HOST, Reachability.classify(UnknownHostException("x")))
        assertEquals(Reachability.TLS_PROBLEM, Reachability.classify(SSLHandshakeException("x")))
        assertEquals(Reachability.TIMEOUT, Reachability.classify(SocketTimeoutException("x")))
        assertEquals(Reachability.UNREACHABLE, Reachability.classify(java.io.IOException("x")))
    }
}
