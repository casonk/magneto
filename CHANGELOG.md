# Changelog

## Unreleased

- Answer `/_portfolio/*` itself from a vendored portfolio site seam (`magneto/portfolio/`), so the theme and top bar work with no Caddy in front: the owner-only site store first, then a pinned fallback copy. Add `/.portfolio` (ignored) and `config/portfolio-site.example.toml`. See traction-control `docs/portfolio-sites.md`.

- Follow the portfolio system themes: the page takes its colours from the shared tokens (`/_portfolio/theme.css`), so the theme chosen in the top bar restyles it. The built-in dark-mode media query is gone; the theme replaces it.

- Load the portfolio top bar (`<script src="/_portfolio/chrome.js" defer></script>`, served by the shared Caddy) on the torrent page, so the global navigation and theme rotator appear here too.
- Stop the torrent list's four-second refresh from discarding a half-made choice: it is
  held while a rate or seed-ratio control is focused or changed, with a note that
  updates are paused.
- Add a **Defaults for new torrents** panel (download and upload rate, target seed
  ratio, do-not-seed). Saved values override the `MAGNETO_DEFAULT_*` environment
  settings and persist in `MAGNETO_SETTINGS_FILE` (default
  `~/.local/state/magneto/settings.json`; set it empty to hide the panel).

- Add a per-torrent target seed ratio control, and configurable defaults for new
  torrents (`MAGNETO_DEFAULT_DOWNLOAD_LIMIT_KBPS`, `MAGNETO_DEFAULT_UPLOAD_LIMIT_KBPS`,
  `MAGNETO_DEFAULT_SEED_RATIO`) applied after the add; `MAGNETO_NO_SEED_BY_DEFAULT`
  still wins over the upload cap and ratio.
- Add per-torrent download-rate presets and links from completion/error
  notifications to the torrent card.
- Initial `magneto` scaffold for private iPhone-friendly torrent control via Transmission RPC.
