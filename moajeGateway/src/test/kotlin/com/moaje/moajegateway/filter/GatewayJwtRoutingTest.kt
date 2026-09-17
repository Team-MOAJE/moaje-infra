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
import java.util.concurrent.atomic.AtomicReference

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
        assertThat(response.body()).isEqualTo("123456789")
    }

    @Test
    @DisplayName("만료·잘못된 발급자·대상·서명·알고리즘의 JWT는 모두 401이다")
    fun rejectsInvalidTokens() {
        // given
        val invalid = mapOf(
            "expired" to token(expiration = Instant.now().minusSeconds(600)),
            "issuer" to token(issuer = "wrong-issuer"),
            "audience" to token(audience = "wrong-audience"),
            "signature" to token(key = RSAKeyGenerator(2048).keyID("other").generate()),
            "algorithm" to token(algorithm = JWSAlgorithm.RS512),
            "subject" to token(subject = "user-123"),
            "expiration" to token(includeExpiration = false),
            "type" to token(type = "refresh"),
            "token-id" to token(includeTokenId = false),
            "issued-at" to token(includeIssuedAt = false),
        )
        // when / then
        invalid.forEach { (case, token) ->
            assertThat(call(token).statusCode()).describedAs(case).isEqualTo(401)
        }
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

    @Test
    @DisplayName("공개 로그인 경로는 JWT 없이 Auth의 실제 경로로 변환된다")
    fun rewritesPublicAuthPath() {
        // given / when: Client는 공통 /api/v1 경로를 사용한다.
        val request = HttpRequest.newBuilder(URI("http://localhost:$port/api/v1/auth/login"))
            .POST(HttpRequest.BodyPublishers.ofString("{}"))
            .build()
        val response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString())
        // then: Auth에는 실제 구현 경로인 /api/auth/login이 전달된다.
        assertThat(response.statusCode()).isEqualTo(200)
        assertThat(response.body()).isEqualTo("/api/auth/login")
        assertThat(authUpgradeHeader.get()).isNull()
    }

    @Test
    @DisplayName("Auth와 Asset, Banking 문서 경로는 JWT 없이 각 서비스 OpenAPI 경로로 전달된다")
    fun routesSwaggerDocumentsWithoutJwt() {
        mapOf(
            "auth/openapi.json" to "/openapi.json",
            "asset/v3/api-docs" to "/v3/api-docs",
            "banking/v3/api-docs" to "/v3/api-docs",
        ).forEach { (documentPath, downstreamPath) ->
            val request = HttpRequest.newBuilder(
                URI("http://localhost:$port/docs/$documentPath"),
            ).GET().build()
            val response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString())

            assertThat(response.statusCode()).describedAs(documentPath).isEqualTo(200)
            assertThat(response.body()).isEqualTo(downstreamPath)
        }
    }

    @Test
    @DisplayName("통합 Swagger 화면은 세 서비스의 문서를 선택할 수 있다")
    fun servesIntegratedSwaggerUiWithoutJwt() {
        val request = HttpRequest.newBuilder(
            URI("http://localhost:$port/docs/swagger-ui.html"),
        ).GET().build()

        val response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString())

        assertThat(response.statusCode()).isEqualTo(200)
        assertThat(response.body()).contains("/docs/auth/openapi.json")
        assertThat(response.body()).contains("/docs/banking/v3/api-docs")
        assertThat(response.body()).contains("/docs/asset/v3/api-docs")
        assertThat(response.body()).contains("persistAuthorization: true")
        assertThat(response.body()).contains("url.pathname.startsWith('/api/auth/')")
        assertThat(response.body()).contains("'/api/v1' + url.pathname")
    }

    private fun call(token: String?): HttpResponse<String> {
        val builder = HttpRequest.newBuilder(URI("http://localhost:$port/api/v1/assets/accounts"))
            .header("X-Authenticated-User-Id", "spoofed-user").GET()
        token?.let { builder.header("Authorization", "Bearer $it") }
        return HttpClient.newHttpClient().send(builder.build(), HttpResponse.BodyHandlers.ofString())
    }

    private fun token(
        issuer: String = "test-auth", audience: String = "test-api", subject: String = "123456789",
        expiration: Instant = Instant.now().plusSeconds(300), key: RSAKey = rsa,
        algorithm: JWSAlgorithm = JWSAlgorithm.RS256, includeExpiration: Boolean = true,
        type: String = "access", includeTokenId: Boolean = true, includeIssuedAt: Boolean = true,
    ): String {
        val claims = JWTClaimsSet.Builder().issuer(issuer).audience(audience).subject(subject)
            .claim("typ", type)
        if (includeTokenId) claims.jwtID("test-jti")
        if (includeIssuedAt) claims.issueTime(Date.from(Instant.now()))
        if (includeExpiration) claims.expirationTime(Date.from(expiration))
        return SignedJWT(JWSHeader.Builder(algorithm).keyID(key.keyID).build(), claims.build())
            .apply { sign(RSASSASigner(key)) }.serialize()
    }

    companion object {
        private val rsa = RSAKeyGenerator(2048).keyID("test-key").generate()
        private val authUpgradeHeader = AtomicReference<String?>()
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
            createContext("/api/auth/login") { exchange ->
                authUpgradeHeader.set(exchange.requestHeaders.getFirst("Upgrade"))
                val body = exchange.requestURI.path.toByteArray()
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
            }
            createContext("/v3/api-docs") { exchange ->
                val body = exchange.requestURI.path.toByteArray()
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
            }
            createContext("/openapi.json") { exchange ->
                val body = exchange.requestURI.path.toByteArray()
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
            registry.add("BANKING_SERVICE_URI") { "http://127.0.0.1:${server.address.port}" }
            registry.add("AUTH_SERVICE_URI") { "http://127.0.0.1:${server.address.port}" }
            registry.add("moaje.gateway.jwt.public-endpoints[0]") { "POST /api/v1/auth/login" }
        }
        @JvmStatic @AfterAll fun stopServer() { server.stop(0) }
    }
}
