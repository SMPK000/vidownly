FROM python:3.10-slim

# نصب ffmpeg و ابزارهای مورد نیاز
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# نصب yt-dlp برای دانلود ویدیو
RUN pip install yt-dlp

# ایجاد پوشه کار
WORKDIR /app

# کپی فایل مورد نیاز
COPY requirements.txt .
COPY bot.py .
# اگه فایل دیگه‌ای داری مثل database handler، اونم کپی کن
# COPY database.py .

# نصب کتابخونه‌های پایتون
RUN pip install --no-cache-dir -r requirements.txt

# اجرای ربات
CMD ["python", "bot.py"]
