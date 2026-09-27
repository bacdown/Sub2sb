FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api
COPY web ./web
COPY converter.py sub2singbox.py web_server.py ./
COPY templates ./templates

EXPOSE 8080

CMD ["python", "web_server.py", "--host", "0.0.0.0", "--port", "8080"]
