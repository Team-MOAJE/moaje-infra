package com.moaje.moajegateway

import org.springframework.boot.context.properties.ConfigurationPropertiesScan
import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
@ConfigurationPropertiesScan
class MoajeGatewayApplication

fun main(args: Array<String>) {
    runApplication<MoajeGatewayApplication>(*args)
}
