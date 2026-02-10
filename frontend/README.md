# ClawsCorp Frontend (Read-only Portal MVP)

## Frontend local dev

1. Install dependencies:
   ```bash
   npm --prefix frontend install
   ```
2. Configure required API base URL:
   - Copy `frontend/.env.example` to `frontend/.env.local`.
   - Set `NEXT_PUBLIC_API_URL` to your deployed Railway backend URL.
3. Run dev server:
   ```bash
   npm --prefix frontend run dev
   ```
4. Build production bundle:
   ```bash
   npm --prefix frontend run build
   ```

## Deployment configuration

- In Vercel project environment variables, set `NEXT_PUBLIC_API_URL` to the Railway API base URL.
- If `NEXT_PUBLIC_API_URL` is missing or empty, the portal renders a clear configuration error and skips network requests.
