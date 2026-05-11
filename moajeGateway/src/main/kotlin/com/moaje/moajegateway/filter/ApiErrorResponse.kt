package com.moaje.moajegateway.filter

data class ApiErrorResponse(
    val code: String,
    val message: String,
    val traceId: String,
    val timestamp: String,
)
