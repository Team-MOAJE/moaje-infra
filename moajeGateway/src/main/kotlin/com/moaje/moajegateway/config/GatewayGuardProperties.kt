package com.moaje.moajegateway.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties(prefix = "moaje.gateway.guard")
data class GatewayGuardProperties(
    var traceHeaderName: String = "X-Trace-Id",
    var internalHeaders: Set<String> = setOf(
        "X-User-Id",
        "X-User-Role",
        "X-User-Roles",
        "X-Authenticated-User-Id",
    ),
    var idempotency: Idempotency = Idempotency(),
) {
    data class Idempotency(
        var enabled: Boolean = true,
        var headerName: String = "Idempotency-Key",
        var keyPrefix: String = "moaje:gateway:idempotency:",
        var ttl: Duration = Duration.ofMinutes(10),
        var failClosed: Boolean = true,
        var requireForUnsafeMethods: Boolean = false,
        var maxBodyBytes: Int = 1_048_576,
        var methods: Set<String> = setOf("POST", "PUT", "PATCH", "DELETE"),
        var excludedPathPrefixes: Set<String> = setOf("/actuator"),
    )
}
