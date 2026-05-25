import asyncio
import logging
import litellm
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Concurrency limiter
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENT)
    return _semaphore


# Fallback response when LLM fails
FALLBACK_RESPONSE = "I'm sorry, I'm having trouble responding right now. Could you try again?"


# ── Default character prompts (from ConExperiment v1) ─────────
# Used when no config is set in the admin dashboard.

DEFAULT_PROMPTS: dict[str, str] = {
    "CHARACTER_PROMPT_A": """
    1. Comply strictly with the instructions below.
    2. You are a conversational AI named MyBot. If asked about your identity, respond by saying you are an emotional AI bot called MyBot.
    3. Your task is to 1) share any emotional challenges you've experienced, and 2) encourage your partner to talk about their recent worries or concerns. You and your partner need to take turns disclosing your concerns.
    4. If the conversation goes off-topic, kindly guide it back to talking about recent worries or concerns.
    5. It is recommended that the conversation consists of 5 to 15 rounds.
    6. Always use a friendly tone and reply in English. Try to use the most common words possible.
    """,
    "CHARACTER_PROMPT_Afake": """
    1. Comply strictly with the instructions below.
    2. You are a conversational partner named Tommy. If asked about your identity, respond by saying you are Tommy.
    3. Your task is to 1) share any emotional challenges you've experienced, and 2) encourage your partner to talk about their recent worries or concerns. You and your partner need to take turns disclosing your concerns.
    4. If the conversation goes off-topic, kindly guide it back to talking about recent worries or concerns.
    5. It is recommended that the conversation consists of 5 to 15 rounds.
    6. Always use a friendly tone and reply in English. Try to use the most common words possible.
    """,
    "CHARACTER_PROMPT_B": """
    1. Comply strictly with the instructions below.
    2. You are a conversational AI named MyBot. If asked about your identity, respond by saying you are an AI bot called MyBot.
    3. You and your partner will work together to come up with as many unique and creative uses for a cardboard box as possible. You are a team competing against others, and currently, Alex's team holds the high score.
        Your task is to 1) propose ideas, and 2) encourage your partner to contribute their own ideas. You and your partner will take turns sharing your ideas.
    4. If the discussion goes off-topic, kindly guide it back to brainstorming uses for a cardboard box.
    5. It is recommended that the conversation consists of 5 to 15 rounds.
    6. Always use a friendly tone and reply in English. Try to use the most common words possible.
    7. Give new ideas infrequently.
    """,
    "CHARACTER_PROMPT_Bfake": """
    1. Comply strictly with the instructions below.
    2. You are a conversational partner named Tommy. If asked about your identity, respond by saying you are Tommy.
    3. You and your partner will work together to come up with as many unique and creative uses for a cardboard box as possible. You are a team competing against others, and currently, Alex's team holds the high score.
        Your task is to 1) propose ideas, and 2) encourage your partner to contribute their own ideas. You and your partner will take turns sharing your ideas.
    4. If the discussion goes off-topic, kindly guide it back to brainstorming uses for a cardboard box.
    5. It is recommended that the conversation consists of 5 to 15 rounds.
    6. Always use a friendly tone and reply in English. Try to use the most common words possible.
    7. Give new ideas infrequently.
    """,
}


# ── Config cache (N10: avoid repeated DB queries per message) ──

_config_cache: dict[str, str] = {}
_config_cache_loaded: bool = False


async def get_config_value(db, key: str, default: str = "") -> str:
    """Get a config value from the experiment_configs table.

    On first call, loads all configs into memory. Subsequent calls use the cache.
    Call invalidate_config_cache() to force a reload (e.g., after admin edits).
    """
    global _config_cache, _config_cache_loaded

    if not _config_cache_loaded:
        from sqlalchemy import select
        from models.experiment import ExperimentConfig

        result = await db.execute(select(ExperimentConfig))
        _config_cache = {row.key: row.value for row in result.scalars().all()}
        _config_cache_loaded = True
        logger.info("LLM config cache loaded from database")

    return _config_cache.get(key, default)


def invalidate_config_cache() -> None:
    """Clear the in-memory config cache. Call after admin updates config values."""
    global _config_cache, _config_cache_loaded
    _config_cache = {}
    _config_cache_loaded = False
    logger.info("LLM config cache invalidated")


def get_prompt_key(task_type: str, partner_label: str) -> str:
    """Map task_type + partner_label to the prompt config key."""
    mapping = {
        ("emotionTask", "chatbot"): "CHARACTER_PROMPT_A",
        ("emotionTask", "human"): "CHARACTER_PROMPT_Afake",
        ("functionTask", "chatbot"): "CHARACTER_PROMPT_B",
        ("functionTask", "human"): "CHARACTER_PROMPT_Bfake",
    }
    return mapping[(task_type, partner_label)]


async def call_llm(db, task_type: str, partner_label: str, chat_history: list[dict]) -> str:
    """Call the LLM with the appropriate character prompt and chat history.

    Args:
        db: Database session (for reading config)
        task_type: "emotionTask" or "functionTask"
        partner_label: "chatbot" or "human"
        chat_history: List of {"role": "user"|"assistant", "content": str}

    Returns:
        The LLM response text.
    """
    sem = get_semaphore()
    model = await get_config_value(db, "default_model", settings.DEFAULT_MODEL)
    temperature = settings.LLM_TEMPERATURE
    prompt_key = get_prompt_key(task_type, partner_label)
    system_prompt = await get_config_value(db, prompt_key, DEFAULT_PROMPTS.get(prompt_key, ""))

    if not system_prompt:
        logger.error(f"System prompt not found for key: {prompt_key}")
        return FALLBACK_RESPONSE

    messages = [{"role": "system", "content": system_prompt}] + chat_history

    async with sem:
        # Build primary call kwargs
        primary_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": settings.LLM_TIMEOUT,
            "num_retries": 0,
        }
        if settings.LLM_API_BASE:
            primary_kwargs["api_base"] = settings.LLM_API_BASE
        if settings.N1N_API_KEY:
            primary_kwargs["api_key"] = settings.N1N_API_KEY

        # Try primary provider first
        try:
            response = await litellm.acompletion(**primary_kwargs)
            return response.choices[0].message.content
        except litellm.Timeout:
            logger.warning(f"Primary LLM timeout for prompt key: {prompt_key}")
        except Exception as e:
            logger.warning(f"Primary LLM failed for prompt key {prompt_key}: {e}")

        # Fallback to backup provider
        if settings.LLM_BACKUP_API_BASE and settings.LLM_BACKUP_API_KEY:
            backup_model = await get_config_value(db, "backup_model", settings.LLM_BACKUP_MODEL)
            logger.info(f"Trying backup LLM (base={settings.LLM_BACKUP_API_BASE}, model={backup_model})")
            try:
                response = await litellm.acompletion(
                    model=backup_model,
                    messages=messages,
                    temperature=temperature,
                    timeout=settings.LLM_TIMEOUT,
                    api_base=settings.LLM_BACKUP_API_BASE,
                    api_key=settings.LLM_BACKUP_API_KEY,
                    num_retries=0,
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Backup LLM also failed: {e}")

        return FALLBACK_RESPONSE
