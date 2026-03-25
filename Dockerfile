FROM python:3.13-slim
LABEL maintainer=twtrubiks
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 建立非 root 使用者（UID=1000 對應本機使用者，避免 volume 權限問題）
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

RUN mkdir -p /youtube_service
WORKDIR /youtube_service
COPY . /youtube_service/

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it（以 root 安裝到系統路徑）
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the PATH
ENV PATH="/root/.local/bin/:$PATH"

# Use uv to install packages（以 root 安裝系統層級套件）
RUN uv pip install --no-cache --system -r requirements.txt

# 設定目錄權限給 appuser
RUN chown -R appuser:appuser /youtube_service

# for entry point
RUN chmod +x /youtube_service/entrypoint.sh

# 切換到非 root 使用者
USER appuser

# 設定 entrypoint
ENTRYPOINT ["/youtube_service/entrypoint.sh"]
