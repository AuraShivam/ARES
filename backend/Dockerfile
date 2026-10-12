ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin ares

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt \
    && python -m pip check

COPY --chown=ares:ares backend/ ./
RUN DJANGO_DEBUG=false DJANGO_SECRET_KEY=build-only-static-collection-key ARES_REDIS_URL=rediss://localhost:6379/0 \
    python manage.py collectstatic --noinput

USER 10001:10001
EXPOSE 8000

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
