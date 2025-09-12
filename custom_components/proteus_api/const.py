"""Constants for the Proteus API integration."""

DOMAIN = "proteus_api"

# API endpoints
API_BASE_URL = "https://proteus.deltagreen.cz/api/trpc/"
API_ENDPOINT = "inverters.detail,inverters.flexibilityRewardsSummary,inverters.controls.state,commands.current,inverters.currentStep"
API_CONTROL_ENDPOINT = "inverters.controls.updateManualControl"
API_ENABLED_ENDPOINT = "inverters.controls.updateControlEnabled"
API_MODE_ENDPOINT = "inverters.controls.updateControlMode"
API_FLEXIBILITY_ENDPOINT = "inverters.controls.updateFlexibilityMode"
API_LOGIN_ENDPOINT = "users.loginWithEmailAndPassword"

# Control types
CONTROL_TYPES = {
    "SELLING_INSTEAD_OF_BATTERY_CHARGE": "Prodej do sítě místo nabíjení",
    "SELLING_FROM_BATTERY": "Prodej z baterie do sítě",
    "USING_FROM_GRID_INSTEAD_OF_BATTERY": "Šetření energie v baterii",
    "SAVING_TO_BATTERY": "Nabíjení baterie ze sítě",
    "BLOCKING_GRID_OVERFLOW": "Zákaz přetoků",
}

# States
CONTROL_STATES = ["DISABLED", "ENABLED"]
CONTROL_MODES = ["AUTOMATIC", "MANUAL"]
