FROM python:3.11-slim

WORKDIR /app

# Install uv package manager
RUN pip install uv

# Copy requirements first for better caching
COPY requirements.txt .
RUN uv pip install -r requirements.txt

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