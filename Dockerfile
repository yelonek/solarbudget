FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Create a non-root user
RUN useradd -m -s /bin/bash appuser

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create app directory and set permissions
WORKDIR /app
COPY . /app/

# Create necessary directories
RUN mkdir -p /app/logs /app/templates /app/static \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 