FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot/ bot/
COPY scripts/ scripts/
COPY memory/ memory/
EXPOSE 8080
CMD ["python", "-m", "bot.main"]
