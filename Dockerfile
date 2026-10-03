# HandCode in a container. docs/0051 Stage 2.
#
# Why a container: agentctl is not a sandbox (guide/concepts.md). On a laptop an
# allowed command can reach the whole laptop. Here it reaches the container and
# the ONE directory mounted at /work. A `pip install` the agent runs unasked, or
# a write to ~/.bashrc, lands in the container and dies with it.
#
# Built from the release WHEEL, not the source tree, so the image tests the same
# artifact PyPI gets:
#
#   uv build
#   docker build -t handcode .
#   docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/work" \
#       --env-file ~/.agentctl/keys.env -v handcode-home:/home/handcode \
#       handcode run "<task>" --accept "<tests>"

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

COPY dist/*.whl /tmp/dist/
RUN uv pip install --system --no-cache "$(ls /tmp/dist/handcode-*.whl)[openhands]" \
 && rm -rf /tmp/dist

# The pool's own environment, built in (docs/0047), so `--pool` starts in
# seconds rather than spending minutes installing litellm[proxy] on first use.
# Outside $HOME on purpose: a volume over the home directory would hide it.
ENV AGENTCTL_PROXY_ENV=/opt/handcode/proxy-env
RUN python -c "from agentctl.control.proxyenv import ensure_env; ensure_env()" \
 && chmod -R a+rwX /opt/handcode

# Any uid may run this (`--user "$(id -u):$(id -g)"`, so files written into
# /work belong to you, not to root). HOME is world-writable for that reason:
# keys, config, the run index and the proxy's state live there, and a named
# volume keeps them across containers.
# HANDCODE_CONTAINER: a package install the agent runs lands here and dies
# with the container, so agentctl does not stop to ask about it (docs/0052).
ENV HOME=/home/handcode \
    HANDCODE_CONTAINER=1 \
    OPENHANDS_SUPPRESS_BANNER=1 \
    PYTHONIOENCODING=utf-8
# safe.directory: the mounted repository belongs to a different uid than the
# one running here, and git refuses such a repo without it.
# The identity is a fallback, so the agent never has to set one in YOUR repo
# (docs/0044 N12). To commit as yourself, mount your own:
#   -v ~/.gitconfig:/home/handcode/.gitconfig:ro
RUN mkdir -p /home/handcode && chmod 1777 /home/handcode \
 && git config --system --add safe.directory '*' \
 && git config --system user.name "HandCode agent" \
 && git config --system user.email "agent@handcode.invalid"

WORKDIR /work
ENTRYPOINT ["agentctl"]
CMD ["--help"]
