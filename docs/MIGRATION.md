# Migration Guide (v1 -> v2)

## 1. Copy your current values

Take values from your old deployment:

- `TELEGRAM_TOKEN`
- `CHAT_IDS`
- `EMBY_API_URL`
- `EMBY_API_KEY`

## 2. Create new webhook secret

Generate a long random value for:

- `WEBHOOK_SECRET`

## 3. Build v2 environment file

Create `.env` from `.env.example` and fill all values.

## 4. Deploy v2

Run:

```bash
docker compose up --build -d
```

## 5. Update Emby webhook

Point to:

- URL: `http://<HOST>:8081/embyhook`
- Header: `X-Webhook-Secret: <WEBHOOK_SECRET>`

## 6. Validate

Health check:

```bash
curl http://<HOST>:8081/health
```

Expected result:

```json
{"status":"ok"}
```

