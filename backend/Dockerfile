FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ---- Timezone Europe/Rome ----
    RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Rome
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
# ------------------------------

WORKDIR /app

# System deps for pymysql are minimal; if switching to mysqlclient you would add build-essential default-libmysqlclient-dev
COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# App code
COPY backend/src/backend /app/backend

# Uploads dir
RUN mkdir -p /app/uploads && chown -R root:root /app/uploads

EXPOSE 8001

ENV DB_HOST=mariadb-birbs \
    DB_PORT=3306 \
    DB_USER=root \
    DB_PASS=root \
    DB_NAME=beertrack \
    MEDIA_ROOT=/app/uploads \
    MEDIA_URL_BASE=/media \
    SESSION_TTL_DAYS=7

    CMD ["uvicorn", "backend.backend:app", "--host", "0.0.0.0", "--port", "8001"]