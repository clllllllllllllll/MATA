FROM python:3.12-slim

RUN groupadd --gid 10001 mata \
    && useradd --uid 10001 --gid mata --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin mata

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY docs/ /docs/

USER mata

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
