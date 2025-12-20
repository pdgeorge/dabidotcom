FROM python:3.12-slim

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .
COPY static ./static

ENV PAGES_API_KEY=change-me \
    DB_PATH=/data/pages.db \
    SITE_NAME=Dabby

VOLUME ["/data"]

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
