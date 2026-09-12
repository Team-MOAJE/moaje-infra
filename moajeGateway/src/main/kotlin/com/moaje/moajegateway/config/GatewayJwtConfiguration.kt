package com.moaje.moajegateway.config

import org.springframework.boot.context.properties.ConfigurationProperties
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator
import org.springframework.security.oauth2.core.OAuth2Error
import org.springframework.security.oauth2.core.OAuth2TokenValidator
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm
import org.springframework.security.oauth2.jwt.*
import org.springframework.http.client.SimpleClientHttpRequestFactory
import org.springframework.web.client.RestTemplate

@ConfigurationProperties("moaje.gateway.jwt")
data class GatewayJwtProperties(
    var issuer: String = "",
    var audience: String = "",
    var jwkSetUri: String = "",
    var algorithm: String = "",
    // 회의에서 로그인·토큰 갱신의 정확한 METHOD와 경로를 정한 뒤 "POST /api/v1/auth/..." 형태로 넣는다.
    // /auth/** 전체를 열면 개인정보 수정 API까지 인증을 건너뛸 수 있으므로 와일드카드는 지원하지 않는다.
    var publicEndpoints: Set<String> = emptySet(),
)

class JwtContractNotConfigured : RuntimeException()

@Configuration
class GatewayJwtConfiguration {
    /**
     * 회의 후 Auth 팀이 알려준 발급자(issuer), 사용 대상(audience), 공개키 주소(JWKS), 서명 방식을 설정한다.
     * 공개키는 서명 확인용이다. Auth의 비밀키나 사용자의 JWT를 설정 파일에 복사하는 것이 아니다.
     * 아직 합의하지 않은 값을 추측하지 않도록 빈 설정에서는 요청을 차단하고, 서버 기동 자체는 허용한다.
     */
    @Bean
    fun gatewayJwtDecoder(properties: GatewayJwtProperties): JwtDecoder {
        if (listOf(properties.issuer, properties.audience, properties.jwkSetUri, properties.algorithm).any(String::isBlank)) {
            return JwtDecoder { throw JwtContractNotConfigured() }
        }
        require(properties.algorithm in setOf("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")) {
            "합의된 비대칭 JWT 서명 방식만 허용합니다."
        }
        val uri = java.net.URI(properties.jwkSetUri)
        require(uri.scheme == "https" || (uri.scheme == "http" && uri.host in setOf("localhost", "127.0.0.1"))) {
            "JWKS는 HTTPS 주소여야 합니다. HTTP는 로컬 테스트에서만 허용합니다."
        }
        val requestFactory = SimpleClientHttpRequestFactory().apply {
            setConnectTimeout(2000)
            setReadTimeout(2000)
        }
        return NimbusJwtDecoder.withJwkSetUri(properties.jwkSetUri)
            .jwsAlgorithm(SignatureAlgorithm.from(properties.algorithm))
            .restOperations(RestTemplate(requestFactory)).build().apply {
                setJwtValidator(contractValidator(properties))
            }
    }

    companion object {
        fun contractValidator(properties: GatewayJwtProperties): OAuth2TokenValidator<Jwt> =
            DelegatingOAuth2TokenValidator(JwtValidators.createDefaultWithIssuer(properties.issuer),
                OAuth2TokenValidator { jwt ->
                    if (jwt.expiresAt != null && jwt.audience.contains(properties.audience) &&
                        jwt.subject?.matches(Regex("[A-Za-z0-9._:@-]{1,100}")) == true) {
                        OAuth2TokenValidatorResult.success()
                    } else OAuth2TokenValidatorResult.failure(OAuth2Error("invalid_token", "Required identity claims are invalid.", null))
                })
    }
}
