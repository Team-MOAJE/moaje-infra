package com.moaje.moajegateway.filter

import jakarta.servlet.ReadListener
import jakarta.servlet.ServletInputStream
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletRequestWrapper
import java.io.BufferedReader
import java.io.ByteArrayInputStream
import java.io.InputStreamReader
import java.nio.charset.Charset

class CachedBodyHttpServletRequest(
    request: HttpServletRequest,
    val cachedBody: ByteArray,
) : HttpServletRequestWrapper(request) {

    override fun getInputStream(): ServletInputStream {
        val inputStream = ByteArrayInputStream(cachedBody)

        return object : ServletInputStream() {
            override fun read(): Int = inputStream.read()

            override fun isFinished(): Boolean = inputStream.available() == 0

            override fun isReady(): Boolean = true

            override fun setReadListener(readListener: ReadListener?) = Unit
        }
    }

    override fun getReader(): BufferedReader {
        val charset = characterEncoding?.let(Charset::forName) ?: Charsets.UTF_8
        return BufferedReader(InputStreamReader(inputStream, charset))
    }
}
