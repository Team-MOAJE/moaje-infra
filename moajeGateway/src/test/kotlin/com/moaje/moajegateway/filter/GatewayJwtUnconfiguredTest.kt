package com.moaje.moajegateway.filter

import com.moaje.moajegateway.config.GatewayJwtConfiguration
import com.moaje.moajegateway.config.GatewayJwtProperties
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class GatewayJwtUnconfiguredTest {
    @Test
    @DisplayName("Auth 규격이 미설정이면 토큰이 있어도 503으로 차단하며 임시 사용자를 만들지 않는다")
    fun failsClosedUntilMeetingContractIsConfigured() {
        // given
        val properties = GatewayJwtProperties()
        val filter = GatewayJwtFilter(GatewayJwtConfiguration().gatewayJwtDecoder(properties), properties)
        val request = MockHttpServletRequest("GET", "/api/v1/assets/accounts").apply {
            addHeader("Authorization", "Bearer unverified")
        }
        val response = MockHttpServletResponse()
        // when
        filter.doFilter(request, response) { _, _ -> error("미설정 인증을 허용하면 안 됩니다.") }
        // then
        assertThat(response.status).isEqualTo(503)
        assertThat(response.contentAsString).contains("JWT_CONTRACT_NOT_CONFIGURED")
    }
}
