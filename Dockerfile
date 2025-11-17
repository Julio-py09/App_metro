FROM python:3.10-slim

# Evitar buffering en logs
ENV PYTHONUNBUFFERED=1

# Asegurar que el paquete local `metro_cdmx` y módulos internos sean importables
ENV PYTHONPATH="/app:/app/metro_cdmx"

WORKDIR /app

# Copiamos requirements e instalamos, añadiendo gunicorn para producción ligera
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copiamos el resto del código
COPY . .

EXPOSE 5000

# Usar gunicorn para servir la app Flask: metro_cdmx.main:app
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5000", "metro_cdmx.main:app"]