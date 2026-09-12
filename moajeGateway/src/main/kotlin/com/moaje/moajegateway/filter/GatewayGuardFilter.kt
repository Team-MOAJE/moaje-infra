package com.moaje.moajegateway.filter

import com.moaje.moajegateway.config.GatewayGuardProperties
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import java.util.UUID

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
class GatewayGuardFilter(private val properties: GatewayGuardProperties) : OncePerRequestFilter() {
    /**
     * 외부 요청의 사용자 헤더는 지우고, 뒤의 JWT 필터가 검증한 값만 다시 채우게 한다.
     * Gateway가 재요청을 차단하면 Banking의 기존 결과를 돌려줄 수 없으므로 Redis 선점은 하지 않는다.
     * 여기서는 송금 헤더의 형식만 검사하고 본문 비교와 중복 판단은 Banking DB가 담당한다.
     */
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val traceId = UUID.randomUUID().toString()
        response.setHeader(properties.traceHeaderName, traceId)
        val guarded = SanitizedHeaderHttpServletRequest(request,
            properties.internalHeaders + setOf("X-Authenticated-User-Id", properties.traceHeaderName),
            mapOf(properties.traceHeaderName to traceId))

        if (request.method == "POST" && request.requestURI == "/api/v1/banking/transfers") {
            val keys = request.getHeaders("Idempotency-Key").toList()
            val key = keys.singleOrNull()
            if (key == null || !key.matches(Regex("[A-Za-z0-9._:-]{1,100}"))) {
                response.status = 400
                response.contentType = "application/json"
                val code = if (keys.isEmpty()) "MISSING_IDEMPOTENCY_KEY" else "INVALID_IDEMPOTENCY_KEY"
                response.writer.write("""{"code":"$code","message":"A single valid Idempotency-Key is required."}""")
                return
            }
        }
        chain.doFilter(guarded, response)
    }
}
