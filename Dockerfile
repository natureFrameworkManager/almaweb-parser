FROM python:3.14-slim AS base

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./src /code/src

WORKDIR /code

CMD ["fastapi", "run", "src/api/main.py", "--port", "80"]

# If running behind a proxy like Nginx or Traefik add --proxy-headers
# CMD ["fastapi", "run", "src/api/main.py", "--port", "80", "--proxy-headers"]