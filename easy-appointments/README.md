# easy-appointments

[Easy!Appointments](https://easyappointments.org) booking site (nginx + php-fpm + MySQL) with phpMyAdmin, Swagger UI and Baikal as private-only extras. The booking site (`nginx`, hostname `${EASY_APPOINTMENTS_SUBDOMAIN}.${DOMAIN}`) is meant to be reachable from the internet through `../traefik-public/`; everything else is private.

## Layout

| Service | Image | Networks | Notes |
|---|---|---|---|
| `nginx` | built from `nginx/` (nginx 1.30.6) | backend, `traefik-proxy`, `public-easy-appointments` | Serves only `/assets/*` and `/index.php`; every other path is routed to the app, so `.git`, `config.php`, `storage/`, `vendor/` etc. are never served. Unknown `Host` headers get no answer (444), which pins the host the app builds links from. |
| `php-fpm` | built from `php-fpm/` (PHP 8.4.27) | backend, default (SMTP egress) | App source mounted **read-only**; only `storage/` is writable. No Xdebug, `session.upload_progress` off. |
| `mysql` | `mysql:8.0.46` | backend | No published port. |
| `phpmyadmin` | `phpmyadmin:5.2.3-apache` | backend, `traefik-proxy` | Private/tailnet only. |
| `swagger-ui` | built from `swagger-ui/` (v5.34.1, API spec of 1.6.1 baked in) | `traefik-proxy` | Private/tailnet only. |
| `baikal` | built from `baikal/` (Baikal 0.10.1) | `traefik-proxy` | Private/tailnet only. See "Open points". |

`easy-appointments-backend` (`internal: true`, `${EASY_APPOINTMENTS_BACKEND_SUBNET}`) carries all nginx/php-fpm/MySQL/phpMyAdmin traffic. php-fpm additionally sits on the stack's default network because it sends mail through an external SMTP server (`application/config/email.php`) and loads the about-page news feed. No service publishes a host port and none is on `cloudflare-web`.

The public path needs, in `../traefik-public/`: the network `public-easy-appointments` (`internal: true`, subnet `172.16.88.0/28`, proxy at `.2`) and a router `Host(`${EASY_APPOINTMENTS_SUBDOMAIN}.${DOMAIN}`)` to `http://easy-appointments-nginx:80`.

## Host layout

| Path | Content |
|---|---|
| `${DOCKER_CONFIG_DIR}/easyappointments-app/` | The Easy!Appointments release (`index.php`, `application/`, `assets/`, `storage/`, `vendor/`, `config.php`). Source of truth for the app version. Nothing else lives here. |
| `${DOCKER_CONFIG_DIR}/easyappointments/docker/mysql` | MySQL data (unchanged location). |
| `${DOCKER_CONFIG_DIR}/easyappointments/docker/baikal/` | Baikal data (unchanged location). |

`permissions-init` only fixes `storage/` (owner `33:33`, mode 750) and the two files holding secrets (`config.php`, `application/config/email.php`: `root:33`, mode 640). It never touches the MySQL or Baikal data.

## Required environment (Portainer stack)

See `.env.example`. New compared with the old stack: `TZ`. Optional (defaults are correct for this repo's network plan): `EASY_APPOINTMENTS_PROXY_IPS`, `EASY_APPOINTMENTS_BACKEND_SUBNET`. Removed and now unused: `NGINX_PORT`, `MYSQL_PORT`, `PHPMYADMIN_PORT`, `SWAGGER_UI_PORT`, `BAIKAL_PORT`.

`EASY_APPOINTMENTS_PROXY_IPS` feeds `PROXY_IPS` (Easy!Appointments 1.6.x): without it every visitor looks like the proxy, so the app's rate limits (100 requests per 2 minutes, 5 failed logins per 5 minutes) would be shared by all customers and one attacker could lock everybody out.

## Moving to 1.6.1 (required before the stack is exposed)

Versions up to 1.6.0 are vulnerable to unauthenticated attacks (GHSA-7pw2-6g72-9v52 appointment overwrite, GHSA-c5rh-f2vc-2qvj password-reset takeover, CAPTCHA skip, login throttle, more). The release notes of 1.6.1 list the fixes; the reset-link fix is in `Recovery.php` (`trusted_site_url()`).

Do all of this on the NAS shell as the normal NAS user (no sudo, so the files are not root-owned). `D` is the value of `DOCKER_CONFIG_DIR`.

1. **Back up** (the old tree stays untouched as the rollback copy):
   ```
   B=$D/easyappointments-backup-$(date +%F); mkdir -p $B
   docker exec easy-appointments-mysql-1 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --events --databases "$MYSQL_DATABASE"' > $B/easyappointments.sql
   cp -a $D/easyappointments/config.php $D/easyappointments/application/config/email.php $B/
   ```
   The dump holds customer data: keep it private.
2. **Create the new app directory** (replaces the old git checkout, which also held the database files):
   ```
   mkdir $D/easyappointments-app && cd $D/easyappointments-app
   curl -fL -o /tmp/ea-1.6.1.zip https://github.com/alextselegidis/easyappointments/releases/download/1.6.1/easyappointments-1.6.1.zip
   echo "1671014c371519fa26e0a0a0dbdaa31047f5dda3156329faaea0662f095042f2  /tmp/ea-1.6.1.zip" | sha256sum -c
   unzip -q /tmp/ea-1.6.1.zip
   cp $B/config.php config.php
   cp $B/email.php application/config/email.php
   ```
   `config.php` keeps the installation settings only (`BASE_URL`, `LANGUAGE`, `DEBUG_MODE`, `DB_*`, Google keys); compare it with `config-sample.php`. `DB_HOST` must stay `mysql`. The release ships no root `config.php`, so a missing file stops `permissions-init` and with it the whole stack.
3. **Deploy** this stack (after `../traefik-public/` created `public-easy-appointments`). php-fpm builds on first start and the booking page shows "the database needs to be updated" until step 4.
4. **Migrate the database** right away (9 migrations, 60 to 69; rehearsed locally on a fresh 1.5.2 install, no output on success):
   ```
   docker exec -u www-data php-fpm php index.php console migrate
   ```
5. **Verify** `BASE_URL`, then see "After the first start".

Rollback: revert the commit and redeploy (the old images `easyappointments-php-fpm:latest` and `easyappointments-baikal:latest` stay on the NAS: do not prune them), then restore the dump into MySQL with `docker exec -i easy-appointments-mysql-1 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' < $B/easyappointments.sql`. Version 1.5.2 cannot run on the migrated schema, so the restore is mandatory.

Later updates are the same three moves: back up, replace the contents of `easyappointments-app/` with the new release (keep `config.php`, `application/config/email.php`, `storage/`), `console migrate`. Update the version in `swagger-ui/Dockerfile` as well.

## After the first start (UI and checks)

- **`BASE_URL`**: in 1.6.1 it is used for the password-reset link (the rest of the app takes the request host, which nginx pins). Check `grep "BASE_URL" config.php` shows `https://<subdomain>.<domain>` without a trailing slash, then use "Forgot password" for a test user and confirm the emailed link starts with that URL.
- **Default admin**: sign in at `/index.php/login`. A fresh Easy!Appointments install is `administrator` / `administrator`; whether the live account still accepts it was not tested. Change the password and the username under the account settings (1.6.1 asks for the current password) and check the other three accounts.
- **CAPTCHA**: Settings > Booking settings > CAPTCHA (covers booking, login and recovery). ALTCHA (proof of work, no third party) is under Settings > Integrations.
- **Login throttling**: five failed logins from one address in five minutes must answer HTTP 429 ("Too many login attempts"). Test it from a device on the public path, then confirm a different address is not blocked at the same time (this proves `PROXY_IPS` works).
- **SMTP**: send a test booking and check the confirmation mail arrives.
- Optional hardening on the public router (in `../traefik-public/`): the REST API answers on both `/index.php/api/` and `/api/`; block both prefixes there unless an external integration needs them from the internet. The proxy's global `frameDeny` header also stops the booking page from being embedded in another site.

## Database: MySQL 8.0 to 8.4 LTS (not done, your decision)

MySQL 8.0 reached end of life in April 2026; 8.0.46 is its last release, so the pinned tag gets no more fixes. 8.4 LTS is supported until 2032 and starts in place on an 8.0 data directory. Rehearsed locally (a fresh `mysql:8.0.46` data directory started with `mysql:8.4.13`: "Server upgrade from '80046' to '80413' completed" within seconds, data and a `caching_sha2_password` user intact; an application-only dump also restores into a fresh 8.4). Not rehearsed: this instance's own data directory.

1. Do it after 1.6.1 is running. Check no account uses `mysql_native_password` (disabled by default in 8.4): `SELECT user, host, plugin FROM mysql.user;`. The default plugin on this instance is `caching_sha2_password`.
2. Take a fresh dump (step 1 above), stop `nginx`, `php-fpm`, `phpmyadmin`, then `docker stop easy-appointments-mysql-1` (clean shutdown) and copy the data directory as root (the files belong to uid 999): `cp -a $D/easyappointments/docker/mysql $D/easyappointments/docker/mysql-8.0-backup`.
3. Change `mysql:8.0.46` to `mysql:8.4.13` in `docker-compose.yml` and redeploy. Check `docker logs easy-appointments-mysql-1 | grep -i upgrade`, then the booking page, a login and a test booking.
4. Rollback: stop MySQL, `rm -rf docker/mysql && mv docker/mysql-8.0-backup docker/mysql`, set the tag back to `mysql:8.0.46`, redeploy. An upgraded data directory cannot be opened by 8.0.

## Open points

- **PHP 8.1 in Baikal.** `ckulka/baikal:0.10.1-apache` (the newest Baikal image) ships PHP 8.1.33, which has no fix for the critical PHP vulnerabilities of 2026-10-21 (CVE-2026-109618/109619, "php2shell"; fixed in 8.2.35 / 8.3.36 / 8.4.27 / 8.5.12). The container is private-only and its setup wizard is still unclaimed (no admin password set, no CalDAV account in Easy!Appointments). Remove it from the compose file unless you use it, or finish its setup and keep it on the tailnet only.
- **php-fpm egress.** php-fpm needs outbound SMTP, so it keeps an ordinary network and can reach the LAN. Narrowing that needs an egress proxy or a gateway rule.
- **Rebuilding for security fixes.** The three built images use `pull_policy: build`. To pick up a new PHP or nginx patch release, change the version in the `Dockerfile` and in the `image:` tag, then redeploy.
- **Leftovers in the old tree.** `${DOCKER_CONFIG_DIR}/easyappointments/` still contains the old git checkout, a stale MySQL data directory in `mysql/` (from 2025-09-26, with TLS private keys) and the old nginx/php files. They were web-readable through the old nginx configuration, so treat the database passwords as exposed and rotate them (`ALTER USER`, then `config.php` and the stack environment), then archive and delete the old tree once everything runs.
