FROM python:3.10-slim

# نصب ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# نصب yt-dlp
RUN pip install yt-dlp

WORKDIR /app

# کپی فایل‌ها - اینجا اسم فایل رو درست کردم
COPY requirements.txt .
COPY vidownly.py .   # تغییر اینجا - به جای bot.py

# نصب کتابخونه‌ها
RUN pip install --no-cache-dir -r requirements.txt

# اجرا - اینجا هم اسم رو درست کن
CMD ["python", "vidownly.py"]
