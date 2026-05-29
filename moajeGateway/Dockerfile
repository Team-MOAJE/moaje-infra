FROM eclipse-temurin:17-jdk-jammy AS builder

WORKDIR /workspace

COPY . .

RUN chmod +x ./gradlew
RUN ./gradlew clean bootJar -x test --no-daemon

FROM eclipse-temurin:17-jre-jammy

WORKDIR /app

COPY --from=builder /workspace/build/libs/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
