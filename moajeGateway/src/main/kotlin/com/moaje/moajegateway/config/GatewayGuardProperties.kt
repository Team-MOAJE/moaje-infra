package com.moaje.moajegateway.config

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "moaje.gateway.guard")
data class GatewayGuardProperties(
    var traceHeaderName: String = "X-Trace-Id",
    var internalHeaders: Set<String> = setOf("X-User-Id", "X-User-Role", "X-User-Roles", "X-Authenticated-User-Id"),
)
