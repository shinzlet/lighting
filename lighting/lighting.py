import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

import dirigera.devices
import dirigera.devices.light
import yaml
import dirigera
from dirigera.devices.light import Light
from dirigera.hub.hub import Hub
import numpy as np
from matplotlib import pyplot as plt
import astral
from astral.sun import sun

# from .hue_util import k_to_hue_and_saturation

HUB_IP = "192.168.86.27"
DIRIGERA_TOKEN_PATH = "dirigera_token"

LIVING_ROOM_LAMP = "Top Lamp"
BEDROOM_LAMP = "Ceiling Lamp"
BATHROOM_LAMP = "Vanity"
ALL_NAMES = (LIVING_ROOM_LAMP, BEDROOM_LAMP, BATHROOM_LAMP)

SEGMENT_NAMES = ["start", "dawn", "sunrise", "noon", "sunset", "dusk", "end"]

def get_light_by_name(lights: list[Light], name: str) -> Optional[Light]:
    return next((l for l in lights if l.attributes.custom_name == name), None)

def get_device_set_by_name(lights: list[Light], name: str) -> list[Light]:
    return [l for l in lights if any(ds["name"] == name for ds in l.device_set)]

def get_hub() -> dirigera.Hub:
    with open(DIRIGERA_TOKEN_PATH, "r") as token_file:
        token = token_file.read().strip()
    
    return dirigera.Hub(token, HUB_IP)

def solar_times(city: astral.LocationInfo, date: date) -> dict[str, datetime]:
    """
    Returns named boundaries for each solar time segment. The start of this solar
    day is defined as 12 hours before noon on this day. the end of this solar day
    is defined as the start of the next solar day. this means that the solar times
    of one day and the next day will form a continuous, non-overlapping partition of
    time.
    """
    s = sun(city.observer, date, tzinfo=city.tzinfo)
    s_tomorrow = sun(city.observer, date + timedelta(days=1), tzinfo=city.tzinfo)
    half_day = timedelta(hours=12)
    s["start"] = s["noon"] - half_day
    s["end"] = s_tomorrow["noon"] + half_day
    return s

def k_to_hue_and_saturation(temp: float) -> Tuple[float, float]:
    temp = min(max(temp, 2202), 4000)
    rise = (temp - 2202) / (4000 - 2202)
    fall = 1 - rise

    # I found these linear relationships of hue, sat as a function of temperature
    # by setting one bulb to a temperature and adjusting another to match via hue and
    # saturation.
    hue = fall * 25 + rise * 30
    sat = fall * 1.0 + rise * 0.4

    return (hue, sat)

class ZoneState:
    def __init__(self, intensity: float = 50, temp: float = 2700, hue: Optional[float] = None, saturation: Optional[float] = None):
        self.intensity: float = intensity
        self.temp: float = temp

        if hue is None or saturation is None:
            self.hue, self.saturation = k_to_hue_and_saturation(temp)
        else:
            self.hue = hue
            self.saturation = saturation
    
    @staticmethod
    def _interpolate_hue(hue1: float, hue2: float, weight: float) -> float:
        # Ensure hues are within 0-360 degrees
        hue1 = hue1 % 360
        hue2 = hue2 % 360
        
        # Calculate the shortest path for hue interpolation
        delta = hue2 - hue1
        if abs(delta) > 180:
            if delta > 0:
                delta -= 360
            else:
                delta += 360
        
        interpolated_hue = (hue1 + weight * delta) % 360
        return interpolated_hue

    @staticmethod
    def weighted_average(zone1: 'ZoneState', zone2: 'ZoneState', weight: float) -> 'ZoneState':
        # Ensure weight is between 0 and 1
        weight = max(0, min(1, weight))
        
        # Weighted average for intensity and temp
        intensity_avg = (1 - weight) * zone1.intensity + weight * zone2.intensity
        temp_avg = (1 - weight) * zone1.temp + weight * zone2.temp
        saturation_avg = (1 - weight) * zone1.saturation + weight * zone2.saturation
        
        # Interpolate hue along the shortest path
        hue_avg = ZoneState._interpolate_hue(zone1.hue, zone2.hue, weight)
        
        # Return the new ZoneState with the computed weighted values
        return ZoneState(intensity=intensity_avg, temp=temp_avg, hue=hue_avg, saturation=saturation_avg)

class Zone:
    def __init__(self, name: str, routine: dict[float, ZoneState], device_sets: list[str] = [], devices: list[str] = []):
        self.name: str = name
        self.device_sets: list[str] = device_sets
        self.devices: list[str] = devices
        self.routine = routine
    
def load_zones(conf: dict) -> list[Zone]:
    zones: list[Zone] = []
    for zone in conf["zones"]:
        routine = {}
        for normalized_time, zone_state in zone["routine"].items():
            routine[normalized_time] = ZoneState(
                intensity=zone_state["intensity"],
                temp=zone_state.get("temp", 2700),
                hue=zone_state.get("hue"),
                saturation=zone_state.get("saturation")
            )
        
        zones.append(
            Zone(
                name=zone["name"],
                routine=routine,
                device_sets=zone.get("device_sets", []),
                devices=zone.get("devices", [])
            )
        )
    
    return zones

def get_lights_in_zone(lights: list[Light], zone: Zone):
    return [light for light in lights 
            if any(ds["name"] in zone.device_sets for ds in light.device_set)
            or light.attributes.custom_name in zone.devices]

def set_light(hub: Hub, light: Light, state: ZoneState):
    if state.intensity == 0:
        light.set_light(False)
        return

    data = [
        {"attributes": {"isOn": True}},
        {"attributes": {"lightLevel": int(state.intensity)}},
    ]

    if "colorHue" in light.capabilities.can_receive and "colorSaturation" in light.capabilities.can_receive:
        data.append({"attributes": {"colorHue": state.hue, "colorSaturation": state.saturation}})
    else:
        data.append({"attributes": {"colorTemperature": int(state.temp)}})

    hub.patch(f"/devices/{light.id}", data=data)

def invert_normalized_time(normalized_time: float, today_sun: dict[str, datetime]):
    segment = int(normalized_time)
    rise = normalized_time - segment
    segment_dt = today_sun[SEGMENT_NAMES[segment]]
    window = today_sun[SEGMENT_NAMES[segment + 1]] - segment_dt
    return segment_dt + window * rise

def light_zone(hub: Hub, lights: list[Light], zone: Zone, normalized_time: float, today_sun: dict[str, datetime], city):
    lights_in_zone = get_lights_in_zone(lights, zone)

    # Find the ZoneState and datetime of the immediate next and previous zone states
    state_times: list[float] = sorted(zone.routine.keys())
    now = invert_normalized_time(normalized_time, today_sun)

    # Find the first zone state in the routine that comes after the current normalized time.

    # First, if we have gone through every routine state today, we know the next routine
    # state is tomorrow.
    if normalized_time >= state_times[-1]:
        print("Next routine state is tomorrow")
        next_state = zone.routine[state_times[0]] # The next state is the first one tomorrow
        tomorrow_sun = solar_times(city, today_sun["noon"].date()+timedelta(hours=24))
        next_state_datetime = invert_normalized_time(state_times[0], tomorrow_sun)
        prev_state = zone.routine[state_times[-1]]
        prev_state_datetime = invert_normalized_time(state_times[-1], today_sun)
    elif normalized_time < state_times[0]:
        print("It is before today's first state")
        # it's also possible that we are currently between yesterday's last state and today's
        # first state
        next_state = zone.routine[state_times[0]]
        next_state_datetime = invert_normalized_time(state_times[0], today_sun)
        prev_state = zone.routine[state_times[-1]] # The previous state is yesterday's last
        yesterday_sun = solar_times(city, today_sun["noon"].date()-timedelta(hours=24))
        prev_state_datetime = invert_normalized_time(state_times[-1], yesterday_sun)
    else:
        print("Between two segments on same day")
        # Otherwise, we can find the state (today) which is happening next:
        for state_index, state_time in enumerate(state_times):
            if state_time > normalized_time:
                break
        
        # Here, we know for sure that the next state and previous state are today
        next_state = zone.routine[state_times[state_index]]
        next_state_datetime = invert_normalized_time(state_times[state_index], today_sun)
        prev_state = zone.routine[state_times[state_index - 1]]
        prev_state_datetime = invert_normalized_time(state_times[state_index - 1], today_sun)
    
    window = next_state_datetime - prev_state_datetime
    rise = (now - prev_state_datetime) / window

    state = ZoneState.weighted_average(prev_state, next_state, rise)

    with ThreadPoolExecutor(max_workers = len(lights_in_zone)) as executor:
        for light in lights_in_zone:
            executor.submit(set_light, hub, light, state)
    print(f"updating {len(lights_in_zone)} lights")
    print(vars(state))
    print()


def main2():
    with open("lighting.yaml", "r") as config:
        conf = yaml.safe_load(config)
        loc = conf["location"]
        lat = loc["lat"]
        lon = loc["lon"]

        default = conf.get("default", {})
        default_temp = default.get("temp", 2700)
        default_hue = default.get("hue", None)

        if default_hue is None:
            default_hue = k_to_hue(default_temp)
        
        zones = load_zones(conf)
    
    hub = get_hub()
    lights = hub.get_lights()
    update_duration: timedelta = timedelta(seconds=10)
    city = astral.LocationInfo("San Francisco", "America", "America/Los_Angeles", lat, lon)
    # one_day = timedelta.days(1)

    today_sun = solar_times(city, datetime.now().date())

    while True:
        start_dt = datetime.now(tz=city.tzinfo)

        if start_dt > today_sun["end"]:
            today_sun = solar_times(city, start_dt.date())
        
        for segment_index in range(len(SEGMENT_NAMES) - 1):
            window_start: datetime = today_sun[SEGMENT_NAMES[segment_index]]
            window_end: datetime = today_sun[SEGMENT_NAMES[segment_index + 1]]

            if window_start < start_dt < window_end:
                break
        
        # segment_index is now correct - note that even if `break` isn't hit above,
        # the preconditions we use to check that we today_sun is correct means that
        # the segment index is always right, and, as we will use next, segment_index
        # is always strictly less than len(SEGMENT_NAMES) - 1

        # Now we compute the distance into our current segment:
        window_start: datetime = today_sun[SEGMENT_NAMES[segment_index]]
        window_end: datetime = today_sun[SEGMENT_NAMES[segment_index + 1]]
        window_duration_s: float = (window_end - window_start).total_seconds()
        rise: float = (start_dt - window_start).total_seconds() / window_duration_s

        # Now that we know the segment index and the `rise` fraction, we can figure out
        # which part of the routine we're in.
        normalized_time = segment_index + rise

        print(normalized_time)

        for zone in zones:
            light_zone(hub, lights, zone, normalized_time, today_sun, city)


        elapsed = datetime.now(tz=city.tzinfo) - start_dt
        wait_duration_s = max(0, (update_duration - elapsed).total_seconds())
        time.sleep(wait_duration_s)

if __name__ == "__main__":
    main2()