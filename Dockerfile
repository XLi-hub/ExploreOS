# syntax=docker/dockerfile:1
# ClawInstitute's bundled frontend currently targets Linux amd64.
FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

RUN --mount=type=secret,id=system_ca \
    touch /tmp/exploreos-apt.conf; \
    if [ -f /run/secrets/system_ca ]; then \
      echo 'Acquire::https::CaInfo "/run/secrets/system_ca";' > /tmp/exploreos-apt.conf; \
    fi \
    && apt-get -c /tmp/exploreos-apt.conf update \
    && apt-get -c /tmp/exploreos-apt.conf install -y --no-install-recommends python3 python3-venv git ca-certificates \
    && rm -rf /var/lib/apt/lists/* /tmp/exploreos-apt.conf \
    && useradd --create-home --uid 10001 exploreos \
    && install -d -o 10001 -g 10001 /opt/exploreos

WORKDIR /opt/exploreos
COPY --chown=10001:10001 cloud/ cloud/
COPY --chown=10001:10001 explore/ explore/
COPY --chown=10001:10001 scripts/ scripts/
COPY --chown=10001:10001 examples/ examples/
COPY --chown=10001:10001 docs/ docs/
USER 10001:10001
RUN --mount=type=secret,id=system_ca,uid=10001 \
    if [ -f /run/secrets/system_ca ]; then \
      export SSL_CERT_FILE=/run/secrets/system_ca PIP_CERT=/run/secrets/system_ca \
        REQUESTS_CA_BUNDLE=/run/secrets/system_ca GIT_SSL_CAINFO=/run/secrets/system_ca \
        NODE_EXTRA_CA_CERTS=/run/secrets/system_ca; \
    fi \
    && bash scripts/cloud/setup.sh \
    && bash scripts/cloud/setup_pi.sh \
    && bash scripts/cloud/setup_subagents.sh \
    && mkdir -p .research .runtime/service .runtime/backups \
    && chmod 700 .research .runtime/service .runtime/backups \
    && rm -rf /home/exploreos/.npm /home/exploreos/.cache

ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="ExploreOS" \
      org.opencontainers.image.source="https://github.com/XLi-hub/ExploreOS" \
      org.opencontainers.image.revision=$VCS_REF
ENV PYTHONUNBUFFERED=1 EXPLORE_FRONTEND_HOSTNAME=0.0.0.0
EXPOSE 3001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=15s --start-period=90s --retries=3 \
  CMD [".venv/bin/python", "scripts/cloud/product.py", "health"]
CMD [".venv/bin/python", "scripts/cloud/product.py", "serve"]
