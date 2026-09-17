package com.moaje.moajegateway.config

import org.springframework.boot.context.properties.ConfigurationProperties
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.convert.converter.Converter
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator
import org.springframework.security.oauth2.core.OAuth2Error
import org.springframework.security.oauth2.core.OAuth2TokenValidator
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult
import org.springframework.security.oauth2.jose.jws.MacAlgorithm
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm
import org.springframework.security.oauth2.jwt.*
import org.springframework.http.client.SimpleClientHttpRequestFactory
import org.springframework.web.client.RestTemplate
import javax.crypto.spec.SecretKeySpec

@ConfigurationProperties("moaje.gateway.jwt")
data class GatewayJwtProperties(
    var issuer: String = "",
    var audience: String = "",
    var jwkSetUri: String = "",
    var algorithm: String = "",
    var secretKey: String = "",
    // 로그인·갱신·토큰 검증처럼 자체 자격정보로 동작하는 API만 "POST /api/v1/auth/..." 형태로 넣는다.
    // /auth/** 전체를 열면 개인정보 수정 API까지 인증을 건너뛸 수 있으므로 와일드카드는 지원하지 않는다.
    var publicEndpoints: Set<String> = emptySet(),
)

class JwtContractNotConfigured : RuntimeException()

@Configuration
class GatewayJwtConfiguration {
    /**
     * Auth의 현재 HS256은 두 서비스에 같은 비밀키를 설정하고, 향후 RS/ES 전환 시에는 JWKS 공개키를 사용한다.
     * 필요한 키가 비어 있으면 검증을 우회하지 않고 해당 요청을 503으로 차단한다.
     */
    @Bean
    fun gatewayJwtDecoder(properties: GatewayJwtProperties): JwtDecoder {
        if (properties.issuer.isBlank() || properties.algorithm.isBlank()) {
            return JwtDecoder { throw JwtContractNotConfigured() }
        }

        val algorithm = properties.algorithm.uppercase()
        require(algorithm in setOf("HS256", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512")) {
            "지원하지 않는 JWT 서명 방식입니다."
        }
        if ((algorithm == "HS256" && properties.secretKey.isBlank()) ||
            (algorithm != "HS256" && properties.jwkSetUri.isBlank())
        ) {
            return JwtDecoder { throw JwtContractNotConfigured() }
        }

        val decoder = when (algorithm) {
            "HS256" -> hmacDecoder(properties)
            "RS256", "RS384", "RS512", "ES256", "ES384", "ES512" -> jwkDecoder(properties)
            else -> error("앞의 서명 방식 검증을 통과할 수 없습니다.")
        }

        // Nimbus는 iat가 없는 토큰에도 내부 issuedAt 값을 보충할 수 있다.
        // 따라서 변환 전 payload에 iat가 실제로 있었는지를 표시해 Auth의 필수 Claim 계약을 검사한다.
        val defaultClaimConverter: Converter<Map<String, Any>, Map<String, Any>> =
            MappedJwtClaimSetConverter.withDefaults(emptyMap())
        return decoder.apply {
            setClaimSetConverter { sourceClaims ->
                defaultClaimConverter.convert(sourceClaims).toMutableMap().apply {
                    this[IAT_PRESENT_MARKER] = sourceClaims["iat"] != null
                }
            }
            setJwtValidator(contractValidator(properties))
        }
    }

    private fun hmacDecoder(properties: GatewayJwtProperties): NimbusJwtDecoder {
        require(properties.secretKey.toByteArray(Charsets.UTF_8).size >= 32) {
            "HS256 비밀키는 UTF-8 기준 32바이트 이상이어야 합니다."
        }
        val key = SecretKeySpec(properties.secretKey.toByteArray(Charsets.UTF_8), "HmacSHA256")
        return NimbusJwtDecoder.withSecretKey(key)
            .macAlgorithm(MacAlgorithm.HS256)
            .build()
    }

    private fun jwkDecoder(properties: GatewayJwtProperties): NimbusJwtDecoder {
        val uri = java.net.URI(properties.jwkSetUri)
        require(uri.scheme == "https" || (uri.scheme == "http" && uri.host in setOf("localhost", "127.0.0.1"))) {
            "JWKS는 HTTPS 주소여야 합니다. HTTP는 로컬 테스트에서만 허용합니다."
        }
        val requestFactory = SimpleClientHttpRequestFactory().apply {
            setConnectTimeout(2000)
            setReadTimeout(2000)
        }
        return NimbusJwtDecoder.withJwkSetUri(properties.jwkSetUri)
            .jwsAlgorithm(SignatureAlgorithm.from(properties.algorithm.uppercase()))
            .restOperations(RestTemplate(requestFactory))
            .build()
    }

    companion object {
        fun contractValidator(properties: GatewayJwtProperties): OAuth2TokenValidator<Jwt> =
            DelegatingOAuth2TokenValidator(JwtValidators.createDefaultWithIssuer(properties.issuer),
                OAuth2TokenValidator { jwt ->
                    val validAudience = properties.audience.isBlank() || jwt.audience.contains(properties.audience)
                    val validClaims = jwt.expiresAt != null && jwt.getClaimAsBoolean(IAT_PRESENT_MARKER) == true &&
                        !jwt.getClaimAsString("jti").isNullOrBlank() &&
                        jwt.getClaimAsString("typ") == "access" &&
                        jwt.subject?.matches(Regex("[0-9]{1,19}")) == true
                    if (validAudience && validClaims) {
                        OAuth2TokenValidatorResult.success()
                    } else OAuth2TokenValidatorResult.failure(OAuth2Error("invalid_token", "Required identity claims are invalid.", null))
                })

        private const val IAT_PRESENT_MARKER = "moaje_internal_iat_present"
    }
}
