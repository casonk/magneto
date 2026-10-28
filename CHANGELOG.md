# Changelog

## Unreleased

- Add a per-torrent target seed ratio control, and configurable defaults for new
  torrents (`MAGNETO_DEFAULT_DOWNLOAD_LIMIT_KBPS`, `MAGNETO_DEFAULT_UPLOAD_LIMIT_KBPS`,
  `MAGNETO_DEFAULT_SEED_RATIO`) applied after the add; `MAGNETO_NO_SEED_BY_DEFAULT`
  still wins over the upload cap and ratio.
- Add per-torrent download-rate presets and links from completion/error
  notifications to the torrent card.
- Initial `magneto` scaffold for private iPhone-friendly torrent control via Transmission RPC.
