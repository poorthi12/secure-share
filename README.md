# SecureShare

SecureShare is a student file-sharing and collaboration workspace built with FastAPI, Jinja2, MongoDB and Cloudinary. It supports verified student accounts, encrypted file uploads, private sharing, secure links, class groups, activity history, notifications and administrative oversight. There is no chat or messaging feature.

## Project walkthrough

This section explains the technologies and engineering ideas used in SecureShare, then follows the order a developer can use to set up, run, and understand the application. It documents the implementation in this repository; it is not a claim that every coding task was completed in this exact historical order.

### Technologies used

| Area | Technology | How it is used |
| --- | --- | --- |
| Language/runtime | Python 3.13+ | Application code and command-line setup scripts. |
| Web framework | FastAPI with Starlette | Async HTTP routes, request handling, middleware, sessions, static files, and lifecycle startup/shutdown. |
| Server | Uvicorn | Runs the ASGI application locally and in deployment. |
| HTML rendering | Jinja2 | Server-rendered pages and reusable template components. |
| Forms and validation | Python multipart support, Pydantic Settings, project validators | Handles uploads/forms and validates application configuration and user input. |
| Database | MongoDB with PyMongo `AsyncMongoClient` | Persistent document records, indexes, conditional updates, and replica-set transactions. |
| Local/test database | In-memory async document adapter | Enables disposable local previews and isolated tests without Atlas. Data is lost when the process stops. |
| File storage | Cloudinary authenticated raw assets | Stores encrypted upload payloads; application routes proxy downloads after authorization. Local demos can use encrypted files under `var/blobs`. |
| Cryptography | `cryptography` AES-GCM | Encrypts file bytes before storage and authenticates them when decrypted. |
| Password hashing | `argon2-cffi` | Hashes account passwords and optional share-link passwords. |
| Email | Python SMTP with STARTTLS | Delivers email verification, password reset, and selected account/share notifications. |
| Browser code | HTML, CSS, vanilla JavaScript | Responsive interface, theme and interaction behavior, upload progress, sharing, notifications, groups, and dashboard enhancements. |
| Tests | pytest and pytest-asyncio | Exercises authentication, permissions, sharing, uploads/downloads, groups, notifications, admin, OTP, and transaction behavior. |
| Environment/dependencies | `uv`, `pyproject.toml`, `uv.lock` | Reproducible Python environment and locked dependency versions. |

### Concepts and methods used

- **Layered application structure:** route modules handle HTTP requests, services implement application operations, core modules hold security and permission rules, integrations wrap external systems, and templates render the interface.
- **Dependency and lifecycle management:** FastAPI's lifespan initializes settings, database, storage, encryption, and email services at startup, then closes clients during shutdown. Services are attached to `app.state` for request handlers.
- **Document-oriented persistence:** user, file, share, group, request, notification, OTP, download, and activity records are stored as MongoDB documents behind a small async database interface.
- **Authentication and authorization:** signed sessions identify a user; route dependencies require login or CSRF validation; service and route checks enforce ownership, share status, group membership, and administrative roles.
- **Defense in depth:** input checks, upload limits and quotas, route-level rate limits, email verification, secure cookies, CSRF tokens, security headers, and server-side file access checks cover different points in a request.
- **Password and token handling:** passwords use Argon2 hashes. One-time codes and share-link tokens are represented by hashes in persistent records, and signed session/token secrets come from configuration.
- **Authenticated encryption:** AES-256-GCM uses a random nonce per upload and the file ID as associated data. GCM detects ciphertext modification; the nonce and encrypted bytes are stored together. The encryption key must remain available to decrypt existing files.
- **Transactions and saga compensation:** database changes that belong together are grouped in a transaction where MongoDB supports it. Uploads first write the encrypted blob, then persist metadata/quota/audit changes; a compensation action deletes the blob if persistence fails.
- **Atomic conditional updates:** a download-limit condition is checked as part of the update so concurrent requests cannot all consume the last available download.
- **Service adapters:** database and storage interfaces allow persistent services in configured deployments and substitutes for local previews/tests.
- **Auditability and notifications:** important events are recorded in activity logs; in-app notifications and optional email communicate events to users.
- **Server-rendered progressive interface:** Jinja renders complete pages, with CSS and small JavaScript files adding responsive layout and interactions.

### Build and run, step by step

1. **Install prerequisites.** Use Python 3.13 or newer and install `uv`. For a persistent deployment, create MongoDB Atlas, Cloudinary, and SMTP credentials. A local preview can use the in-memory database and local blob storage, but it is temporary.
2. **Create the environment.** From the repository root, run `uv sync` to create the virtual environment and install the dependencies recorded in `uv.lock`.
3. **Create configuration.** Copy `.env.example` to `.env`. For persistent development, set the MongoDB URI/database, Cloudinary credentials, SMTP values, and unique session, token, and encryption secrets. Keep `.env` private and out of source control.
4. **Choose local preview or persistent mode.** For a disposable preview, set `LOCAL_DEMO_MODE=true`; the database records are memory-only and uploaded encrypted blobs use local storage. For normal development with persistence, leave demo mode off and configure `MONGODB_URI`. Production requires persistent MongoDB, Cloudinary, SMTP, and explicit secrets.
5. **Start the app.** Run `uv run uvicorn app.main:app --reload`, then open <http://localhost:8000>. Startup validates required production configuration, connects to MongoDB when configured, and ensures indexes.
6. **Create an account.** Register with an email address, receive the six-digit verification code through SMTP, and verify it before signing in. In-app account creation grants the student role; use the admin script for the first administrator.
7. **Upload and organize files.** The upload route validates the file name, size, group permission, and storage quota; encrypts its bytes; writes the encrypted object to storage; then records file metadata and usage. The app supports personal files, group repositories, and file requests.
8. **Share securely.** Create a recipient share or link. The app checks permissions on the server for each download. Link shares can have a password, expiry, and download limit, and can be revoked.
9. **Use administration and maintenance scripts.** `uv run python scripts/create_admin.py` creates an administrator in configured MongoDB. `uv run python scripts/create_indexes.py` explicitly creates database indexes. App startup also ensures them.
10. **Run the test suite.** Use `uv run pytest`. Tests use the isolated in-memory database and local encrypted blob storage; SMTP is stubbed, so external services are not required.

### Request flow: encrypted file upload

1. The browser submits a multipart form to the authenticated upload route, including a CSRF token.
2. The route checks login, upload permission, filename, maximum size, and remaining account quota.
3. The application encrypts the file bytes with AES-256-GCM and a fresh nonce, binding the ciphertext to the generated file ID.
4. Storage saves only the encrypted payload and returns a storage key.
5. A database transaction records file metadata, updates the owner's used storage, and records the activity event.
6. If the metadata transaction fails, the saga's compensation step deletes the newly written blob.

### Request flow: file download

1. The browser requests a download through SecureShare; it does not receive a permanent public Cloudinary asset URL.
2. The server checks that the requester owns the file or has valid recipient, group, or link access.
3. It checks that the share is active and that any password, expiry, and download-limit rules pass.
4. The server fetches the encrypted blob, authenticates and decrypts it, records download history, and returns the bytes with a safe attachment filename.

### Where to find things

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI application, startup/shutdown, middleware, router registration, and error handlers. |
| `app/routes/` | HTTP endpoints grouped by feature. |
| `app/services/` | Reusable authentication, file, sharing, group, notification, activity, and admin operations. |
| `app/core/` | Encryption, password/token security, permissions, errors, and rate limiting. |
| `app/transactions/` | Upload/share/download/revocation transaction helpers and saga coordination. |
| `app/integrations/` | MongoDB, Cloudinary/local blob, and SMTP adapters. |
| `app/models/` and `app/schemas/` | Domain record definitions and request/data validation schemas. |
| `app/middleware/` | Security headers and request logging/authentication middleware. |
| `templates/` | Jinja page templates and reusable components. |
| `static/css/` and `static/js/` | Stylesheets and browser-side interactions. |
| `scripts/` | Admin creation, index creation, and seed helper scripts. |
| `tests/` | Automated behavior and security regression tests. |

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

### Vercel

Import the repository with its root directory set to the folder containing `main.py` and `pyproject.toml`. Select the **FastAPI** framework preset; Vercel discovers the ASGI app exported by root `main.py`. The project configuration also sets the FastAPI entrypoint and keeps the mounted static files in the function so the app's security middleware and `/static/...` URLs continue to work.

Before deploying, add these environment variables in Vercel Project Settings for each environment: `APP_ENV=production`, `LOCAL_DEMO_MODE=false`, `MONGODB_URI`, `MONGODB_DATABASE`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SESSION_SECRET`, `JWT_SECRET`, and `ENCRYPTION_KEY`. Use a real MongoDB Atlas URI and Cloudinary credentials. Vercel sets `VERCEL=1` for deployed functions, so the app applies its production checks even if `APP_ENV` was accidentally omitted; without Cloudinary credentials it will refuse to start instead of saving uploads to temporary local disk. Confirm the startup log says `File storage configured: Cloudinary` after deployment. Changes to Vercel environment variables require a new deployment.

The local file system on Vercel is temporary. Persistent uploads must use Cloudinary, and records must use MongoDB Atlas; do not enable `LOCAL_DEMO_MODE` in deployment. Vercel's FastAPI runtime is one serverless function, so the process-local rate limiter is not shared across instances. Configure Vercel's routing/security controls or a shared rate limiter if login throttling must be consistent across instances.
