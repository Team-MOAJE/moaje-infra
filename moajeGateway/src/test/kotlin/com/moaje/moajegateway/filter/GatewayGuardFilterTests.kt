package com.moaje.moajegateway.filter

import com.fasterxml.jackson.databind.ObjectMapper
import com.moaje.moajegateway.config.GatewayGuardProperties
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test
import org.mockito.Mockito
import org.springframework.data.redis.RedisConnectionFailureException
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.data.redis.core.ValueOperations
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import java.time.Duration

@Suppress("UNCHECKED_CAST")
class GatewayGuardFilterTests {

    private val objectMapper = ObjectMapper().findAndRegisterModules()
    private val properties = GatewayGuardProperties()

    @Test
    @DisplayName("최초 멱등 요청은 통과하고 내부 헤더는 제거한다")
    fun passesFirstIdempotentRequestAndSanitizesInternalHeaders() {

        val valueOperations = valueOperations(setIfAbsentResult = true)
        val redisTemplate = redisTemplate(valueOperations)
        val filter = GatewayGuardFilter(redisTemplate, objectMapper, properties)
        val request = request(body = """{"amount":1000}""").apply {
            addHeader("Idempotency-Key", "transfer-1")
            addHeader("X-User-Id", "client-spoofed")
            addHeader("X-Trace-Id", "client-trace")
        }
        val response = MockHttpServletResponse()
        var filteredRequest: HttpServletRequest? = null

        // 후행 람다식, doFilter의 마지막 인자인 FilterChain은 메서드가 딱 하나만 있는 Single Abstract Method(SAM) 이라서
        // 인터페이스를 직접 구현하는 대신에, 그냥 람다식({}) 으로 퉁칠 수 있게 해줌!
        filter.doFilter(request, response) { servletRequest, servletResponse ->
            filteredRequest = servletRequest as HttpServletRequest
            servletResponse as MockHttpServletResponse
            servletResponse.status = HttpStatus.OK.value()
        }

        assertThat(response.status).isEqualTo(HttpStatus.OK.value())
        assertThat(response.getHeader("X-Trace-Id")).isEqualTo("client-trace")
        assertThat(filteredRequest?.getHeader("X-Trace-Id")).isEqualTo("client-trace")
        assertThat(filteredRequest?.getHeader("X-User-Id")).isNull()
        Mockito.verify(valueOperations).setIfAbsent(
            Mockito.startsWith("moaje:gateway:idempotency:"),
            Mockito.anyString(),
            Mockito.eq(Duration.ofMinutes(10)),
        )
    }

    @Test
    @DisplayName("같은 멱등성 키와 같은 본문의 중복 요청은 차단한다")
    fun rejectsDuplicatedRequestWithSameIdempotencyKeyAndBody() {
        var storedValue = ""
        val valueOperations = Mockito.mock(ValueOperations::class.java) as ValueOperations<String, String>
        Mockito.`when`(
            valueOperations.setIfAbsent(Mockito.anyString(), Mockito.anyString(), Mockito.any(Duration::class.java)),
        ).thenAnswer { invocation ->
            storedValue = invocation.arguments[1] as String
            false
        }
        Mockito.`when`(valueOperations.get(Mockito.anyString())).thenAnswer { storedValue }

        val filter = GatewayGuardFilter(redisTemplate(valueOperations), objectMapper, properties)
        val response = MockHttpServletResponse()

        filter.doFilter(request(body = """{"amount":1000}""").withIdempotencyKey(), response, FilterChain { _, _ ->
            error("Duplicated request must not pass the filter chain.")
        })

        assertThat(response.status).isEqualTo(HttpStatus.CONFLICT.value())
        assertThat(response.contentAsString).contains("DUPLICATE_REQUEST")
    }

    @Test
    @DisplayName("같은 멱등성 키와 다른 본문의 요청은 충돌로 차단한다")
    fun rejectsReusedIdempotencyKeyWithDifferentBody() {
        val valueOperations = valueOperations(setIfAbsentResult = false, existingValue = "different-body-hash")
        val filter = GatewayGuardFilter(redisTemplate(valueOperations), objectMapper, properties)
        val response = MockHttpServletResponse()

        filter.doFilter(request(body = """{"amount":2000}""").withIdempotencyKey(), response, FilterChain { _, _ ->
            error("Conflicting request must not pass the filter chain.")
        })

        assertThat(response.status).isEqualTo(HttpStatus.CONFLICT.value())
        assertThat(response.contentAsString).contains("IDEMPOTENCY_KEY_CONFLICT")
    }

    @Test
    @DisplayName("Redis를 사용할 수 없으면 fail-closed 정책으로 차단한다")
    fun failsClosedWhenRedisIsUnavailable() {
        val valueOperations = Mockito.mock(ValueOperations::class.java) as ValueOperations<String, String>
        Mockito.`when`(
            valueOperations.setIfAbsent(Mockito.anyString(), Mockito.anyString(), Mockito.any(Duration::class.java)),
        ).thenThrow(RedisConnectionFailureException("redis down"))

        val filter = GatewayGuardFilter(redisTemplate(valueOperations), objectMapper, properties)
        val response = MockHttpServletResponse()

        filter.doFilter(request(body = """{"amount":1000}""").withIdempotencyKey(), response, FilterChain { _, _ ->
            error("Request must not pass when Redis is unavailable.")
        })

        assertThat(response.status).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE.value())
        assertThat(response.contentAsString).contains("IDEMPOTENCY_STORE_UNAVAILABLE")
    }

    private fun request(body: String): MockHttpServletRequest {
        return MockHttpServletRequest("POST", "/api/transfers").apply {
            contentType = MediaType.APPLICATION_JSON_VALUE
            setContent(body.toByteArray(Charsets.UTF_8))
        }
    }

    private fun MockHttpServletRequest.withIdempotencyKey(): MockHttpServletRequest = apply {
        addHeader("Idempotency-Key", "transfer-1")
    }

    private fun redisTemplate(
        valueOperations: ValueOperations<String, String>,
    ): StringRedisTemplate {
        val redisTemplate = Mockito.mock(StringRedisTemplate::class.java)
        Mockito.`when`(redisTemplate.opsForValue()).thenReturn(valueOperations)
        return redisTemplate
    }

    private fun valueOperations(
        setIfAbsentResult: Boolean,
        existingValue: String? = null,
    ): ValueOperations<String, String> {
        val valueOperations = Mockito.mock(ValueOperations::class.java) as ValueOperations<String, String>
        Mockito.`when`(
            valueOperations.setIfAbsent(Mockito.anyString(), Mockito.anyString(), Mockito.any(Duration::class.java)),
        ).thenReturn(setIfAbsentResult)
        Mockito.`when`(valueOperations.get(Mockito.anyString())).thenReturn(existingValue)
        return valueOperations
    }
}

