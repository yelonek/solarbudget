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
RUN /root/.local/bin/uv pip install -r requirements.txt

# Create data directory for SQLite
RUN mkdir -p /app/data
ENV DATABASE_URL="sqlite:///app/data/solarbudget.db"

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"] 