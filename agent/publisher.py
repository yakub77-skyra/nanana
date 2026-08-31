import os, shutil, glob, subprocess, time
import httpx
from loguru import logger
from .config import settings

Z = "https://zernio.com/api/v1"

def _public_url(mp4):
    """GitHub Pages = public video URL (Zernio downloads it from here)."""
    os.makedirs("reels", exist_ok=True)
    rel = f"reels/{os.path.basename(mp4)}"
    shutil.copy(mp4, rel)
    for old in sorted(glob.glob("reels/*.mp4"))[:-5]:
        os.remove(old)
    subprocess.run(["git", "add", "-A", "reels"], check=True)
    subprocess.run(["git", "add", "history.json", "analytics.json"], capture_output=True)
    subprocess.run(["git", "-c", "user.name=reel-agent", "-c", "user.email=agent@bot",
                    "commit", "-m", "daily reel", "--allow-empty"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)

    time.sleep(45)
    return f"https://{settings.gh_user}.github.io/{settings.gh_repo}/{rel}"

def publish(final, caption, hashtags):
    if not (settings.zernio_api_key and settings.zernio_account_id):
        logger.warning("⏸️ Auto-post skipped — set ZERNIO_API_KEY + ZERNIO_ACCOUNT_ID")
        return
    url = _public_url(final)
    cap = f"{caption}\n\n" + " ".join("#" + h for h in hashtags)
    r = httpx.post(f"{Z}/posts",
                   headers={"Authorization": f"Bearer {settings.zernio_api_key}"},
                   json={"content": cap,
                         "mediaItems": [{"type": "video", "url": url}],
                         "platforms": [{"platform": "instagram",
                                        "accountId": settings.zernio_account_id,
                                        "platformSpecificData": {"shareToFeed": True}}],
                         "publishNow": True},
                   timeout=180).json()
    logger.success(f"📲 POSTED via Zernio: {r.get('post', {}).get('_id', r)}")