# LearnTube

Personal IELTS study platform built with React, TypeScript, Vite, Tailwind CSS, shadcn/ui, FastAPI, SQLModel, and SQLite.

## Start everything (Windows)

Double-click `start-learntube.bat` in the project folder. It starts the API on port 8001, the frontend on port 5173, and opens LearnTube in your browser.

## Use from an iPhone over your private Tailscale network (Windows PC)

Install Tailscale on this PC and your iPhone and sign in to the same tailnet. On this PC, enable Tailscale Serve once with `tailscale serve --bg 5173` in an Administrator terminal. Double-click `start-learntube-mobile.bat` to run the API and UI on this PC. In iPhone Safari, open the HTTPS address shown by `tailscale serve status`. Keep Tailscale connected on the iPhone, this PC awake, and both LearnTube command windows open. The existing `start-learntube.bat` remains for PC-only use; close its windows before starting mobile mode because both use ports 5173 and 8001.

Mobile mode uses a separate Vite configuration to proxy `/api` through the same private HTTPS origin. The one-line `frontend/.env.mobile` is created from `frontend/mobile.env.template` on first start. Tailscale Serve is private to devices allowed in your tailnet; do not enable Tailscale Funnel. The Gemini endpoint intentionally accepts only localhost browser origins, so Gemini is unavailable from the iPhone until the app has an explicit remote-access security design. Other app data stays in the existing local SQLite database and PDF uploads on this PC. Stop sharing with `tailscale serve --https=443 off` in an Administrator terminal.

## Frontend

```powershell
cd frontend
Copy-Item .env.example .env
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173`.

## Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

The health check is available at `http://localhost:8001/api/health`.

## Notebook

Open **Notebook** in the sidebar. Create a notebook, then add a blank note or use the **Grammar** template. Notes use Markdown syntax and save automatically after editing; Ctrl+S saves immediately. Search titles and contents within the selected notebook or choose **All notes** to search across notebooks. Select text in the editor and choose **Add selection to Vocabulary** to use the existing vocabulary form. A failed save leaves a local draft in the browser for recovery; the editor shows an error until you edit and retry.

## Dashboard and study time

Open `/` or `/dashboard` for the 365-day activity calendar, weekly breakdown, streaks, vocabulary and writing progress, and recent activity. Study time begins accumulating with this version; past timer elapsed values and video playback positions are not treated as verified study time. Video time is recorded only during visible playback. Flashcard time ends after 30 seconds without interaction; writing time ends after 20 seconds without editing and stops when paused or finished. Activity is saved in short increments in UTC. The browser's IANA timezone determines calendar days. Windows Python needs the `tzdata` dependency in `backend/requirements.txt` for this conversion.

## PDF learning

Open `/pdfs` to upload a PDF from your computer or drag it into the library. Uploaded files are stored in `backend/uploads/pdfs/` (outside SQLite); metadata, notes, reading position, and PDF vocabulary are stored in SQLite. You can scroll the rendered pages, change page and zoom, select text, and use **Add to Vocabulary**. PDF words join the existing review queue. Removing a PDF keeps its saved words and review history and labels their source unavailable. Scanned image-only PDFs can be read, but their text cannot be selected without OCR.

The default upload limit is 50 MB. Set `MAX_PDF_SIZE_MB` and optionally `PDF_STORAGE_DIR` in `backend/.env` to change it. On an existing installation, run `npm.cmd install` in `frontend/` and `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` in `backend/` once. The backend adds the PDF tables and vocabulary source columns without recreating the database. Run the backend checks with `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` (install `requirements-dev.txt` for the HTTP tests).

## IELTS Writing

Open `/writing` to start a Task 1 or Task 2 session with your own prompt. Drafts autosave after a short pause; the browser keeps a temporary local recovery copy while a save is pending. The timer stores UTC start times and accumulated elapsed time in SQLite, so refreshing the page does not restart it. Completed sessions are read-only. Use the project root `start-learntube.bat` to start both services, then open `http://localhost:5173/writing`.

### ChatGPT feedback

In a Writing workspace, **Copy for ChatGPT** copies the task, original question and essay, and a request covering the four IELTS Writing criteria. For Task 1 visuals, attach the original image to ChatGPT yourself. Evaluate it separately in ChatGPT, then paste the response into **ChatGPT Feedback**. Feedback saves automatically, can be saved manually, edited later, and viewed with a safe Markdown preview. It is stored with the Writing session without changing the essay. LearnTube does not send Writing content to Gemini.

## Vocabulary definition sources

Selecting text in a YouTube transcript, PDF, or Notebook note opens Add to Vocabulary with the expression filled in and Definition and Examples blank. Choose **Free Dictionary** or **Gemini** in the form; neither generates a definition automatically. The English-to-English [Free Dictionary API](https://dictionaryapi.dev/) is reached through `GET /api/dictionary/lookup?word=...`, with no API key. Gemini uses the existing optional backend configuration in `backend/.env`. Dictionary results provide the first available definition and up to three real examples, with a compact selector for other meanings. Unknown phrases can still be saved with your own definition. Results remain editable and nothing is saved until you click **Save**. Only the word or phrase is sent to the chosen service; notes, transcripts, and PDFs are not sent.

## Vocabulary review schedule

New expressions are due immediately. Again schedules a card 10 minutes later and sets it to Learning. Good schedules a new card tomorrow; Easy schedules it in four days. For a reviewed card, Good multiplies the previous interval by its ease factor (initially 2.5, minimum one day); Easy multiplies it by the ease factor and 1.3. Again resets the interval and lowers ease by 0.2, to a minimum of 1.3. Easy raises ease by 0.1, to a maximum of 3.0. A card is Mastered only after at least three successful reviews and a scheduled interval of at least 21 days. Due times are compared in UTC and shown in the browser's local time.

Run scheduling checks with `cd backend` then `.\.venv\Scripts\python.exe -m unittest discover -s tests`.

## Structure

- `frontend/` â€” Vite React application and initial UI.
- `backend/app/` â€” FastAPI app, settings, and SQLModel setup.
- `backend/learntube.db` â€” SQLite database, created automatically at startup.
