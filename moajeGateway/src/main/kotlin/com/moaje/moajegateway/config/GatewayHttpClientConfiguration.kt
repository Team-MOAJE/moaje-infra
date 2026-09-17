package com.moaje.moajegateway.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.client.ClientHttpRequestFactory
import org.springframework.http.client.JdkClientHttpRequestFactory
import java.net.http.HttpClient

@Configuration
class GatewayHttpClientConfiguration {
    /**
     * 현재 내부 서비스는 모두 HTTP/1.1로 통신한다.
     * 버전을 명시하지 않으면 JDK Client가 h2c 전환을 제안해 Uvicorn이 일반 요청을 거부할 수 있다.
     */
    @Bean
    fun gatewayClientHttpRequestFactory(): ClientHttpRequestFactory =
        JdkClientHttpRequestFactory(
            HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .build(),
        )
}
