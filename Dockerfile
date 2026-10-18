FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home sstv

USER sstv
ENV SSTV_SATS_CACHE=/home/sstv/.cache/sstv-sats \
    PYTHONUNBUFFERED=1

# Default: run the alert watcher. Set SSTV_LAT/SSTV_LON (or SSTV_GRID) and SSTV_NTFY.
ENTRYPOINT ["sstv-sats"]
CMD ["watch"]
