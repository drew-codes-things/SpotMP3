package app.starfire.webapp

class CrashLimiter(private val maxCrashes: Int, private val windowMillis: Long) {
    private val crashTimes = ArrayDeque<Long>()

    fun recordAndCheckExceeded(nowMillis: Long): Boolean {
        crashTimes.addLast(nowMillis)
        while (crashTimes.isNotEmpty() && nowMillis - crashTimes.first() > windowMillis) crashTimes.removeFirst()
        return crashTimes.size >= maxCrashes
    }
}
