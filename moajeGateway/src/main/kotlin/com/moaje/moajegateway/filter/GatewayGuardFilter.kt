package com.moaje.moajegateway.filter

import com.fasterxml.jackson.databind.ObjectMapper
import com.moaje.moajegateway.config.GatewayGuardProperties
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.LoggerFactory
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.data.redis.RedisConnectionFailureException
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.util.StreamUtils
import org.springframework.web.filter.OncePerRequestFilter
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import java.util.Locale
import java.util.UUID

/**
 * GateWay Guard Filter
 * 클라이언트의 요청으로부터 받은 request 데이터를 정제하고 검증하는 필터
 * This filter is responsible for:
 * - Sanitizing internal headers
 * - Checking idempotency
 * - Logging traceId
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
class GatewayGuardFilter(
    private val redisTemplate: StringRedisTemplate,
    private val objectMapper: ObjectMapper,
    private val properties: GatewayGuardProperties,
) : OncePerRequestFilter() {

    private val log = LoggerFactory.getLogger(javaClass)

    // doFilterInternal, 하나의 요청당 한번 실행
    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain,
    ) {
        val traceId = request.getHeader(properties.traceHeaderName)
            ?.takeIf { it.isNotBlank() }
            ?: UUID.randomUUID().toString() // x-trace-Id 값이 없으면 UUID 문자열 생성, 있으면 가져오기
        response.setHeader(properties.traceHeaderName, traceId)

        // 외부에서 온 Header 무시, gateway에서 추적용 헤더 및 기본 보안헤더를 추가한 guardRequest (wrapper request)
        val guardedRequest = request.withGuardHeaders(traceId)

        // 멱등성 검증
        val idempotency = properties.idempotency
        if (!idempotency.enabled || shouldSkipIdempotency(guardedRequest)) {
            filterChain.doFilter(guardedRequest, response)
            return
        }

        // 멱등성 헤더가 존재하지 않으면 통과할 수 없음
        val keyHeader = guardedRequest.getHeader(idempotency.headerName)?.trim()
        if (keyHeader.isNullOrBlank()) {
            if (idempotency.requireForUnsafeMethods) {
                writeError(
                    response = response,
                    status = HttpStatus.BAD_REQUEST,
                    code = "MISSING_IDEMPOTENCY_KEY",
                    message = "Idempotency-Key header is required.",
                    traceId = traceId,
                )
                return
            }

            filterChain.doFilter(guardedRequest, response)
            return
        }

        // 요청본문의 크기가 지정한 크기보다 크면 처리하지 않음
        val cachedRequest = try {
            guardedRequest.cachedWithLimit(idempotency.maxBodyBytes)
        } catch (ex: RequestBodyTooLargeException) {
            writeError(
                response = response,
                status = HttpStatus.PAYLOAD_TOO_LARGE,
                code = "REQUEST_BODY_TOO_LARGE",
                message = "Request body is too large.",
                traceId = traceId,
            )
            return
        }

        val bodyHash = sha256Base64(cachedRequest.cachedBody)
        val fingerprint = requestFingerprint(cachedRequest, bodyHash)
        val redisKey = idempotency.keyPrefix + sha256Base64(fingerprint.toByteArray(Charsets.UTF_8))
        val redisValue = bodyHash
        val acquired = tryAcquireIdempotencyKey(
            response = response,
            redisKey = redisKey,
            redisValue = redisValue,
            traceId = traceId,
        ) ?: return

        try {
            filterChain.doFilter(cachedRequest, response)

            if (acquired && response.status >= 500) {
                deleteQuietly(redisKey, traceId)
            }
        } catch (ex: RuntimeException) {
            if (acquired) {
                deleteQuietly(redisKey, traceId)
            }
            throw ex
        }
    }

    // 멱등성 키 검사가 필요한지를 check
    // redis에 이미 key가 있다면 검사하지 않고, 키가 있으면 검사함
    private fun tryAcquireIdempotencyKey(
        response: HttpServletResponse,
        redisKey: String,
        redisValue: String,
        traceId: String,
    ): Boolean? {
        return try {
            // redis 에서 해당 멱등성 키 선점 성공 시 True, 선점 실패 시 False
            val acquired = redisTemplate.opsForValue()
                .setIfAbsent(redisKey, redisValue, properties.idempotency.ttl) == true

            if (!acquired) { // KEY값 (IdempotencyKey)는 같은데 body가 다른경우 -> Key만 재사용했단 소리
                val previousValue = redisTemplate.opsForValue().get(redisKey)
                val code = if (previousValue == redisValue) {
                    "DUPLICATE_REQUEST"
                } else {
                    "IDEMPOTENCY_KEY_CONFLICT"
                }
                val message = if (previousValue == redisValue) {
                    "Duplicated request."
                } else {
                    "Idempotency-Key was reused with a different request body."
                }

                writeError(response, HttpStatus.CONFLICT, code, message, traceId)
                return null
            }

            true
        } catch (ex: RedisConnectionFailureException) {
            handleRedisFailure(response, traceId, ex)
        }
    }
    // 클라이언트가 위조해서 보낼 수 있는 내부 헤더값들을 제거하고 gateway가 관리하는 traceId만 다시 넣는다 (HttpServletRequest 확장함수)
    // Remove internal headers that could be used to tamper with the request
    private fun HttpServletRequest.withGuardHeaders(traceId: String): HttpServletRequest {
        val blockedHeaderNames = properties.internalHeaders + setOf(properties.traceHeaderName)
        return SanitizedHeaderHttpServletRequest(
            request = this,
            blockedHeaders = blockedHeaderNames,
            addedHeaders = mapOf(properties.traceHeaderName to traceId),
        )
    }
    // 멱등성스킵여부 확인 함수
    private fun shouldSkipIdempotency(request: HttpServletRequest): Boolean {
        val idempotency = properties.idempotency
        val method = request.method.uppercase(Locale.ROOT)
        // Properties에 명시된 method가 아니면 멱등성 검사를 진행하지 않는다.
        if (method !in idempotency.methods.map { it.uppercase(Locale.ROOT) }) {
            return true
        }
        return idempotency.excludedPathPrefixes.any { request.requestURI.startsWith(it) }
    }

    private fun HttpServletRequest.cachedWithLimit(maxBytes: Int): CachedBodyHttpServletRequest {
        val bytes = StreamUtils.copyToByteArray(inputStream)
        if (bytes.size > maxBytes) {
            throw RequestBodyTooLargeException()
        }
        return CachedBodyHttpServletRequest(this, bytes)
    }

    private fun requestFingerprint(request: HttpServletRequest, bodyHash: String): String {
        val authScope = request.getHeader("Authorization")
            ?.let { sha256Base64(it.toByteArray(Charsets.UTF_8)) }
            ?: "anonymous"
        val query = request.queryString ?: ""
        return listOf(
            authScope,
            request.method.uppercase(Locale.ROOT),
            request.requestURI,
            query,
            request.getHeader(properties.idempotency.headerName).orEmpty(),
            bodyHash,
        ).joinToString(":")
    }

    private fun handleRedisFailure(
        response: HttpServletResponse,
        traceId: String,
        ex: RuntimeException,
    ): Boolean? {
        log.warn("Redis failure while checking idempotency. traceId={}", traceId, ex)
        if (properties.idempotency.failClosed) {
            writeError(
                response = response,
                status = HttpStatus.SERVICE_UNAVAILABLE,
                code = "IDEMPOTENCY_STORE_UNAVAILABLE",
                message = "Unable to verify request idempotency.",
                traceId = traceId,
            )
            return null
        }

        log.warn("Fail-open idempotency policy is enabled. Passing request. traceId={}", traceId)
        response.setHeader(properties.traceHeaderName, traceId)
        return false
    }

    private fun deleteQuietly(redisKey: String, traceId: String) {
        try {
            redisTemplate.delete(redisKey)
        } catch (ex: RuntimeException) {
            log.warn("Failed to delete idempotency key after upstream failure. traceId={}", traceId, ex)
        }
    }

    private fun writeError(
        response: HttpServletResponse,
        status: HttpStatus,
        code: String,
        message: String,
        traceId: String,
    ) {
        response.status = status.value()
        response.contentType = MediaType.APPLICATION_JSON_VALUE
        response.characterEncoding = Charsets.UTF_8.name()
        objectMapper.writeValue(
            response.writer,
            ApiErrorResponse(
                code = code,
                message = message,
                traceId = traceId,
                timestamp = Instant.now().toString(),
            ),
        )
    }

    private fun sha256Base64(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
    }

    private class RequestBodyTooLargeException : RuntimeException()
}
