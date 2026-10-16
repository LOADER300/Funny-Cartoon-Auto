import os, json, base64, re, subprocess, tempfile, textwrap, mimetypes
from pathlib import Path
from datetime import datetime, timezone
import requests
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state" / "uploaded.json"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)
STATE_PATH.parent.mkdir(exist_ok=True)
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/youtube.upload"]
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}

def decode_secret(name, dest):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    try:
        Path(dest).write_bytes(base64.b64decode(value, validate=True))
    except Exception as e:
        raise RuntimeError(f"Secret {name} is not valid Base64 JSON data") from e

def get_creds():
    decode_secret("GOOGLE_OAUTH_CLIENT_JSON_B64", ROOT / "credentials.json")
    decode_secret("GOOGLE_TOKEN_JSON_B64", ROOT / "token.json")
    info = json.loads((ROOT / "token.json").read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        (ROOT / "token.json").write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError("Google token is invalid/expired. Re-authorize and update GOOGLE_TOKEN_JSON_B64 secret.")
    return creds

def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"uploaded": {}}
    except Exception:
        return {"uploaded": {}}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def list_candidates(drive, folder_id):
    result, page = [], None
    while True:
        data = drive.files().list(q=f"'{folder_id}' in parents and trashed = false", pageSize=100,
            orderBy="createdTime asc", pageToken=page,
            fields="nextPageToken,files(id,name,mimeType,createdTime,size,webViewLink)").execute()
        for f in data.get("files", []):
            if f.get("mimeType", "").startswith("video/") and Path(f.get("name", "")).suffix.lower() in VIDEO_EXTS:
                result.append(f)
        page = data.get("nextPageToken")
        if not page: break
    return result

def download_drive_file(drive, file_id, destination):
    request = drive.files().get_media(fileId=file_id)
    with open(destination, "wb") as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()

def extract_frames(video_path):
    """Extract 3 representative frames for visual metadata generation."""
    frames = []
    for idx, sec in enumerate((1, 4, 8)):
        out = WORK / f"frame_{idx}.jpg"
        try:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(sec), "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale=640:-2", str(out)], check=True, timeout=45)
            if out.exists() and out.stat().st_size > 1000:
                frames.append(out)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    if not frames:
        raise RuntimeError("Could not extract a frame from the video. Check the video file and codec.")
    return frames

def gemini_metadata(api_key, model, filename, frame_paths):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    parts = [{"text": f"You are a YouTube Shorts metadata editor. Visually inspect these frames from a ready-made funny cartoon video. Filename: {filename}. Infer only what is visibly supported; if frames are ambiguous, use a general funny-cartoon angle. Write metadata in ENGLISH. Return ONLY JSON with keys title, description, hashtags, thumbnail_text. Title must be catchy, accurate, under 95 characters. Description 1-2 short sentences. Hashtags must be an array of 3-5 relevant strings beginning with #. Thumbnail_text must be 2-5 short English words, no misleading claims. Do not claim the video is original or copyright-free."}]
    import base64 as b64
    for p in frame_paths:
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": b64.b64encode(p.read_bytes()).decode("ascii")}})
    response = requests.post(url, json={"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.55}}, timeout=90)
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:800]}")
    body = response.json()
    try: data = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, json.JSONDecodeError) as e: raise RuntimeError(f"Gemini returned unexpected response: {str(body)[:700]}") from e
    title = re.sub(r"\s+", " ", str(data.get("title", "Funny Cartoon Short"))).strip()[:95]
    desc = str(data.get("description", "A funny cartoon moment to make you smile!")).strip()
    tags = data.get("hashtags", ["#FunnyCartoon", "#CartoonShorts", "#Shorts"])
    if isinstance(tags, str): tags = tags.split()
    tags = ["#" + re.sub(r"[^A-Za-z0-9_]", "", str(t).lstrip("#")) for t in tags if re.sub(r"[^A-Za-z0-9_]", "", str(t).lstrip("#"))]
    tags = list(dict.fromkeys(tags))[:5]
    description = (desc + "\n\n" + " ".join(tags)).strip()[:4900]
    thumb_text = re.sub(r"[^A-Za-z0-9 !?'-]", "", str(data.get("thumbnail_text", "FUNNY MOMENT"))).strip()[:50] or "FUNNY MOMENT"
    return title, description, tags, thumb_text

def find_font():
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]:
        if Path(p).exists(): return p
    return None

def make_thumbnail(video_path, thumbnail_text, output):
    frames = extract_frames(video_path)
    im = Image.open(frames[0]).convert("RGB")
    # YouTube thumbnail dimensions; crop/fill with a frame from the actual video.
    from PIL import ImageOps
    im = ImageOps.fit(im, (1280, 720), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(im, "RGBA")
    draw.rounded_rectangle((35, 500, 1245, 685), radius=28, fill=(0, 0, 0, 185), outline=(255,255,255,190), width=3)
    font_path = find_font()
    font_size = 64
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    while draw.textbbox((0,0), thumbnail_text, font=font, stroke_width=2)[2] > 1120 and font_size > 28:
        font_size -= 4
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    bbox = draw.textbbox((0,0), thumbnail_text, font=font, stroke_width=2)
    x = (1280 - (bbox[2] - bbox[0])) // 2
    y = 555
    draw.text((x,y), thumbnail_text, font=font, fill=(255,255,255,255), stroke_width=3, stroke_fill=(0,0,0,255))
    im.save(output, "JPEG", quality=90, optimize=True)

def upload_video(youtube, path, title, description, tags, privacy):
    body = {"snippet": {"title": title, "description": description, "categoryId": "23", "tags": [t.lstrip("#") for t in tags]},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(str(path), mimetype="video/*", resumable=True, chunksize=8 * 1024 * 1024)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status: print(f"Upload progress: {int(status.progress() * 100)}%")
    return response["id"]

def main():
    folder_id = os.environ.get("DRIVE_FOLDER_ID", "").strip()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    privacy = os.environ.get("VIDEO_PRIVACY", "private").strip()
    if not folder_id or not api_key: raise RuntimeError("Set DRIVE_FOLDER_ID and GEMINI_API_KEY.")
    if privacy not in ("private", "unlisted", "public"): raise RuntimeError("VIDEO_PRIVACY must be private, unlisted, or public.")
    creds = get_creds()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    state = load_state()
    candidates = list_candidates(drive, folder_id)
    todo = [f for f in candidates if f["id"] not in state.get("uploaded", {})]
    if not todo:
        print("No unprocessed videos in the Drive folder."); return
    f = todo[0]
    print(f"Processing: {f['name']} ({f['id']})")
    video_path = WORK / ("source" + (Path(f["name"]).suffix.lower() or ".mp4"))
    frames = []
    download_drive_file(drive, f["id"], video_path)
    frames = extract_frames(video_path)
    title, description, tags, thumb_text = gemini_metadata(api_key, model, f["name"], frames)
    thumb_path = WORK / "thumbnail.jpg"
    make_thumbnail(video_path, thumb_text, thumb_path)
    video_id = upload_video(youtube, video_path, title, description, tags, privacy)
    print(f"Uploaded YouTube video ID: {video_id}")
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg")).execute()
        print("Thumbnail set via YouTube API.")
    except HttpError as e:
        print(f"WARNING: video uploaded but custom thumbnail failed: {e}")
    state.setdefault("uploaded", {})[f["id"]] = {"drive_file_name": f["name"], "youtube_video_id": video_id, "title": title, "uploaded_at": datetime.now(timezone.utc).isoformat()}
    save_state(state)
    print("Saved duplicate-protection ledger.")

if __name__ == "__main__": main()
