FROM php:8.1-apache

WORKDIR /var/www/html

# composer из официального образа
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# git и zip нужны composer для скачивания пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    git unzip libzip-dev \
    && docker-php-ext-install zip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/www/html/data /app/data && chmod 777 /var/www/html/data /app/data

RUN ln -s /app/data /var/www/html/data_persistent || true

COPY . .

RUN composer install --no-dev --optimize-autoloader --no-interaction

EXPOSE 80
