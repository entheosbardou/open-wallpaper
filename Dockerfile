FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt && useradd -r -u 10001 wallpaper
COPY server /app/server
COPY web /app/web
RUN mkdir -p /app/data && chown wallpaper:wallpaper /app/data
USER wallpaper
EXPOSE 8080
CMD ["uvicorn","server.app:app","--host","0.0.0.0","--port","8080","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]
