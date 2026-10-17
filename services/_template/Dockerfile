# syntax=docker/dockerfile:1
#
# Template Dockerfile: a Java 25 + Maven example. Replace it with your
# service's own build, keeping the conventions every SyncWave image follows:
#   - listens on port 8080 for HTTP (and 50051 if it serves gRPC)
#   - answers GET /health with 200 {"status":"ok"}  (used by the HEALTHCHECK)
#   - runs as a non-root user
#   - needs contract files at build time? Copy them from the shared
#     `contracts` build context (set up by compose.yaml and CI), e.g.:
#         COPY --from=contracts grpc/ /contracts/grpc/
#     and list that folder in your CONTRACT_PATHS in the root .gitlab-ci.yml.

FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /src
# Dependencies first: this layer is reused (locally and from the CI cache)
# until pom.xml changes.
COPY pom.xml .
RUN mvn --batch-mode --quiet dependency:go-offline
COPY src ./src
RUN mvn --batch-mode --quiet -DskipTests package

FROM eclipse-temurin:25-jre-alpine
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app
COPY --from=build /src/target/*.jar app.jar
USER app
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
