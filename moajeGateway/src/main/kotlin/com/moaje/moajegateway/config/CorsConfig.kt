package com.moaje.moajegateway.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.cors.CorsConfiguration
import org.springframework.web.cors.UrlBasedCorsConfigurationSource
import org.springframework.web.filter.CorsFilter

@Configuration
class CorsConfig {

    @Bean
    fun corsFilter(): CorsFilter {
        val configuration = CorsConfiguration().apply {
            allowedOriginPatterns = listOf("*")
            allowedMethods = listOf("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
            allowedHeaders = listOf(
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Trace-Id",
            )
            exposedHeaders = listOf("X-Trace-Id")
            allowCredentials = true
            maxAge = 3600
        }

        return CorsFilter(UrlBasedCorsConfigurationSource().apply {
            registerCorsConfiguration("/**", configuration)
        })
    }
}
