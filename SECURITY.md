# LearnTube security

LearnTube is a personal application. Both Windows launchers bind FastAPI to `127.0.0.1`. Mobile access uses Tailscale Serve on a private tailnet; do not use Tailscale Funnel or expose the API directly to the internet without adding authentication.

Gemini accepts local browser requests and, when explicitly configured in `backend/.env`, requests from one Tailscale Serve origin with a matching verified `Tailscale-User-Login` identity. Keep `TAILSCALE_AI_ORIGIN` and `TAILSCALE_AI_LOGIN` limited to your own tailnet address and login. Do not share this device with other tailnet users if you do not want them to access the rest of LearnTube, which has no application login.

Keep real credentials in `backend/.env`. This file, local SQLite databases, uploaded PDFs, virtual environments, and build output are ignored by Git. `frontend/.env.example` contains only a local API URL. Never put an API key in a `VITE_` variable; Vite embeds those variables in browser code.

Before sharing a repository or a bug report, review any attached logs and screenshots for personal study content. If a credential is ever committed, revoke it at the provider and replace it; removing it from a later commit does not remove it from Git history.
