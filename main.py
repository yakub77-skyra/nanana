from agent.graph import build
from loguru import logger

if __name__ == "__main__":
    logger.info("🚀 Phase 1 agent starting — fetching TODAY's live news…")
    result = build().invoke({})
    logger.success(f"Done. Open {result['final']}")