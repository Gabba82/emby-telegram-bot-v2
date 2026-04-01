# Deployment Step by Step (Beginner Friendly)

Esta guia explica como desplegar el bot sin conocimientos tecnicos avanzados.

## 1. Preparar Telegram

### 1.1 Crear el bot

1. Abre Telegram y busca `@BotFather`.
2. Escribe `/newbot`.
3. Sigue las instrucciones y guarda el token final.

Ejemplo de token:

`123456789:AAExampleToken`

### 1.2 Anadir el bot al grupo o canal

1. Crea (o abre) el grupo/canal donde quieres los avisos.
2. Anade el bot como miembro.
3. Si es canal, dale permisos para publicar.

### 1.3 Obtener el chat_id

Metodo simple:

1. Envia un mensaje al grupo/canal con el bot dentro.
2. Abre en navegador:
`https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
3. Busca `chat` -> `id`.

Ejemplo de chat ID de supergrupo:

`-1001234567890`

Si quieres enviar a varios destinos:

`CHAT_IDS=-1001234567890,-1009876543210`

## 2. Preparar Emby

### 2.1 Obtener API key

1. Entra en Emby como admin.
2. Ve a configuracion de API keys.
3. Crea una nueva key y copiala.

### 2.2 Confirmar URL de Emby

Formato esperado:

`http://IP_O_HOST:8096/emby`

Ejemplo:

`http://192.168.1.112:8096/emby`

## 3. Descargar y configurar el proyecto

### 3.1 Clonar repo

```bash
git clone <URL_DEL_REPO>
cd emby-telegram-bot-v2
```

### 3.2 Crear archivo de entorno

Linux/macOS:
```bash
cp .env.example .env
```

Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

### 3.3 Editar `.env`

Rellena todos los campos:

```env
TELEGRAM_TOKEN=tu_token_de_botfather
CHAT_IDS=-1001234567890
EMBY_API_URL=http://192.168.1.112:8096/emby
EMBY_API_KEY=tu_api_key_de_emby
REQUEST_TIMEOUT_SECONDS=15
EPISODE_BUFFER_SECONDS=60
```

## 4. Desplegar con Docker

En la carpeta del proyecto:

```bash
docker compose up --build -d
```

Comprobar que esta levantado:

```bash
docker compose ps
```

Comprobar salud:

```bash
curl http://localhost:8081/health
```

Respuesta esperada:

```json
{"status":"ok"}
```

## 5. Configurar webhook en Emby

En el plugin de webhook de Emby:

- URL: `http://TU_HOST:8081/embyhook`
- Metodo: `POST`

## 6. Probar funcionamiento

1. Anade una pelicula o episodio en Emby.
2. Revisa Telegram.
3. Si falla, revisa logs:

```bash
docker compose logs -f
```

## 7. Actualizar a futuro

Cuando haya cambios nuevos:

```bash
git pull
docker compose up --build -d
```

## 8. Problemas frecuentes

### No llega nada a Telegram

- Revisa `TELEGRAM_TOKEN`.
- Asegura que el bot este dentro del grupo/canal.
- Verifica que `CHAT_IDS` sea correcto.

### Emby no alcanza el bot

- Comprueba IP/puerto.
- Comprueba firewall.
- Prueba desde la red de Emby:
  - `http://TU_HOST:8081/health`

### Mensajes con caracteres raros o fallos de parseo

- El bot ya escapa MarkdownV2, pero revisa logs si hay metadatos muy especiales.

## 9. Buenas practicas

- No subas `.env` al repositorio.
- Rota claves si se filtran.
- Haz backup de tu `.env`.
- Limita acceso al puerto 8081 a red de confianza.
