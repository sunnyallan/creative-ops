FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fontconfig \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake the rembg u2net model (~170MB) into the image so containers don't
# download it at first cutout request.
RUN python -c "from rembg import new_session; new_session('u2net')"

COPY . .
RUN chmod +x /app/entrypoint-api.sh

EXPOSE 8000
# API image default: run migrations then Uvicorn.
# Worker + beat services override this in Railway with plain celery commands.
CMD ["/app/entrypoint-api.sh"]
