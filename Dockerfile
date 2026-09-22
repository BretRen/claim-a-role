FROM python:3.11-slim

WORKDIR /app

# 避免 Python 缓冲输出
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 挂载存储目录
VOLUME ["/app/data"]

CMD ["python", "main.py"]
