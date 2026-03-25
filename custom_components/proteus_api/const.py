"""Constants for the Proteus API integration."""

DOMAIN = "proteus_api"

# API endpoints
API_BASE_URL = "https://proteus.deltagreen.cz/api/trpc/"
API_ENDPOINT = "inverters.detail,inverters.flexibilityRewardsSummary,inverters.controls.state,commands.current,inverters.currentStep,prices.currentDistributionPrices"
API_LIST_ENDPOINT = "inverters.list"
API_CONTROL_ENDPOINT = "inverters.controls.updateManualControl"
API_ENABLED_ENDPOINT = "inverters.controls.updateControlEnabled"
API_MODE_ENDPOINT = "inverters.controls.updateControlMode"
API_FLEXIBILITY_ENDPOINT = "inverters.controls.updateFlexibilityCapabilities"
API_LOGIN_ENDPOINT = "users.loginWithEmailAndPassword"

# Control types
CONTROL_TYPES = {
    "SELLING_INSTEAD_OF_BATTERY_CHARGE": "Prodej do sítě místo nabíjení",
    "SELLING_FROM_BATTERY": "Prodej z baterie do sítě",
    "USING_FROM_GRID_INSTEAD_OF_BATTERY": "Šetření energie v baterii",
    "SAVING_TO_BATTERY": "Nabíjení baterie ze sítě",
    "BLOCKING_GRID_OVERFLOW": "Zákaz přetoků",
}

FLEXIBILITY_CAPABILITIES = {
    "UP_POWER": "Dodavka do site",
    "DOWN_BATTERY_POWER": "Odber ze site do baterie",
    "DOWN_SOLAR_CURTAILMENT_POWER": "Zakaz pretoku",
}

FLEXIBILITY_CAPABILITY_LOCALIZED_NAMES = {
    "en": {
        "UP_POWER": "Export to grid",
        "DOWN_BATTERY_POWER": "Charge battery from grid",
        "DOWN_SOLAR_CURTAILMENT_POWER": "Block grid export",
    },
    "cs": {
        "UP_POWER": "Dodávka do sítě",
        "DOWN_BATTERY_POWER": "Odběr ze sítě do baterie",
        "DOWN_SOLAR_CURTAILMENT_POWER": "Zákaz přetoků",
    },
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
