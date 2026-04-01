# Migration Guide (v1 -> v2)

## 1. Copy your current values

Take values from your old deployment:

- `TELEGRAM_TOKEN`
- `CHAT_IDS`
- `EMBY_API_URL`
- `EMBY_API_KEY`

## 2. Build v2 environment file

Create `.env` from `.env.example` and fill all values.

## 3. Deploy v2

Run:

```bash
docker compose up --build -d
```

## 4. Update Emby webhook

Point to:

- URL: `http://<HOST>:8081/embyhook`

## 5. Validate

Health check:

```bash
curl http://<HOST>:8081/health
```

Expected result:

```json
{"status":"ok"}
```
