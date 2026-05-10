package com.moaje.moajegateway.config

import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

@Configuration
class JsonConfig {

    @Bean
    fun objectMapper(): ObjectMapper {
        return ObjectMapper().findAndRegisterModules()
    }
}
