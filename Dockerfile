FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl wird für die Zustandsprüfung des Containers gebraucht.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Die statischen Dateien werden beim Bauen eingesammelt. Die Platzhalterwerte
# gelten nur für diesen Befehl und landen nicht im Abbild.
RUN DJANGO_SECRET_KEY=nur-zum-bauen DJANGO_DEBUG=0 \
    python manage.py collectstatic --noinput --clear

RUN chmod +x /app/entrypoint.sh
RUN useradd --uid 10001 --create-home app \
 && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
