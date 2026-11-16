# LearnTube security

LearnTube is a personal local application. Start the API with `start-learntube.bat`, which binds FastAPI to `127.0.0.1`. Do not expose the API to the internet without adding authentication.

Keep real credentials in `backend/.env`. This file, local SQLite databases, uploaded PDFs, virtual environments, and build output are ignored by Git. `frontend/.env.example` contains only a local API URL. Never put an API key in a `VITE_` variable; Vite embeds those variables in browser code.

Before sharing a repository or a bug report, review any attached logs and screenshots for personal study content. If a credential is ever committed, revoke it at the provider and replace it; removing it from a later commit does not remove it from Git history.
