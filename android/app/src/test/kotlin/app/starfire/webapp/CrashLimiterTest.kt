package app.starfire.webapp

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CrashLimiterTest {
    @Test
    fun threeCrashesInAMinuteAreTooMany() {
        val limiter = CrashLimiter(maxCrashes = 3, windowMillis = 60_000)
        assertFalse(limiter.recordAndCheckExceeded(0))
        assertFalse(limiter.recordAndCheckExceeded(10_000))
        assertTrue(limiter.recordAndCheckExceeded(20_000))
    }

    @Test
    fun oldCrashesFallOutOfTheWindow() {
        val limiter = CrashLimiter(maxCrashes = 3, windowMillis = 60_000)
        limiter.recordAndCheckExceeded(0)
        limiter.recordAndCheckExceeded(10_000)
        assertFalse(limiter.recordAndCheckExceeded(70_001))
    }
}
