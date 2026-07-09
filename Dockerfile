FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --prefer-binary python-telegram-bot==22.8 apscheduler==3.10.4

COPY . /app

CMD ["python", "wimbledon_bot.py"]
