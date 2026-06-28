# FindSecBugs CLI (SpotBugs + find-sec-bugs plugin) — phân tích BYTECODE .class/.jar.
FROM eclipse-temurin:17-jdk
ARG FSB=https://github.com/find-sec-bugs/find-sec-bugs/releases/download/version-1.14.0/findsecbugs-cli-1.14.0.zip
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && rm -rf /var/lib/apt/lists/* \
 && curl -sSL "$FSB" -o /tmp/fsb.zip \
 && mkdir -p /opt/findsecbugs && unzip -q /tmp/fsb.zip -d /opt/findsecbugs && rm /tmp/fsb.zip \
 && S="$(find /opt/findsecbugs -name findsecbugs.sh | head -1)" \
 && sed -i 's/\r$//' "$S" && chmod +x "$S" && ln -s "$S" /usr/local/bin/findsecbugs
