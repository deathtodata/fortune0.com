FROM searxng/searxng:latest

# Copy our settings
COPY settings.yml /etc/searxng/settings.yml

# Render uses PORT env var
ENV PORT=8080
EXPOSE 8080
