# Shopping Content Factory — 단일 컨테이너 (웹 + 스케줄러는 compose 에서 분리 실행)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY . .
ENV SCF_DATA_DIR=/app/data SCF_OUTPUT_DIR=/app/outputs PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "wsgi:app"]
