package com.moaje.moajegateway.config

import com.nimbusds.jose.JWSAlgorithm
import com.nimbusds.jose.JWSHeader
import com.nimbusds.jose.crypto.MACSigner
import com.nimbusds.jwt.JWTClaimsSet
import com.nimbusds.jwt.SignedJWT
import org.assertj.core.api.Assertions.assertThat
import org.assertj.core.api.Assertions.assertThatThrownBy
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.springframework.security.oauth2.jwt.JwtException
import java.time.Instant
import java.util.Date

class GatewayJwtHmacTest {
    private val secret = "test-auth-secret-key-that-is-at-least-32-bytes"
    private val properties = GatewayJwtProperties(
        issuer = "moaje-auth",
        algorithm = "HS256",
        secretKey = secret,
    )

    @Test
    @DisplayName("Auth의 HS256 Access Token과 숫자형 문자열 sub를 검증한다")
    fun decodesCurrentAuthAccessToken() {
        // given
        val token = token()
        // when
        val jwt = GatewayJwtConfiguration().gatewayJwtDecoder(properties).decode(token)
        // then
        assertThat(jwt.subject).isEqualTo("123456789")
    }

    @Test
    @DisplayName("서명이 맞아도 Access Token 필수 Claim이 다르면 거절한다")
    fun rejectsInvalidAccessTokenClaims() {
        // given
        val decoder = GatewayJwtConfiguration().gatewayJwtDecoder(properties)
        val invalidTokens = listOf(token(type = "refresh"), token(subject = "user-123"), token(includeTokenId = false))
        // when / then
        invalidTokens.forEach { invalid ->
            assertThatThrownBy { decoder.decode(invalid) }.isInstanceOf(JwtException::class.java)
        }
    }

    private fun token(
        type: String = "access",
        subject: String = "123456789",
        includeTokenId: Boolean = true,
    ): String {
        val now = Instant.now()
        val claims = JWTClaimsSet.Builder()
            .issuer("moaje-auth")
            .subject(subject)
            .claim("typ", type)
            .issueTime(Date.from(now))
            .expirationTime(Date.from(now.plusSeconds(300)))
        if (includeTokenId) claims.jwtID("test-jti")
        return SignedJWT(JWSHeader.Builder(JWSAlgorithm.HS256).build(), claims.build())
            .apply { sign(MACSigner(secret)) }
            .serialize()
    }
}
