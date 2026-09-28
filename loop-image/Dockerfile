FROM docker.io/library/python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ARG TARGETARCH
COPY install.py releases.json /opt/loop-release/
RUN python3 /opt/loop-release/install.py "$TARGETARCH" /usr/local/bin
USER 1000:1000
ENTRYPOINT ["loopd"]
