import sys
from loguru import logger
from agent.graph import build

BUILD = "P8.0-reference"

if __name__ == "__main__":
    logger.info(f"🧬 BUILD {BUILD} — Autonomous News Agent starting…")
    try:
        from agent import nodes
        nodes._doctor({})
        result = build().invoke({})
        final = result.get("final")
        fmt = result.get("reel_format", "unknown")
        if final:
            logger.success(f"✅ Done! Final reel: {final}")
            logger.info(f"📺 Format: {fmt.upper()} | 🧬 BUILD {BUILD}")
        else:
            logger.warning(f"⚠️ Agent finished without final video")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("🛑 Stopped by user.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Agent crashed: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)