FROM ckulka/baikal:0.10.1-apache

RUN apt-get update \
    && apt-get install -y libpng16-16 libzip4 \
    && rm -rf /var/lib/apt/lists/*
