FROM rust:1.94-bookworm AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends cmake ffmpeg perl pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/audio_transmitter /usr/local/bin/audio_transmitter
ENV AWS_REGION=ap-southeast-1
EXPOSE 8081
CMD ["audio_transmitter"]
