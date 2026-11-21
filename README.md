# LearnTube

Personal IELTS study platform built with React, TypeScript, Vite, Tailwind CSS, shadcn/ui, FastAPI, SQLModel, and SQLite.

## Start everything (Windows)

Double-click `start-learntube.bat` in the project folder. It starts the API on port 8001, the frontend on port 5173, and opens LearnTube in your browser.

The launcher checks installed dependencies and waits for both services to respond before opening the page. If LearnTube is already running, it reuses the existing services. Run `start-learntube.bat --check` in Command Prompt to check dependencies without starting anything. Close the **LearnTube API** and **LearnTube Frontend** command windows to stop the local application.

Video and PDF notes keep an unsaved recovery draft in this browser if a save fails or you leave while a save is pending. Reopen the same item in the same browser to retry. Wait for **Saved** before creating a backup: browser recovery drafts are not included in backup ZIPs.

## Use from an iPhone over your private Tailscale network (Windows PC)

Install Tailscale on this PC and your iPhone and sign in to the same tailnet. On this PC, enable Tailscale Serve once with `tailscale serve --bg 5173` in an Administrator terminal. Double-click `start-learntube-mobile.bat` to run the API and UI on this PC. In iPhone Safari, open the HTTPS address shown by `tailscale serve status`. Keep Tailscale connected on the iPhone, this PC awake, and both LearnTube command windows open. The existing `start-learntube.bat` remains for PC-only use; close its windows before starting mobile mode because both use ports 5173 and 8001.

The frontend proxies `/api` to the local backend in both PC and mobile modes, so the browser uses the same origin for application requests. The one-line `frontend/.env.mobile` is created from `frontend/mobile.env.template` on first start. Tailscale Serve is private to devices allowed in your tailnet; do not enable Tailscale Funnel. Gemini can also work from the iPhone when `TAILSCALE_AI_ORIGIN` is set to the exact private HTTPS URL and `TAILSCALE_AI_LOGIN` to your Tailscale login in the ignored `backend/.env`; the backend checks both plus Tailscale's identity header. The optional `AI_DAILY_REQUEST_LIMIT` remains a local safeguard. Other app data stays in the existing local SQLite database and PDF uploads on this PC. Stop sharing with `tailscale serve --https=443 off` in an Administrator terminal.

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

## Local backup and restore

On this PC, open **Settings → Backup & Restore** at `http://localhost:5173/settings` (or `http://127.0.0.1:5173/settings`). Click **Create Backup**. In browsers with a save dialog, choose where to save the ZIP; otherwise your browser downloads `learntube-backup-YYYY-MM-DD-HHMMSS.zip` to its usual Downloads folder. Move a copy to another drive or external storage **outside the LearnTube project folder**. A backup stored only beside the project could be lost with the project or PC.

The ZIP contains `database.sqlite3`, referenced files under `uploads/pdfs/`, and `manifest.json` with the creation time, format/schema versions, record counts, sizes, and SHA-256 checksums. SQLite is captured through its online backup API, including committed WAL data. The database contains videos, transcripts, notes, PDF and playback progress, vocabulary and review history, Writing sessions and feedback, Notebook content, and Dashboard activity. Derived search indexes and extracted PDF text are rebuilt from the saved records and PDFs after restoration. Environment files, API keys, application source, dependencies, caches, and temporary files are excluded. Unsaved browser-only drafts are also excluded; wait for the editor to report **Saved** before backing up. If you use `PDF_STORAGE_DIR`, the referenced PDFs from that configured location are included using portable ZIP paths.

To check a ZIP, choose it under **Restore a backup**. LearnTube verifies its manifest, checksums, SQLite integrity, table structure, relationships, and PDF inventory, then displays its date and record summary. Selecting a file does **not** restore it. To restore, review the warning, click **Restore Backup**, and confirm in the browser dialog. The current SQLite database and PDFs are saved first as `backend/safety-backups/learntube-before-restore-*.zip`. LearnTube pauses other API requests while it replaces data, then reloads the page. If replacement fails, it tries to recover the previous data from that safety ZIP. An interrupted operation is recovered before the backend starts again. If startup recovery reports an error, keep the safety ZIP and `backend/.backup-state/` intact before seeking help.

After reinstalling or moving to another computer, install and start LearnTube as described above, then use Settings to inspect and restore your saved ZIP. Re-enter your own API keys and other secrets in `backend/.env`; they are never backed up. Keep the same or a compatible LearnTube version: this backup format currently supports format 1 and schema 1. Backup and restore endpoints are reachable only from the PC itself, even when the rest of LearnTube is shared privately through Tailscale. The backend remains bound to `127.0.0.1` by the provided launch scripts. ZIP uploads are limited to 2 GiB and expanded contents to 4 GiB. A restore coordinates this app's requests but cannot guarantee a single atomic transaction across SQLite and PDF files; the pre-restore safety ZIP and startup recovery protect interrupted operations.

## Notebook

Open **Notebook** in the sidebar. Create a notebook, then add a blank note or use the **Grammar** template. In **Edit**, type Markdown or select text and use the Heading, Bold, Italic, List, Quote, Link, and Code buttons. Switch to **Preview** to see the formatted note, then return to Edit to make changes. For example, `**word**` appears bold in Preview. Notes save automatically after editing; Ctrl+S saves immediately. Search titles and contents within the selected notebook or choose **All notes** to search across notebooks. Select text in the editor and choose **Add selection to Vocabulary** to use the existing vocabulary form. A failed save leaves a local draft in the browser for recovery; the editor shows an error until you edit and retry.

## Global Search

Click **Search** in the sidebar or press **Ctrl+K** (on macOS, **Cmd+K**). Type at least two characters to search saved Vocabulary terms, definitions, examples and notes; saved YouTube titles, notes and transcript segments; PDF titles, notes and extracted page text; and Notebook names, note titles and Markdown content. Results appear together by source. Use ↑/↓ and Enter to open a result, Esc to close, the clear button to start over, and **Show more results** for the next page. Transcript results open the video at the saved timestamp and mark the segment. PDF page results open the matching page. Vocabulary results open the existing edit view; searching does not change review progress.

Search runs entirely in the local SQLite database. FTS5 is used when available, with a bounded SQLite fallback otherwise. Existing records are indexed on backend startup; database triggers maintain the index as records change. PDF text is extracted once per document with the existing `pypdf` library and stored by page. Scanned image-only pages have no searchable text; OCR is not included. PDF indexing failures leave the original document usable and are retried on the next backend start. After restoring a backup, the search index is checked and rebuilt if needed. No search query or saved content is sent to an external service.

## Video and PDF bookmarks

On a saved video, wait for the player to load, move to the desired moment, and choose **Save Bookmark** in the Bookmarks panel. The dialog captures the player's current time; you can change its suggested title and add an optional note. A small bookmark icon beside each timed transcript segment saves that segment's own timestamp. Click a saved bookmark to seek back to it. If the video cannot play, the existing player displays the playback error.

In the PDF reader, choose **Save Bookmark** in the toolbar to save the current page. Saved PDF bookmarks appear in the side panel, including for scanned PDFs. Click one to return to its page. The central **Bookmarks** page in the sidebar lists video and PDF bookmarks together, with filters, search, open, edit, and delete actions. Deleting a bookmark does not delete its source or other notes; deleting a source removes only its related bookmarks.

Bookmarks are stored in the local SQLite database and included in new ZIP backups automatically. Older LearnTube backups without a bookmark table remain restorable; the table is created during restoration. Bookmark titles and notes also appear in Global Search. Bookmarks do not include PDF text highlights or OCR.

## Study Planner

Open **Study Planner** in the sidebar. The Week view starts on Monday; switch to Day for one date, use the arrows or Today to navigate, and choose **New Plan** to add a timed block or an untimed task. The calendar shows all 24 hours in a scrollable grid and places simultaneous blocks side by side. Click a block or task for its details, completion controls, edit and delete actions, and a link into LearnTube. The chosen Day/Week view is remembered in this browser.

Plans may repeat daily, weekly on the first date's weekday, or on selected weekdays until an optional end date. A repeated occurrence can be completed, skipped, edited, moved, or deleted without changing its siblings. **Edit whole series** changes the base schedule; **Delete whole series** removes its occurrences and overrides. Moving one occurrence to a date already occupied by the same series is rejected, as is a series edit that would create a duplicate on a moved occurrence's date. Overnight blocks are deliberately disallowed: end time must be later on the same local date. Plan dates and wall-clock times remain local across daylight-saving changes; the creating browser's IANA timezone is stored with each series. Switching the computer to another timezone does not shift the stored wall times.

Planned time is the sum of timed block durations, including skipped blocks. Completed plan time includes only blocks you explicitly mark completed. Untimed tasks have no duration. Neither action creates `StudyActivity` records or changes the Dashboard's actual study-time totals. The Dashboard's **Upcoming Study Plan** section shows upcoming timed plans and today's unfinished tasks separately from real activity. Saved plans, recurrence rules, and occurrence changes live in the local SQLite database and are included in new ZIP backups. Older backups without planner tables remain restorable. If a linked video, PDF, or note was deleted, the plan stays visible and opens its related library instead.

Planner requests are limited to 63 local calendar days at once. There is no drag-and-drop; use **Edit** to move a block. A series edit that would hide an existing occurrence override is rejected. No plans are created automatically.

## Focus Timer

Open **Focus Timer** in the sidebar to run a Pomodoro, short break, or long break. The initial durations are 30, 5, and 15 minutes; change them under **Settings**. Start, pause, resume, stop, and reset controls work across LearnTube pages through the small sidebar timer. A completed Pomodoro is recorded once in the local SQLite history. A stopped session or a break does not count as a completed Pomodoro. Normal background-tab throttling does not pause the timer. If computer sleep, a system clock change, or an uncertain page recovery is detected, the timer pauses rather than crediting unverified time; resume it when you return. Keep LearnTube open for the timer and notification sounds. Browser notifications require permission. Only one tab controls an active timer at a time.

The task list shows Study Planner plans for the chosen date. **Add Task** creates an untimed Planner task; editing, completing, or deleting a task updates the same Planner record. Recurring tasks are edited one occurrence at a time here; edit the whole series in Study Planner. You can also open a Planner block and choose **Start Focus Session**. Each task can set its Pomodoro estimate and optional focus or break durations. Changing a duration affects future sessions, not a running session. Completing a Pomodoro does not automatically mark the task complete. The Dashboard shows a separate Focus summary; its existing actual study activity calculation is unchanged. Focus settings, tasks, and session history are included in new local backups, and older backups remain restorable. No sample sessions are created.

Run checks with `cd backend; .\.venv\Scripts\python.exe -m unittest discover -s tests -q` and `cd frontend; npm.cmd run build; node --test tests/*.test.mjs`.

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

## Difficult Words

Open **Vocabulary** to see the Difficult Words section, its counts, the reason for each classification, and the next scheduled review. Choose **Difficult** in the library filter to search or edit only those expressions. **Practice Difficult Words** opens a focused session with the same front and back card content as scheduled review. Space reveals the answer; 1 means Again and 2 means Got It. Again returns the card later in the session, up to two repeats. The summary shows unique words practiced, Got It, and words needing more practice. Leaving a session discards only that session's queue.

Classification uses actual stored scheduled review events. At least two events are required. A word is difficult after two Again ratings in its latest five events, or three Again ratings in its latest ten. After three consecutive Good or Easy ratings following the latest Again, it leaves the category once its latest five events contain no Again. Words with only aggregate counters and no event history remain unclassified until future real scheduled reviews. Extra practice runs entirely in browser memory: it does not submit review ratings, create events, or change intervals, due dates, review counts, or daily due totals. The local SQLite backup includes the original review history; difficulty is derived again after restoration.

Checks: `cd frontend; npm.cmd run build; node --test tests/difficultPractice.test.mjs` and `cd backend; .\.venv\Scripts\python.exe -m unittest discover -s tests -q`.

## Structure

- `frontend/` â€” Vite React application and initial UI.
- `backend/app/` â€” FastAPI app, settings, and SQLModel setup.
- `backend/learntube.db` â€” SQLite database, created automatically at startup.
