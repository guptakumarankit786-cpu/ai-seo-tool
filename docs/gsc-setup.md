# Google Search Console setup

The app connects to Search Console through your own Google OAuth client. You set this up once in Google Cloud.

## 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com/> and sign in.
2. Use the project picker (top bar) → **New project** → name it e.g. `ai-seo-tool` → **Create**.
3. Make sure the new project is selected.

## 2. Enable the Search Console API

1. Go to **APIs & Services → Library**.
2. Search **Google Search Console API** → **Enable**.

## 3. Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen** (shown as **Google Auth Platform** in newer consoles).
2. **User type:** External → fill in app name (`AI SEO Tool`), your support email and developer email.
3. **Scopes / Data access:** add
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/webmasters.readonly`
4. **Test users / Audience:** add every Google account you'll connect (e.g. the one that owns your GSC properties).
   While the app is in *Testing* mode, only these accounts can connect, and Google expires refresh tokens after 7 days — you'll need to reconnect weekly until the app is published.

## 4. Create the OAuth client

1. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID** (or **Clients → Create client**).
2. **Application type:** Web application. Name: `AI SEO Tool (local)`.
3. **Authorized redirect URIs:** add exactly
   ```
   http://localhost:8000/api/gsc/oauth/callback
   ```
4. **Create**, then copy the **Client ID** and **Client secret**.

## 5. Add the credentials to `.env`

In the project root, open `.env` (copy it from `.env.example` if it doesn't exist) and set:

```
GOOGLE_CLIENT_ID=<your client id>
GOOGLE_CLIENT_SECRET=<your client secret>
```

`.env` is gitignored — never commit it. Then restart the backend:

```bash
docker compose restart backend
```

## 6. Connect

Open <http://localhost:3000/integrations> → **Connect** → choose your Google account → allow access.
Your properties appear in the list; click **Sync 90 days** to pull data, then **Open** to view the dashboard.
