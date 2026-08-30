import sys
from agent.graph import build
from loguru import logger

if __name__ == "__main__":
    logger.info("🚀 Autonomous News Agent starting — fetching TODAY's live news…")
    
    try:
        # Run the LangGraph pipeline
        result = build().invoke({})
        
        # Safely check if the final video was generated
        if result.get("final"):
            logger.success(f"✅ Done! Final reel saved at: {result['final']}")
            
            # Optional: Print the format it chose today
            fmt = result.get("reel_format", "unknown")
            logger.info(f"📺 Today's format: {fmt.upper()}")
        else:
            logger.warning("⚠️ Agent finished, but no final video was generated. Check logs above.")
            
    except KeyboardInterrupt:
        logger.warning("🛑 Agent stopped by user.")
        sys.exit(0)
        
    except Exception as e:
        # Catch any unexpected crashes so GitHub Actions knows it failed
        logger.error(f"❌ Agent crashed: {e}")
        sys.exit(1)