package com.moaje.moajegateway.filter

import com.moaje.moajegateway.config.GatewayGuardProperties
import jakarta.servlet.http.HttpServletRequest
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.mockito.Mockito
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class GatewayIdempotencyPolicyCharacterizationTest {
    @Test
    @DisplayName("현재 정책은 일반 unsafe method에 Idempotency-Key를 전역 필수 적용하지 않는다")
    fun currentPolicyDoesNotRequireIdempotencyKeyForEveryUnsafeMethod() {
        val properties = GatewayGuardProperties()
        val filter = GatewayGuardFilter(
            properties = properties,
        )
        val request = MockHttpServletRequest("POST", "/api/v1/profile").apply {
            contentType = MediaType.APPLICATION_JSON_VALUE
            setContent("""{"amount":1000}""".toByteArray(Charsets.UTF_8))
        }
        val response = MockHttpServletResponse()
        var passedRequest: HttpServletRequest? = null

        filter.doFilter(request, response) { servletRequest, servletResponse ->
            passedRequest = servletRequest as HttpServletRequest
            servletResponse as MockHttpServletResponse
            servletResponse.status = HttpStatus.OK.value()
        }

        assertThat(response.status).isEqualTo(HttpStatus.OK.value())
        assertThat(passedRequest).isNotNull()
    }

    @Test
    @DisplayName("현재 정책은 POST /api/v1/banking/transfers에 Idempotency-Key를 좁게 필수 적용한다")
    fun currentPolicyRequiresIdempotencyKeyForBankingTransferOnly() {
        val properties = GatewayGuardProperties()
        val filter = GatewayGuardFilter(
            properties = properties,
        )
        val request = MockHttpServletRequest("POST", "/api/v1/banking/transfers").apply {
            contentType = MediaType.APPLICATION_JSON_VALUE
            setContent("""{"amount":1000}""".toByteArray(Charsets.UTF_8))
        }
        val response = MockHttpServletResponse()

        filter.doFilter(request, response) { _, _ ->
            error("Banking transfer without Idempotency-Key must not pass the filter chain.")
        }

        assertThat(response.status).isEqualTo(HttpStatus.BAD_REQUEST.value())
        assertThat(response.contentAsString).contains("MISSING_IDEMPOTENCY_KEY")
    }
}
