FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN mkdir -p data
EXPOSE 8080
ENV F0_PORT=8080
CMD ["python3", "server.py"]
