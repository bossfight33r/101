# Песочница TechStudio: VHS + базовые сетевые/dev-утилиты. Команды сценариев выполняются ТОЛЬКО здесь.
# Сборка: make sandbox-image   (docker build -t techstudio-sandbox:latest docker/studio)
FROM ghcr.io/charmbracelet/vhs:latest

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl ca-certificates iproute2 dnsutils iputils-ping git python3 python3-venv \
      procps jq less nano net-tools bash-completion \
 && rm -rf /var/lib/apt/lists/*

# non-root пользователь; uid 1000 совпадает с владельцем выходной папки сцены
RUN useradd --create-home --uid 1000 --shell /bin/bash studio
ENV HOME=/home/studio \
    PS1='\[\e[1;32m\]studio\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]$ ' \
    VHS_NO_SANDBOX=true \
    LANG=C.UTF-8
WORKDIR /home/studio
USER studio

# По умолчанию: vhs /out/scene.tape (точка входа базового образа — vhs)
ENTRYPOINT ["/usr/bin/vhs"]
