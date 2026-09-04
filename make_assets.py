import os
import subprocess
import imageio_ffmpeg
from PIL import Image

def main():
    os.makedirs("assets", exist_ok=True)
    print("[+] 'assets' directory ready.")

    terrain_jpg = os.path.join("assets", "terrain.jpg")
    terrain_png = os.path.join("assets", "terrain.png")

    if os.path.exists(terrain_png) and not os.path.exists(terrain_jpg):
        img = Image.open(terrain_png).convert("RGB")
        img.save(terrain_jpg, "JPEG", quality=95)
        print(f"[+] Converted {terrain_png} -> {terrain_jpg}")
    elif os.path.exists(terrain_jpg):
        print(f"[+] {terrain_jpg} exists ({os.path.getsize(terrain_jpg)} bytes).")
    else:
        print("[!] No terrain map found.")

    music_mp3 = os.path.join("assets", "music.mp3")
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "sine=frequency=110:duration=240",
        "-f", "lavfi", "-i", "sine=frequency=164.8:duration=240",
        "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.4,afade=t=in:d=4,afade=t=out:st=234:d=6",
        "-q:a", "9", music_mp3
    ]
    
    print("[*] Generating ambient music bed...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"[+] Generated {music_mp3} ({os.path.getsize(music_mp3)} bytes).")
    else:
        print("[-] FFmpeg error:", res.stderr)

if __name__ == "__main__":
    main()
