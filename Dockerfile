FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUB2SB_DB_PATH=/data/subscriptions.sqlite3

WORKDIR /app

COPY pyproject.toml .
COPY converter.py remote_subscription.py sub2singbox.py subscription_utils.py subscription_lab.py ./
RUN pip install --no-cache-dir .

COPY api ./api
COPY public ./public
COPY web_server.py ./
COPY templates ./templates

EXPOSE 8080

CMD ["python", "web_server.py", "--host", "0.0.0.0", "--port", "8080"]
