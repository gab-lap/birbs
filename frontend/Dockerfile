FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY frontend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY frontend/src/frontend /app/frontend
COPY frontend/templates /app/templates
COPY frontend/static /app/static

ENV BACKEND_API_URL=http://backend-birbs:8001
EXPOSE 8000

CMD ["uvicorn", "frontend.frontend:app", "--host", "0.0.0.0", "--port", "8000"]