# Gotcha: Jellyfin `LibraryMonitor` permission error - known dead end, don't re-diagnose

Jellyfin startup logs sometimes show `System.UnauthorizedAccessException` /
`IOException: Permission denied` from `LibraryMonitor` (the inotify-based
live directory watcher) for specific library folders. As of 2026-09-28 this
was chased to exhaustion on one specific folder
(`tv-shows/Rick and Morty Season 1-5/Season 5`) and is confirmed to be
**cosmetic, not a real permission problem**.

**Impact:** none. Actual file reads/playback from the affected folder work
fine. Jellyfin falls back to watching the parent directory - the only
effect is new files dropped directly into that folder miss the *instant*
auto-scan (the daily scheduled scan still covers them).

**Every OS/NAS-level mechanism was ruled out**, in order: ownership
(`chown -R krit:admin` fixed every OTHER affected folder but not this one,
confirmed via `chown -Rc` reporting zero changes needed - ownership was
already fully correct), ACL (`getfacl` byte-identical to a working
sibling folder), the `ugacl`/`+` flag, extended attributes, `lsattr`,
btrfs subvolume boundaries, stray symlinks/root-owned nested files, hidden
characters in the folder name, inotify/fd resource limits, and
kernel/LSM-level denial (`dmesg`/`journalctl -k` showed nothing at the
exact failure timestamp).

**Conclusion:** very likely a bug/quirk internal to .NET's Linux
`FileSystemWatcher` implementation (a known class of issue - transient
races during recursive-watch enumeration sometimes get mis-reported as
`UnauthorizedAccessException`), not a real permission/ACL/ownership/NAS
issue.

**How to apply:**
- If this exact folder (`Rick and Morty Season 1-5/Season 5`) shows this
  error again: this is closed/final, don't re-attempt ownership/ACL/rename
  fixes on it without genuinely new evidence.
- If a **different, new** folder shows this same error class: try the
  ownership fix first (`chown -R <owner>:<group>`) - it's proven effective
  for that general class of issue on other folders. Only conclude "harmless
  quirk, ignore it" if ownership normalization is confirmed via
  restart+logs to NOT fix that specific new folder too.
