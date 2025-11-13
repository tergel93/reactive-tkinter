FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3-tk x11-apps && \
    rm -rf /var/lib/apt/lists/*
