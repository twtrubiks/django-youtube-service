FROM python:3.13-slim
LABEL maintainer=twtrubiks
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 建立非 root 使用者（UID=1000 對應本機使用者，避免 volume 權限問題）
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

RUN mkdir -p /youtube_service
WORKDIR /youtube_service
COPY . /youtube_service/

# 從官方映像複製 uv 到系統路徑
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 安裝 Python 套件
RUN uv pip install --no-cache --system -r requirements.txt

# 設定目錄權限給 appuser
RUN chown -R appuser:appuser /youtube_service

# for entry point
RUN chmod +x /youtube_service/entrypoint.sh

# 切換到非 root 使用者
USER appuser

# 設定 entrypoint
ENTRYPOINT ["/youtube_service/entrypoint.sh"]
