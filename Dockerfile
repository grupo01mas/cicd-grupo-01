FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /data

# Docker image tags this build was published under, injected by CI at build time.
# Empty by default so local builds show no tags in the app footer.
ARG IMAGE_TAGS=""
ENV IMAGE_TAGS=$IMAGE_TAGS

EXPOSE 5000

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${APP_PORT:-5000} app:app"]
