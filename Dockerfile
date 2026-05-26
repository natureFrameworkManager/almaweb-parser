FROM python:3.14-slim AS base

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./src /code/src
COPY ./scrapy.cfg /code/scrapy.cfg

# Install cron and gosu (gosu gives clean exec into appuser without sudo)
RUN apt-get update && apt-get install -y --no-install-recommends cron gosu && \
    rm -rf /var/lib/apt/lists/*

# Persistent data volume — symlink the SQLite db out of the image layer so
# it survives container rebuilds when /data is mounted from the host.
RUN mkdir -p /data && \
    ln -sf /data/database.db /code/database.db

# Daily cron job: re-run scrapy spider at 02:00
RUN echo 'SHELL=/bin/bash' > /etc/cron.d/almaweb-parse && \
    echo '0 2 * * * appuser cd /code && /usr/local/bin/scrapy crawl lecture_spider >> /var/log/almaweb-cron.log 2>&1' \
    >> /etc/cron.d/almaweb-parse && \
    chmod 0644 /etc/cron.d/almaweb-parse

# Pre-create cron log file so appuser can write to it
RUN touch /var/log/almaweb-cron.log

# Entrypoint: start cron daemon, then exec FastAPI as appuser (PID 1)
RUN echo '#!/bin/bash'                                                                      > /entrypoint.sh && \
    echo 'set -e'                                                                          >> /entrypoint.sh && \
    echo '/usr/sbin/cron'                                                                  >> /entrypoint.sh && \
    echo 'exec gosu appuser fastapi run src/api/main.py --port 80 --proxy-headers'        >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

RUN useradd -u 8888 appuser && \
    chown -R appuser:appuser /code /data /var/log/almaweb-cron.log

WORKDIR /code

CMD ["/entrypoint.sh"]