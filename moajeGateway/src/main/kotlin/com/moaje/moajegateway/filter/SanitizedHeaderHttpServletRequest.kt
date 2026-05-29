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

    // blockedHeader set의 요소를 소문자로 가공하여 blocked 에 새로운 set을 할당
    private val blocked = blockedHeaders.map { it.lowercase(Locale.ROOT) }.toSet()

    // addedHeaders Map의 key 값을 모두 소문자로 바꾸어 added 라는 Map 을 다시 만듦
    private val added = addedHeaders.mapKeys { it.key.lowercase(Locale.ROOT) }

    // addedHeaders Map의 key 값만 모아둔 Set 의 요소와 그 원본요소의 값을 소문자로 바꾸어 연관짓는(associateBy) Map을 만든다.
    // associateBy 중괄호 안에 있는 로직의 결과값을 Key로 하며 그 원본 key 값을 value로 하는 Map을 생성한다.
    private val originalAddedNames = addedHeaders.keys.associateBy { it.lowercase(Locale.ROOT) }

    // 인자로 받은 헤더이름(name)을 찾아 헤더를 반환한다.
    // 단, x-trace-id의 경우 gateway가 만든 x-trace-id만 포함시키기 위해 added에 있는 x-trace-id만 포함시킨다.
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

    // 인자로 받은 헤더이름(name)을 찾아 헤더리스트를 반환한다.
    // 단, x-trace-id의 경우 gateway가 만든 x-trace-id만 포함시키기 위해 added에 있는 x-trace-id만 포함시킨다.
    override fun getHeaders(name: String): Enumeration<String> {
        val normalized = name.lowercase(Locale.ROOT)
        if (normalized in added) {
            // 해당 클래스의 ServletAPI 스펙에 맞추어 반환값인 "Enumeration<String>" 으로 바꾸어서 반환
            return Collections.enumeration(listOfNotNull(added[normalized]))
        }
        if (normalized in blocked) {
            return Collections.emptyEnumeration()
        }
        return super.getHeaders(name)
    }

    // getHeaderNames를 통해 blocked에 포함된 header 이름은 포함시키지 않는다.
    // 그리고 다시 x-trace-id 헤더를 names.addAll 해서 원본Request에 있던 x-trace-id를 숨기고,
    // gateway에서 생성한 x-trace-id 헤더와 그 값을 넣은 값(names)을 반환한다.
    override fun getHeaderNames(): Enumeration<String> {
        val names = super.getHeaderNames().toList()
            .filterNot { it.lowercase(Locale.ROOT) in blocked } // 중괄호 안에있는 로직의 결과값이 false 인 대상만 수집
            .toMutableSet() // 수정가능한(mutable) set 으로 변환
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
