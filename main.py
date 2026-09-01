import sys
from loguru import logger

from agent.version import BUILD
from agent.graph import build

if __name__ == "__main__":
    logger.info(f"🧬 BUILD {BUILD} — Autonomous News Agent starting…")

    try:
        result = build().invoke({})

        final = result.get("final")
        fmt = result.get("reel_format", "unknown")

        if final:
            logger.success(f"✅ Done! Final reel: {final}")
            logger.info(f"📺 Format: {fmt.upper()} | 🧬 BUILD {BUILD}")
        else:
            logger.warning(f"⚠️ Agent finished without a final video (BUILD {BUILD}). Check logs above.")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("🛑 Stopped by user.")
        sys.exit(0)

    except Exception as e:
        # Non-zero exit → GitHub Actions shows ❌ so we KNOW it failed
        logger.error(f"❌ Agent crashed (BUILD {BUILD}): {type(e).__name__}: {e}")
        sys.exit(1)