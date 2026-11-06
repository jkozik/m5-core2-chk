# One small stdlib-only script: no build stage needed, so the size comes from the base image.
FROM python:3.13-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY listener.py /app/listener.py
EXPOSE 9099/udp
CMD ["python", "/app/listener.py"]
