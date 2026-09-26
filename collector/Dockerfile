ARG BASE_IMAGE=docker.io/library/python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY payment_metrics.py /app/payment_metrics.py
EXPOSE 9093
CMD ["python3", "/app/payment_metrics.py"]
