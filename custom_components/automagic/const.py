"""Constants for the AutoMagic integration."""

DOMAIN = "automagic"
CONF_API_KEY = "api_key"
CONF_DEFAULT_SERVICE_ID = "default_service_id"
CONF_ENDPOINT_URL = "endpoint_url"
CONF_MODEL = "model"
CONF_MAX_TOKENS = "max_tokens"
CONF_PROVIDER = "provider"
CONF_REQUEST_TIMEOUT = "request_timeout"
CONF_SERVICE_ID = "service_id"
CONF_SERVICES = "services"
CONF_TEMPERATURE = "temperature"
CONF_CONTEXT_LIMIT = "context_limit"

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_REQUEST_TIMEOUT = 900
DEFAULT_TEMPERATURE = 0.15
OPENAI_ENDPOINT = "https://api.openai.com"
PROVIDER_CUSTOM = "custom"
PROVIDER_OPENAI = "openai"
# 0 = send all entities (no artificial cap)
DEFAULT_CONTEXT_LIMIT = 0

API_PATH_GENERATE = "/api/automagic/generate"
API_PATH_GENERATE_STATUS = "/api/automagic/generate/{job_id}"
API_PATH_INSTALL = "/api/automagic/install"
API_PATH_INSTALL_REPAIR = "/api/automagic/install_repair"
API_PATH_ENTITIES = "/api/automagic/entities"
API_PATH_HISTORY = "/api/automagic/history"
API_PATH_HISTORY_ENTRY = "/api/automagic/history/{entry_id}"
API_PATH_SERVICES = "/api/automagic/services"

HA_MIN_VERSION = (2024, 10)

PRIORITY_DOMAINS = [
    "light",
    "switch",
    "sensor",
    "binary_sensor",
    "climate",
    "media_player",
    "cover",
    "lock",
    "alarm_control_panel",
    "person",
    "device_tracker",
    "fan",
    "vacuum",
    "camera",
    "weather",
    "automation",
    "notify",
    "script",
    "scene",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "timer",
    "counter",
    "number",
    "select",
    "button",
    "text",
    "date",
    "time",
    "datetime",
]

# Preferred models in quality order for auto-detection
PREFERRED_MODEL_ORDER = [
    "qwen2.5:14b",
    "qwen2.5:7b",
    "mistral-nemo",
    "qwen2.5:3b",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4",
    "gpt-3.5-turbo",
    "llama3.1",
    "llama3",
    "codellama",
    "deepseek-coder",
    "mixtral",
    "gemma2",
    "phi3",
    "command-r",
]

# Per-model-family optimal temperature (lower = more deterministic YAML)
MODEL_TEMPERATURE_MAP: dict[str, float] = {
    "qwen2.5": 0.15,
    "mistral-nemo": 0.2,
    "mistral": 0.2,
    "mixtral": 0.2,
    "gpt-4o": 0.1,
    "gpt-4o-mini": 0.1,
    "gpt-4": 0.1,
    "gpt-3.5": 0.15,
    "llama3": 0.2,
    "llama3.1": 0.2,
    "codellama": 0.1,
    "deepseek": 0.1,
    "gemma2": 0.2,
    "phi3": 0.2,
    "command-r": 0.2,
}

# Per-model-family max_tokens defaults
MODEL_MAX_TOKENS_MAP: dict[str, int] = {
    "gpt-4o": 4096,
    "gpt-4o-mini": 4096,
    "gpt-4": 4096,
    "gpt-3.5": 4096,
}
DEFAULT_LOCAL_MAX_TOKENS = 4096
