package com.moaje.moajegateway.filter

import com.moaje.moajegateway.config.GatewayJwtProperties
import com.moaje.moajegateway.config.JwtContractNotConfigured
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.security.oauth2.jwt.JwtDecoder
import org.springframework.security.oauth2.jwt.JwtException
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 30)
class GatewayJwtFilter(private val decoder: JwtDecoder, private val properties: GatewayJwtProperties) : OncePerRequestFilter() {
    override fun shouldNotFilter(request: HttpServletRequest): Boolean =
        request.requestURI == "/actuator" || request.requestURI.startsWith("/actuator/") ||
            "${request.method} ${request.requestURI}" in properties.publicEndpoints

    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val headers = request.getHeaders("Authorization").toList()
        val header = headers.singleOrNull()
        if (header == null || !header.startsWith("Bearer ", ignoreCase = true) || header.substring(7).isBlank()) {
            reject(response, 401, "UNAUTHENTICATED")
            return
        }
        val jwt = try { decoder.decode(header.substring(7)) }
        catch (_: JwtContractNotConfigured) { reject(response, 503, "JWT_CONTRACT_NOT_CONFIGURED"); return }
        catch (_: JwtException) { reject(response, 401, "INVALID_TOKEN"); return }

        // sub는 서명 검증이 끝난 뒤에만 신뢰한다. 클라이언트가 같은 이름으로 보낸 헤더는 덮어쓴다.
        // Controller마다 JWT를 해석하지 않아도 downstream의 공통 필터가 이 값으로 Principal을 만든다.
        chain.doFilter(SanitizedHeaderHttpServletRequest(request, setOf("X-Authenticated-User-Id"),
            mapOf("X-Authenticated-User-Id" to jwt.subject)), response)
    }

    private fun reject(response: HttpServletResponse, status: Int, code: String) {
        response.status = status
        response.contentType = "application/json"
        if (status == 401) response.setHeader("WWW-Authenticate", "Bearer")
        response.writer.write("""{"code":"$code"}""")
    }
}
