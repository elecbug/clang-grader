# syntax=docker/dockerfile:1

FROM debian:bookworm-slim

# Install toolchain, C standard library headers, and Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential python3 python3-pip ca-certificates time && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY run_tests.py /app/run_tests.py

ENV CFLAGS="-O2 -std=c17 -Wall -Wextra" \
    BIN_OUT="/work/a.out"

ENTRYPOINT ["python3", "/app/run_tests.py"]
