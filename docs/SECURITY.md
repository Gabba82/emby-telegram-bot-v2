# Security Notes

## Secret management

- Never commit real tokens or keys.
- Keep runtime secrets only in `.env` or in your secret manager.
- Rotate `TELEGRAM_TOKEN` and `EMBY_API_KEY` if they were ever exposed.

## Network hardening

- Expose port `8081` only to trusted network zones.
- Prefer placing the service behind reverse proxy and IP allow-list.
- If possible, terminate TLS at proxy and enforce HTTPS from client side.
