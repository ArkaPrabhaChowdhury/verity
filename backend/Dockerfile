FROM python:3.13.5-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY verity ./verity
RUN mkdir -p /app/data && useradd --system --uid 10001 verity && chown -R verity:verity /app
USER verity
EXPOSE 8080
CMD ["uvicorn", "verity.app:app", "--host", "0.0.0.0", "--port", "8080"]
