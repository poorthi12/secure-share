# SecureShare

SecureShare is a student file-sharing and collaboration workspace built with FastAPI, Jinja2, MongoDB and Cloudinary. It supports verified student accounts, encrypted file uploads, private sharing, secure links, class groups, activity history, notifications and administrative oversight. There is no chat or messaging feature.

## Features

- Argon2 password hashing, six-digit email verification codes, password recovery, secure signed sessions and CSRF checks.
- AES-256-GCM encryption of file bytes before storage, with file-specific associated data and a fresh nonce for each upload.
- Server-authorized file downloads, authenticated Cloudinary assets, hashed link tokens, optional Argon2 link passwords, expirations, download limits and immediate revocation.
- Atomic MongoDB transactions for related writes, atomic download-limit consumption and a compensation step to delete an uploaded blob if its metadata transaction fails.
- Group repositories with owner, admin and member roles, per-member upload permission, in-app notifications, private activity history and admin views.
- Responsive Jinja pages with light, dark and system themes, accessible focus styles, reduced-motion support, upload progress, confirmation dialogs and keyboard search (`Ctrl/Cmd+K`).

## Architecture

`app/routes` contains thin page handlers. `app/services` contains file authorization, OTP, activity and notification operations. `app/core` contains cryptography, password/token functions, permissions, and rate limiting. `app/integrations` contains MongoDB, Cloudinary and SMTP adapters. `app/database.py` exposes one small async document-store interface backed by PyMongo's `AsyncMongoClient` in configured deployments and a process-local adapter for tests and unconfigured local previews.

Production uses MongoDB Atlas. The process-local adapter is only a development/test convenience and loses its records on restart. Configure MongoDB before deploying. MongoDB multi-document transactions require a replica set or sharded deployment; Atlas provides that transaction-capable topology. Critical share, upload metadata, revocation, download tracking, group and notification writes use a transaction.

## Encryption and file access

The app encrypts the complete file payload using AES-256-GCM before calling Cloudinary. The stored payload includes a 12-byte random nonce followed by the authenticated ciphertext. A 32-byte key comes from `ENCRYPTION_KEY`; the local development fallback is generated into the ignored `var/dev-encryption.key` file. Production refuses to start without an explicit key. Back up the key securely and plan key rotation before changing it: existing files cannot be decrypted with a different key.

MongoDB stores file metadata and an internal storage key. Cloudinary assets are uploaded as authenticated raw resources. Its signed delivery URL is generated server-side and fetched by the app; a permanent Cloudinary URL is not sent to a browser. The download route checks owner, recipient or group membership, active share state, expiry, password and the remaining limit before decrypting and returning bytes. For deployments that omit Cloudinary, encrypted blobs are stored under `var/blobs` for local development only.

## Transactions and compensation

Uploads follow a small saga: read and validate the upload, encrypt and store the payload, then atomically create metadata, update quota and write the audit event. If the database transaction fails, the just-created Cloudinary or local blob is deleted. When deletion of an already committed blob fails, metadata remains unavailable to users and a cleanup-queue record is written for an operator or background cleanup job. Download limits use a conditional atomic update inside the same transaction as download history, so only one concurrent request can consume the final slot.

## Setup

Requirements: Python 3.13+, UV, a MongoDB Atlas URI for persistent data, Cloudinary credentials for hosted file storage, and an SMTP account for verification and recovery email.

```powershell
uv sync
Copy-Item .env.example .env
```

Set the required production values in `.env` (or inject them through your deployment secret manager). Generate secrets with Python:

```powershell
uv run python -c "import base64,secrets; print('SESSION_SECRET='+secrets.token_urlsafe(48)); print('JWT_SECRET='+secrets.token_urlsafe(48)); print('ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Configure `MONGODB_URI` and `MONGODB_DATABASE` (`MONGODB_DB_NAME` is also accepted), Cloudinary's cloud name/key/secret, SMTP host/port/credentials/from address, `SESSION_SECRET`, `JWT_SECRET`, and `ENCRYPTION_KEY`. Keep `.env` out of source control. Set `LOCAL_DEMO_MODE=true` for a disposable local preview; this uses an in-memory database and encrypted local blobs even when cloud credentials are present. It is rejected in production. Email codes will not be delivered until SMTP is configured.

## Development

```powershell
uv run uvicorn app.main:app --reload
```

Open <http://localhost:8000>. Register with an email account that your SMTP service can deliver to, then enter the verification code. To create an administrator, run `uv run python scripts/create_admin.py` with a configured MongoDB URI. `uv run python scripts/create_indexes.py` explicitly creates database indexes; app startup also ensures them.

### Environment variables

See `.env.example`. `MAX_UPLOAD_BYTES` defaults to 100 MiB. `STORAGE_QUOTA_BYTES` defaults to 2 GiB per account. OTP codes expire after five minutes, allow five attempts, and can be resent after 60 seconds. `APP_ENV=production` requires MongoDB, a session secret and an encryption key, and enables secure cookies. TLS termination should be configured at the hosting platform or reverse proxy.

## Testing

```powershell
uv run pytest
```

Tests use the isolated in-memory adapter and local encrypted blob storage; they do not require Atlas or Cloudinary credentials. SMTP calls are stubbed in tests.

## Security notes

- Passwords, link passwords and OTP codes are never stored in plaintext. OTP mail contents are not logged.
- File names are sanitized, uploads are size limited, and file bytes are not served from permanent Cloudinary URLs.
- Forms use session-bound CSRF tokens. Cookies are HTTP-only, SameSite=Lax, and `Secure` in production.
- Security headers include a restrictive content security policy, anti-framing, MIME sniffing protection and referrer controls.
- Authentication routes have a process-local rate limiter. For multiple workers, place a shared rate limiter or API gateway in front of the app; a local in-memory counter is not shared across workers.
- The app records download IP and user agent for auditing. Configure retention and privacy notice requirements for your institution.
- Seed or create the first admin through the script; ordinary registration always creates a student role.

## Deployment guidance

Run multiple Uvicorn worker processes behind a TLS reverse proxy. Set `APP_ENV=production`, all secrets, MongoDB Atlas, Cloudinary and SMTP before starting. Use Atlas replica-set transactions, restrict the database user to the application database, limit Cloudinary API permissions, keep secret backups separate from file backups, and monitor transaction errors, failed logins and the cleanup queue. Do not use the in-memory database or local blob mode for production.
