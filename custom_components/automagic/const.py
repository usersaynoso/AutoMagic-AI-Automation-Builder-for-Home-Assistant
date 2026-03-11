"""Constants for the AutoMagic integration."""

DOMAIN = "automagic"
CONF_ENDPOINT_URL = "endpoint_url"
CONF_MODEL = "model"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_CONTEXT_LIMIT = "context_limit"

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2
DEFAULT_CONTEXT_LIMIT = 40

API_PATH_GENERATE = "/api/automagic/generate"
API_PATH_INSTALL = "/api/automagic/install"
API_PATH_ENTITIES = "/api/automagic/entities"

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
]
