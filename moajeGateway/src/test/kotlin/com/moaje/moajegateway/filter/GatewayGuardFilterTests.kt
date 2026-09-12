package com.moaje.moajegateway.filter

import com.moaje.moajegateway.config.GatewayGuardProperties
import jakarta.servlet.http.HttpServletRequest
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class GatewayGuardFilterTests {
    @Test
    @DisplayName("같은 키의 재요청과 본문 변경 요청 모두 Banking DB에서 판단하도록 전달한다")
    fun retriesReachBanking() {
        // given
        val filter = GatewayGuardFilter(GatewayGuardProperties())
        var calls = 0
        // when: Gateway는 기존 응답을 모르므로 Banking에 요청을 전달한다.
        listOf("1000", "1000", "2000").forEach { amount ->
            val request = MockHttpServletRequest("POST", "/api/v1/banking/transfers").apply {
                addHeader("Idempotency-Key", "retry-key")
                setContent("""{"amount":$amount}""".toByteArray())
            }
            filter.doFilter(request, MockHttpServletResponse()) { _, _ -> calls++ }
        }
        // then
        assertThat(calls).isEqualTo(3)
    }

    @Test
    @DisplayName("클라이언트가 위조한 내부 사용자 헤더를 제거한다")
    fun removesSpoofedHeaders() {
        // given
        val request = MockHttpServletRequest("GET", "/api/v1/assets/accounts").apply {
            addHeader("X-User-Id", "fake")
            addHeader("X-Authenticated-User-Id", "fake")
        }
        // when / then
        GatewayGuardFilter(GatewayGuardProperties()).doFilter(request, MockHttpServletResponse()) { forwarded, _ ->
            val http = forwarded as HttpServletRequest
            assertThat(http.getHeader("X-User-Id")).isNull()
            assertThat(http.getHeader("X-Authenticated-User-Id")).isNull()
        }
    }

    @Test
    @DisplayName("중복 헤더와 잘못된 형식의 멱등성 키는 400으로 거절한다")
    fun rejectsInvalidKeys() {
        // given
        listOf(listOf("bad key"), listOf("a", "b"), listOf("x".repeat(101))).forEach { keys ->
            val request = MockHttpServletRequest("POST", "/api/v1/banking/transfers")
            keys.forEach { request.addHeader("Idempotency-Key", it) }
            val response = MockHttpServletResponse()
            // when
            GatewayGuardFilter(GatewayGuardProperties()).doFilter(request, response) { _, _ -> error("잘못된 키") }
            // then
            assertThat(response.status).isEqualTo(400)
        }
    }
}

