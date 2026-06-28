# Image tầng đắt: Maven+JDK8 (build/trace) + CodeQL bundle (CLI + query pack precompiled).
# CodeQL cần JDK/Maven cùng container để TRACE build java.
FROM maven:3.9-eclipse-temurin-8
ARG BUNDLE=https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.25.6/codeql-bundle-linux64.tar.gz
RUN curl -sSL "$BUNDLE" -o /tmp/c.tgz \
 && tar -xzf /tmp/c.tgz -C /opt \
 && rm /tmp/c.tgz \
 && ln -s /opt/codeql/codeql /usr/local/bin/codeql
