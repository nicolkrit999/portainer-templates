---
name: gokapi-file-requests-are-a-user-permission
description: Gokapi v2.2.4 has no env var to disable file requests (anonymous uploads); it is a per-user permission, and the guest-upload "0" limits mean unlimited
metadata:
  type: reference
---

In Gokapi v2.2.4 (verified from `internal/environment/Environment.go` and `internal/models/User.go`, 2026-11-03) "file requests" (outsiders upload via a link) are the per-user permission `UserPermGuestUploads`. `GOKAPI_GUEST_UPLOAD_BY_DEFAULT` only sets that permission for NEW users (default false); existing users keep the stored value, so the only way to turn it off is the admin UI (Users). No global env switch exists.

Limits: `GOKAPI_MAX_FILES_GUESTUPLOAD=0` means unlimited file count; `GOKAPI_MAX_SIZE_GUESTUPLOAD=0` means limited only by `GOKAPI_MAX_FILESIZE`. Upstream defaults are 100 files / 10240 MB; `GOKAPI_MIN_FREE_SPACE` 400 MB. The compose currently sets 100 / 10240 for guests, `GOKAPI_MAX_FILESIZE=10485760` (MB, 10 TB) and `GOKAPI_GUEST_UPLOAD_BY_DEFAULT=false`. Gokapi also auto-adds its own Docker subnet to trusted proxies unless `GOKAPI_DISABLE_DOCKER_TRUSTED_PROXY=true`.

**Why:** the public-access rollout needed to know whether anonymous upload could be closed from compose; it cannot.
**How to apply:** when asked to "disable file requests" or tighten guest uploads on Gokapi, give the UI step plus the env limits above; do not promise an env-only fix. As of 2026-11-03 the latest release was still v2.2.4 (2026-03-10), so the March 2026 advisories had no fixed version to move to (UNVERIFIED since; re-check upstream before relying on it).
