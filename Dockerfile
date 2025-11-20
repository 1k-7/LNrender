# Base image
FROM python:3.10-slim

# 1. Install system build dependencies (caches this layer)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
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

# 5. IMPORTANT: Prevent auto-downloading unused sources
ENV LNCRAWL_MODE="dev" 
ENV PYTHONUNBUFFERED=1

# Create downloads directory
RUN mkdir -p downloads

# Command to run the bot
CMD ["python", "bot.py"]
