import os, shutil, glob, subprocess, time
import httpx
from loguru import logger
from .config import settings

def _public_url(mp4):
    """Push reel into the repo → GitHub Pages serves it publicly (replaces R2)."""
    os.makedirs("reels", exist_ok=True)
    rel = f"reels/{os.path.basename(mp4)}"
    shutil.copy(mp4, rel)
    for old in sorted(glob.glob("reels/*.mp4"))[:-5]:   # keep only last 5 reels
        os.remove(old)
    subprocess.run(["git", "add", "-A", "reels"], check=True)
    subprocess.run(["git", "-c", "user.name=reel-agent", "-c", "user.email=agent@bot",
                    "commit", "-m", "daily reel", "--allow-empty"], check=True)
    subprocess.run(["git", "push"], check=True)
    time.sleep(45)                                      # wait for Pages deploy
    return f"https://{settings.gh_user}.github.io/{settings.gh_repo}/{rel}"

def publish(final, caption, hashtags):
    if not (settings.ig_user_id and settings.ig_access_token):
        logger.warning("⏸️ Auto-post skipped (IG_* not set) — reel saved locally")
        return
    url = _public_url(final)
    cap = f"{caption}\n\n" + " ".join("#" + h for h in hashtags)
    h = {"Authorization": f"Bearer {settings.ig_access_token}"}
    r = httpx.post(f"https://graph.facebook.com/v21.0/{settings.ig_user_id}/media",
                   data={"media_type": "REELS", "video_url": url, "caption": cap},
                   headers=h, timeout=180).json()
    r2 = httpx.post(f"https://graph.facebook.com/v21.0/{settings.ig_user_id}/media_publish",
                    data={"creation_id": r["id"]}, headers=h, timeout=60).json()
    logger.success(f"📲 POSTED to Instagram: {r2}")