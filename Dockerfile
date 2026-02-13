FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir psycopg2-binary
COPY . .
RUN mkdir -p data
EXPOSE 8080
ENV F0_PORT=8080
CMD ["python3", "server.py"]
