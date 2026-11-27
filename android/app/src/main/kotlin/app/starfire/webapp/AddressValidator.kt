package app.starfire.webapp

import java.net.URI
import java.net.URISyntaxException

enum class AddressProblem { EMPTY, NOT_A_URL, NOT_HTTPS, NO_HOST, HAS_CREDENTIALS, BAD_HOST }

sealed interface AddressResult {
    data class Valid(val url: String, val host: String) : AddressResult
    data class Invalid(val problem: AddressProblem) : AddressResult
}

sealed interface ExtraHostsResult {
    data class Valid(val hosts: List<String>) : ExtraHostsResult
    data class Invalid(val entry: String, val problem: AddressProblem) : ExtraHostsResult
}

object AddressValidator {
    private const val HTTPS = "https"
    private const val SCHEME_SEPARATOR = "://"
    private const val MAX_HOST_LENGTH = 253
    private const val MAX_PORT = 65535
    private const val NO_PORT = -1
    private val hostLabel = Regex("[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
    private val entrySeparator = Regex("[,\\s]+")

    fun validate(input: String): AddressResult {
        val trimmed = input.trim()
        if (trimmed.isEmpty()) return invalid(AddressProblem.EMPTY)
        val addressText = withScheme(trimmed)
        if (addressText.substringAfter(SCHEME_SEPARATOR).isEmpty()) return invalid(AddressProblem.NO_HOST)
        val uri = parse(addressText) ?: return invalid(AddressProblem.NOT_A_URL)
        if (!uri.scheme.equals(HTTPS, ignoreCase = true)) return invalid(AddressProblem.NOT_HTTPS)
        if (uri.userInfo != null) return invalid(AddressProblem.HAS_CREDENTIALS)
        val host = uri.host?.lowercase() ?: return invalid(missingHostProblem(uri))
        if (!isRealHostName(host)) return invalid(AddressProblem.BAD_HOST)
        if (uri.port != NO_PORT && uri.port !in 1..MAX_PORT) return invalid(AddressProblem.NOT_A_URL)
        return AddressResult.Valid(normalised(uri, host), host)
    }

    fun parseExtraHosts(input: String): ExtraHostsResult {
        val hosts = linkedSetOf<String>()
        for (entry in input.split(entrySeparator).filter { it.isNotEmpty() }) {
            when (val result = validate(entry)) {
                is AddressResult.Invalid -> return ExtraHostsResult.Invalid(entry, result.problem)
                is AddressResult.Valid -> hosts.add(result.host)
            }
        }
        return ExtraHostsResult.Valid(hosts.toList())
    }

    fun allowedHosts(url: String, extraHosts: List<String>): Set<String> {
        val primary = parse(url)?.host?.lowercase() ?: return emptySet()
        return setOf(primary) + extraHosts.map { it.lowercase() }
    }

    private fun invalid(problem: AddressProblem) = AddressResult.Invalid(problem)

    private fun withScheme(text: String) = if (text.contains(SCHEME_SEPARATOR)) text else HTTPS + SCHEME_SEPARATOR + text

    private fun parse(text: String): URI? = try {
        URI(text)
    } catch (invalid: URISyntaxException) {
        null
    }

    private fun missingHostProblem(uri: URI) =
        when {
            uri.authority.isNullOrEmpty() -> AddressProblem.NO_HOST
            uri.authority.contains(":") -> AddressProblem.NOT_A_URL
            else -> AddressProblem.BAD_HOST
        }

    private fun isRealHostName(host: String): Boolean {
        if (host.length > MAX_HOST_LENGTH) return false
        val labels = host.split(".")
        return labels.size >= 2 && labels.all { hostLabel.matches(it) } && !labels.last().all { it.isDigit() }
    }

    private fun normalised(uri: URI, host: String): String {
        val port = if (uri.port == NO_PORT) "" else ":${uri.port}"
        val path = uri.rawPath.orEmpty().let { if (it.endsWith("/")) it else "$it/" }
        return "$HTTPS$SCHEME_SEPARATOR$host$port$path"
    }
}
