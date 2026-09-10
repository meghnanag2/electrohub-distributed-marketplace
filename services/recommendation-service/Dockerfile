FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch — avoids ~2 GB CUDA download
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    sentence-transformers==2.7.0 \
    fastapi==0.110.0 \
    uvicorn==0.27.1 \
    psycopg2-binary==2.9.9 \
    numpy==1.26.4

COPY services/recommendation-service/ .

# Pre-download model weights into the image layer (no internet needed at runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 8005
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
