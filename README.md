# Funny Cartoon Shorts Auto Publisher (Drive → Gemini → YouTube)

A ready-to-configure automation starter for **already-made cartoon Shorts**. It checks a Google Drive folder three times daily, processes one not-yet-uploaded video per run, asks Gemini to create English metadata from three sample video frames, makes a title thumbnail from a frame, uploads to YouTube, and records the Drive file ID to reduce duplicates.

## What is automated
- Google Drive folder scan (oldest unprocessed video first)
- Downloads one ready video per run
- Extracts up to three frames and asks Gemini for English title, description, hashtags and short thumbnail text
- Creates a 1280×720 JPG thumbnail using a frame + title text
- Uploads video through YouTube Data API
- Attempts to set the custom thumbnail (YouTube may reject it or show it differently for Shorts)
- Saves an upload ledger so successfully recorded videos are skipped next time
- Scheduled workflow: 08:30, 16:30, and 00:30 India time (one video per run, three per day)

## Important limitations — read first
- This does **not** download from Pinterest or scrape random websites. Use your own Drive bundle and only videos/music you have rights to publish.
- Gemini sees sample frames, not every moment or the audio. Its metadata may need review; AI can misunderstand a clip.
- A generated thumbnail is attempted, but YouTube Shorts thumbnail selection/display and API permissions can vary.
- GitHub Actions is scheduled cloud automation, **not** an always-on server. Schedules may be delayed and free usage has limits.
- A new/unverified YouTube API project may be restricted to private uploads. Test with `VIDEO_PRIVACY=private` first; public upload may require YouTube API project verification/audit.
- YouTube API upload quota, Gemini quotas, Google OAuth testing-mode token expiry, and GitHub usage limits apply. No unlimited-free guarantee.
- The ledger cannot eliminate every duplicate edge case (for example, if YouTube accepts a video and the runner fails before saving the ledger). Check YouTube Studio during initial testing.

## A. Create Google Drive folder
1. Create a folder in Google Drive, for example `Funny Cartoon Bundle`.
2. Upload your finished vertical cartoon Shorts (`.mp4`, `.mov`, `.m4v`, `.webm`).
3. Open the folder. Its URL looks like `https://drive.google.com/drive/folders/FOLDER_ID`. Copy only `FOLDER_ID`.

## B. Create Google APIs / OAuth credentials
Do this carefully in the Google account that owns the Drive folder and YouTube channel.
1. Open https://console.cloud.google.com/ and create/select a project.
2. In APIs & Services → Library, enable **Google Drive API** and **YouTube Data API v3**.
3. Configure OAuth consent screen / Google Auth Platform. If the app is in Testing mode, add your own Google account as a test user.
4. Create an OAuth Client ID of type **Desktop app**, download the JSON and save it as `credentials.json` on your Android device (for example in Download).
5. Create a Gemini API key at https://aistudio.google.com/apikey . Keep it private.

## C. Create `token.json` on Android with Termux
This step is required only once unless Google authorization expires. Install Termux from its official F-Droid/GitHub source, then run:

```bash
termux-setup-storage
pkg update -y
pkg install python git unzip -y
python -m pip install --upgrade pip
```

Extract this project ZIP into a folder such as `~/funny-cartoon-auto`, then:

```bash
cd ~/funny-cartoon-auto
python -m pip install -r requirements.txt
cp /storage/emulated/0/Download/credentials.json ./credentials.json
python auth_setup.py
```

The script prints a Google authorization URL. Open it in your phone browser, choose the correct account, approve Drive read and YouTube upload permissions, then paste the authorization code back into Termux. It creates `token.json`.

If Google blocks this because the OAuth app is in Testing mode, ensure your account is listed as a test user. If Google says the app is unverified, proceed only if you trust your own Cloud project and the scopes shown are the ones requested. Never give these files to another person.

## D. Convert credentials/token JSON to Base64 on Android
From the project directory in Termux:

```bash
base64 -w 0 credentials.json
base64 -w 0 token.json
```

Copy each entire output separately. These strings are secrets. Do **not** paste them into ChatGPT, GitHub Issues, public files, or messages. If `-w 0` is unsupported, use `base64 credentials.json | tr -d '\n'` and likewise for `token.json`.

## E. Create a PRIVATE GitHub repository and upload files
1. On https://github.com/ create a **Private** repository, e.g. `funny-cartoon-auto`.
2. Upload the contents of this ZIP (including `.github/workflows/publish.yml`, `main.py`, `requirements.txt`, `state/uploaded.json`, `auth_setup.py`, `README.md`, `.gitignore`). GitHub's web uploader may hide dot-folders; if `.github/workflows/publish.yml` is missing, scheduled Actions will not run. Confirm the workflow appears in the repository's Actions tab.
3. Never upload `credentials.json` or `token.json` into the repository. `.gitignore` excludes them, but verify they are absent from the GitHub file list.

## F. Add GitHub Actions secrets
Repository → Settings → Secrets and variables → Actions → **New repository secret**. Create:
- `GOOGLE_OAUTH_CLIENT_JSON_B64` = entire Base64 output from `credentials.json`
- `GOOGLE_TOKEN_JSON_B64` = entire Base64 output from `token.json`
- `GEMINI_API_KEY` = your Gemini API key

Then Settings → Secrets and variables → Actions → **Variables** → New repository variable:
- `DRIVE_FOLDER_ID` = copied Google Drive folder ID
- `GEMINI_MODEL` = `gemini-2.5-flash` (change if that model is unavailable to your key)
- `VIDEO_PRIVACY` = `private` for the first test. After confirming API permissions and behavior, set `public` if your project is allowed to publish publicly.

## G. Test before enabling public uploads
1. Put one test video in the Drive folder.
2. GitHub repository → Actions → `Funny Cartoon Shorts Auto Publisher` → Run workflow.
3. Open the run logs and check for errors. Check YouTube Studio; the first test should be private.
4. If successful, add more videos. Scheduled runs will attempt one video at each of the three daily times.
5. Only change `VIDEO_PRIVACY` to `public` after verifying the channel/API project can publish public videos.

## Troubleshooting
- **No videos found:** check folder ID, that videos are directly inside the folder (not only in a nested subfolder), file extensions, and that the authorized Google account can access it.
- **401/invalid_grant:** redo `auth_setup.py`, then update `GOOGLE_TOKEN_JSON_B64` with the new `token.json` Base64.
- **403 from YouTube upload:** check YouTube Data API v3 is enabled, OAuth account/channel, API quota and project verification restrictions.
- **Gemini 404/model not found:** choose a model currently available to your API key in Google AI Studio and update `GEMINI_MODEL`.
- **Thumbnail error:** upload may still have succeeded. Shorts thumbnail behavior/API eligibility varies; see the run logs and YouTube Studio.
- **No automatic run:** check that `.github/workflows/publish.yml` exists in the repo and Actions are enabled. GitHub scheduled workflows can be delayed.

## Privacy and safety
Keep the repository private. Never publish OAuth secrets, API keys, `credentials.json`, or `token.json`. Upload only content you own or are licensed to use. This software does not guarantee monetization or freedom from claims.
