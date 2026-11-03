FROM php:8.4.27-fpm-trixie

COPY --from=mlocati/php-extension-installer:2.13.2 /usr/bin/install-php-extensions /usr/local/bin/

RUN install-php-extensions gd intl ldap mysqli pdo_mysql zip exif gettext bcmath sockets \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY 99-easy-appointments.ini /usr/local/etc/php/conf.d/99-easy-appointments.ini

WORKDIR /var/www/html
