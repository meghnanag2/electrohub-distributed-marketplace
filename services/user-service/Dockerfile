FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir grpcio-tools==1.60.0
COPY protos/ /protos/
RUN mkdir -p app/grpc/generated && touch app/grpc/__init__.py app/grpc/generated/__init__.py && \
    python -m grpc_tools.protoc -I/protos \
      --python_out=app/grpc/generated \
      --grpc_python_out=app/grpc/generated \
      /protos/user.proto /protos/listing.proto /protos/notification.proto

COPY services/user-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code first, then overlay shared core (exceptions, logging, redis)
COPY services/user-service/ .
COPY services/shared/ app/core/

ENV PYTHONPATH=/app/app/grpc/generated

EXPOSE 8001 50051
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
