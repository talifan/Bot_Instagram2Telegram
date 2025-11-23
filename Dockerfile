FROM python:3.11-slim

# Устанавливаем ffmpeg и другие системные зависимости
RUN apt-get update && apt-get install -y ffmpeg iputils-ping && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем файлы проекта
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Папка для временных файлов
RUN mkdir -p /app/temp

CMD ["python", "bot2.py"]