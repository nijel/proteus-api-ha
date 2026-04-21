"""Constants for the Proteus API integration."""

DOMAIN = "proteus_api"

# API endpoints
API_BASE_URL = "https://proteus.deltagreen.cz/api/trpc/"
API_PRICE_ENDPOINT = "prices.currentDistributionPrices"
API_PRICE_ENDPOINTS = (API_PRICE_ENDPOINT,)
API_STATUS_ENDPOINTS = (
    "inverters.detail",
    "inverters.flexibilityRewardsSummary",
    "inverters.controls.state",
    "commands.current",
    "inverters.currentStep",
)
API_STATUS_ENDPOINT = ",".join(API_STATUS_ENDPOINTS)
API_ENDPOINT = ",".join((*API_STATUS_ENDPOINTS, API_PRICE_ENDPOINT))
API_LIST_ENDPOINT = "inverters.list"
API_CONTROL_ENDPOINT = "inverters.controls.updateManualControl"
API_ENABLED_ENDPOINT = "inverters.controls.updateControlEnabled"
API_MODE_ENDPOINT = "inverters.controls.updateControlMode"
API_FLEXIBILITY_ENDPOINT = "inverters.controls.updateFlexibilityCapabilities"
API_LOGIN_ENDPOINT = "users.loginWithEmailAndPassword"

# Control types
CONTROL_TYPES = [
    "SELLING_INSTEAD_OF_BATTERY_CHARGE",
    "SELLING_FROM_BATTERY",
    "USING_FROM_GRID_INSTEAD_OF_BATTERY",
    "SAVING_TO_BATTERY",
    "BLOCKING_GRID_OVERFLOW",
]

FLEXIBILITY_CAPABILITIES = {
    "UP_POWER": "Dodavka do site",
    "DOWN_BATTERY_POWER": "Odber ze site do baterie",
    "DOWN_SOLAR_CURTAILMENT_POWER": "Zakaz pretoku",
}

DISTRIBUTION_TARIFF_TYPES = {
    "HT": "High tariff",
    "LT": "Low tariff",
}

# States
CONTROL_STATES = ["DISABLED", "ENABLED"]
CONTROL_MODES = ["AUTOMATIC", "MANUAL"]
COMMAND_NONE = "NONE"

UPDATE_INTERVAL = 10
PRICE_UPDATE_INTERVAL = 15 * 60
PRICE_UPDATE_DELAY = 5

TID_DELTA_GREEN = "TID_DELTA_GREEN"


def normalize_email(email: str) -> str:
    """Normalize an email address for use as a config entry unique ID."""
    return email.strip().casefold()


def format_vendor_name(vendor_name: str) -> str:
    """Format vendor name from API format to human-friendly format.

    Converts "VICTRON_ENERGY" to "Victron Energy".
    """
    if not vendor_name:
        return "Unknown"
    # Replace underscores with spaces and convert to title case
    return vendor_name.replace("_", " ").title()
