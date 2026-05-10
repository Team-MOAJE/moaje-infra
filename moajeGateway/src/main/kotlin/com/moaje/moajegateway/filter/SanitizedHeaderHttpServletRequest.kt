package com.moaje.moajegateway.filter

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletRequestWrapper
import java.util.Collections
import java.util.Enumeration
import java.util.Locale

class SanitizedHeaderHttpServletRequest(
    request: HttpServletRequest,
    blockedHeaders: Set<String>,
    private val addedHeaders: Map<String, String>,
) : HttpServletRequestWrapper(request) {

    private val blocked = blockedHeaders.map { it.lowercase(Locale.ROOT) }.toSet()
    private val added = addedHeaders.mapKeys { it.key.lowercase(Locale.ROOT) }
    private val originalAddedNames = addedHeaders.keys.associateBy { it.lowercase(Locale.ROOT) }

    override fun getHeader(name: String): String? {
        val normalized = name.lowercase(Locale.ROOT)
        if (normalized in added) {
            return added[normalized]
        }
        if (normalized in blocked) {
            return null
        }
        return super.getHeader(name)
    }

    override fun getHeaders(name: String): Enumeration<String> {
        val normalized = name.lowercase(Locale.ROOT)
        if (normalized in added) {
            return Collections.enumeration(listOfNotNull(added[normalized]))
        }
        if (normalized in blocked) {
            return Collections.emptyEnumeration()
        }
        return super.getHeaders(name)
    }

    override fun getHeaderNames(): Enumeration<String> {
        val names = super.getHeaderNames().toList()
            .filterNot { it.lowercase(Locale.ROOT) in blocked }
            .toMutableSet()
        names.addAll(originalAddedNames.values)
        return Collections.enumeration(names)
    }

    private fun <T> Enumeration<T>.toList(): List<T> {
        val values = mutableListOf<T>()
        while (hasMoreElements()) {
            values.add(nextElement())
        }
        return values
    }
}
