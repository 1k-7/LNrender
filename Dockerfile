# Base image
FROM python:3.10-slim

# 1. Install system dependencies
# 'nodejs' is required for PyExecJS/Cloudscraper to handle JS challenges efficiently
# 'build-essential' and libs are for compiling lxml, pillow, etc.
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    nodejs \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    libjpeg-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# 2. Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 3. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy project files
COPY . .

# 5. Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Set a default port for local testing; Render overrides this automatically
ENV PORT=8000 

# Create downloads directory for temporary file generation
RUN mkdir -p downloads

# 6. Run the Web Server
# Using 'sh -c' to properly expand the $PORT variable
# Workers are set to 2 to fit within Render's free tier 512MB RAM limit
CMD sh -c "gunicorn lncrawl.bots.server.app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT}"
