FROM searxng/searxng:latest

COPY settings.yml /etc/searxng/settings.yml

EXPOSE 8080

CMD ["python3", "-m", "searxng.webapp"]
