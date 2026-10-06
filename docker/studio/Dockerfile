# Песочница TechStudio: VHS + базовые сетевые/dev-утилиты. Команды сценариев выполняются ТОЛЬКО здесь.
# Сборка: make sandbox-image   (docker build -t techstudio-sandbox:latest docker/studio)
FROM ghcr.io/charmbracelet/vhs:latest

USER root
# База образа VHS — Debian; ветка apk на случай, если upstream сменит базу на Alpine.
RUN set -eux; \
    if command -v apt-get >/dev/null; then \
      apt-get update; \
      apt-get install -y --no-install-recommends \
        curl ca-certificates iproute2 dnsutils iputils-ping git python3 python3-venv \
        procps jq less nano net-tools bash-completion; \
      rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null; then \
      apk add --no-cache bash curl ca-certificates iproute2 bind-tools iputils git python3 \
        procps jq less nano net-tools bash-completion shadow; \
    else \
      echo "неизвестный пакетный менеджер" >&2; exit 1; \
    fi

# non-root пользователь; uid 1000 совпадает с uid, под которым запускается контейнер (--user 1000:1000)
RUN id -u studio >/dev/null 2>&1 || useradd --create-home --uid 1000 --shell /bin/bash studio
ENV HOME=/home/studio \
    PS1='\[\e[1;32m\]studio\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]$ ' \
    VHS_NO_SANDBOX=true \
    LANG=C.UTF-8
WORKDIR /home/studio
USER studio

# Проверка при сборке: vhs и утилиты на месте
RUN vhs --version && ss -V && dig -v && python3 --version

# По умолчанию: vhs /out/scene.tape
ENTRYPOINT ["vhs"]
