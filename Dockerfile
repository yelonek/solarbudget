FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && echo 'export PATH="/root/.local/bin:$PATH"' >> /root/.bashrc \
    && . /root/.bashrc

# Copy requirements first for better caching
COPY requirements.txt .
RUN /root/.local/bin/uv pip install --system -r requirements.txt

# Create required directories
RUN mkdir -p /app/data /app/logs /app/templates /app/static

# Copy application code
COPY . .

# Create non-root user and set permissions
RUN useradd -m appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod -R 777 /app/data /app/logs

# Set environment variables
ENV DATABASE_URL="sqlite:////app/data/solarbudget.db"

USER appuser

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 