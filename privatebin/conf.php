;<?php http_response_code(403); /*
; PrivateBin configuration for a public, anonymous drop box.
; Every setting is documented at https://github.com/PrivateBin/PrivateBin/wiki/Configuration.
; Keys not listed here keep their built-in defaults.

[main]
; Text pastes only: no attachments, no comments.
fileupload = false
discussion = false
opendiscussion = false

password = true
burnafterreadingselected = false
defaultformatter = "plaintext"

; Maximum size of one paste in bytes (the encrypted payload counts, so the
; usable text is a little smaller). The image's own hard cap is 15 MiB.
sizelimit = 1048576

templateselection = true
availabletemplates[] = "bootstrap5"
availabletemplates[] = "bootstrap"
availabletemplates[] = "bootstrap-page"
availabletemplates[] = "bootstrap-dark"
availabletemplates[] = "bootstrap-dark-page"
availabletemplates[] = "bootstrap-compact"
availabletemplates[] = "bootstrap-compact-page"

languageselection = true

[expire]
default = "1week"

; No entry may be 0 (never expires): expired pastes are what the purge removes.
[expire_options]
5min = 300
10min = 600
1hour = 3600
1day = 86400
1week = 604800
1month = 2592000
1year = 31536000

[formatter_options]
plaintext = "Plain Text"
syntaxhighlighting = "Source Code"
markdown = "Markdown"

[traffic]
; Seconds between two requests from the same client IP.
limit = 10

; The client IP comes from the proxy's X-Forwarded-For. Traefik discards any
; value sent by the client and writes the real peer address, so it cannot be
; spoofed on the public path.
header = "X_FORWARDED_FOR"

; Private, LAN and tailnet source addresses skip the limit; internet clients
; never have such an address.
exempted = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10"

; Anyone may create pastes: "creators" is deliberately not set.

[purge]
; Expired pastes are deleted when a paste is created, at most one purge per
; "limit" seconds and "batchsize" pastes per purge. There is no scheduled job.
limit = 300
batchsize = 100

[model]
class = Filesystem
[model_options]
dir = PATH "data"
