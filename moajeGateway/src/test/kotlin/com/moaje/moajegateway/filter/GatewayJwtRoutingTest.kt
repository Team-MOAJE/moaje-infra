package com.moaje.moajegateway.filter

import com.nimbusds.jose.JWSAlgorithm
import com.nimbusds.jose.JWSHeader
import com.nimbusds.jose.crypto.RSASSASigner
import com.nimbusds.jose.jwk.JWKSet
import com.nimbusds.jose.jwk.RSAKey
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator
import com.nimbusds.jwt.JWTClaimsSet
import com.nimbusds.jwt.SignedJWT
import com.sun.net.httpserver.HttpServer
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.beans.factory.annotation.Value
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import java.net.InetSocketAddress
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Instant
import java.util.Date

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class GatewayJwtRoutingTest {
    @Value("\${local.server.port}") private var port: Int = 0

    @Test
    @DisplayName("실제 JWT 서명 검증 후 라우팅된 HTTP 요청에는 검증된 sub만 전달된다")
    fun verifiedSubjectReachesDownstream() {
        // given: 키는 매 테스트 실행 시 생성하며 외부 사용자 토큰이나 비밀키를 저장하지 않는다.
        val token = token()
        // when: 가짜 사용자 헤더와 정상 JWT를 함께 보낸다.
        val response = call(token)
        // then: 실제 Gateway HTTP 라우팅 결과까지 확인한다. wrapper 단위 테스트만으로 대체하지 않는다.
        assertThat(response.statusCode()).isEqualTo(200)
        assertThat(response.body()).isEqualTo("verified-user")
    }

    @Test
    @DisplayName("만료·잘못된 발급자·대상·서명·알고리즘의 JWT는 모두 401이다")
    fun rejectsInvalidTokens() {
        // given
        val invalid = listOf(
            token(expiration = Instant.now().minusSeconds(600)),
            token(issuer = "wrong-issuer"), token(audience = "wrong-audience"),
            token(key = RSAKeyGenerator(2048).keyID("other").generate()),
            token(algorithm = JWSAlgorithm.RS512), token(subject = ""), token(includeExpiration = false),
        )
        // when / then
        invalid.forEach { assertThat(call(it).statusCode()).isEqualTo(401) }
    }

    @Test
    @DisplayName("JWT 없이 내부 사용자 헤더만 위조한 요청은 라우팅하지 않는다")
    fun rejectsHeaderSpoofing() {
        // given / when
        val response = call(null)
        // then
        assertThat(response.statusCode()).isEqualTo(401)
        assertThat(call("").statusCode()).isEqualTo(401)
    }

    private fun call(token: String?): HttpResponse<String> {
        val builder = HttpRequest.newBuilder(URI("http://localhost:$port/api/v1/assets/accounts"))
            .header("X-Authenticated-User-Id", "spoofed-user").GET()
        token?.let { builder.header("Authorization", "Bearer $it") }
        return HttpClient.newHttpClient().send(builder.build(), HttpResponse.BodyHandlers.ofString())
    }

    private fun token(
        issuer: String = "test-auth", audience: String = "test-api", subject: String = "verified-user",
        expiration: Instant = Instant.now().plusSeconds(300), key: RSAKey = rsa,
        algorithm: JWSAlgorithm = JWSAlgorithm.RS256, includeExpiration: Boolean = true,
    ): String {
        val claims = JWTClaimsSet.Builder().issuer(issuer).audience(audience).subject(subject)
        if (includeExpiration) claims.expirationTime(Date.from(expiration))
        return SignedJWT(JWSHeader.Builder(algorithm).keyID(key.keyID).build(), claims.build())
            .apply { sign(RSASSASigner(key)) }.serialize()
    }

    companion object {
        private val rsa = RSAKeyGenerator(2048).keyID("test-key").generate()
        private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/jwks") { exchange ->
                val body = JWKSet(rsa.toPublicJWK()).toString().toByteArray()
                exchange.responseHeaders.set("Content-Type", "application/json")
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
            }
            createContext("/api/v1/assets/") { exchange ->
                val body = exchange.requestHeaders.getFirst("X-Authenticated-User-Id").orEmpty().toByteArray()
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
            }
            start()
        }
        @JvmStatic @DynamicPropertySource
        fun properties(registry: DynamicPropertyRegistry) {
            registry.add("moaje.gateway.jwt.issuer") { "test-auth" }
            registry.add("moaje.gateway.jwt.audience") { "test-api" }
            registry.add("moaje.gateway.jwt.algorithm") { "RS256" }
            registry.add("moaje.gateway.jwt.jwk-set-uri") { "http://127.0.0.1:${server.address.port}/jwks" }
            registry.add("ASSET_SERVICE_URI") { "http://127.0.0.1:${server.address.port}" }
        }
        @JvmStatic @AfterAll fun stopServer() { server.stop(0) }
    }
}
