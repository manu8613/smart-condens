"""Constants for Smart Condens."""

from __future__ import annotations

DOMAIN = "smart_condens"
STORAGE_VERSION = 1
DASHBOARD_URL = "smart-condens"

CONF_OUTDOOR = "outdoor_sensor"
CONF_FLOW = "flow_sensor"
CONF_RETURN = "return_sensor"
CONF_BURNER_HEATING = "burner_heating"
CONF_BURNER_DHW = "burner_dhw"
CONF_STARTS = "starts_last_hour"
CONF_GAS = "gas_sensor"
CONF_PRICE = "gas_price"
CONF_CHANGE_DATE = "change_date"
CONF_GD_BASE = "degree_day_base"
CONF_DHW_BASE = "dhw_kwh_day"
CONF_W_ELEMENT = "watts_per_element"
CONF_DASHBOARD = "create_dashboard"
CONF_ALLOW_WRITE = "allow_boiler_write"
CONF_MQTT_TOPIC = "ebusd_topic"
CONF_CIRCUIT = "ebusd_circuit"

SUBENTRY_ROOM = "room"
CONF_NAME = "name"
CONF_TEMP = "temperature_sensor"
CONF_CLIMATE = "climate"
CONF_DEMAND = "demand_entity"
CONF_ELEMENTS = "elements"
CONF_ORDER = "loop_order"

DEFAULT_GD_BASE = 18.0
DEFAULT_W_ELEMENT = 120.0
DEFAULT_FLOW_SET = 60.0
