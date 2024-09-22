import time
from random import randint

import yaml
import dirigera
import numpy as np
from matplotlib import pyplot as plt

HUB_IP = "192.168.86.27"
DIRIGERA_TOKEN_PATH = "dirigera_token"

# import illumipy
# WEATHER_API_KEY_PATH = "weather_api_key"
# with open(WEATHER_API_KEY_PATH, "r") as weather_api_key_file:
#     weather_api_key = weather_api_key_file.read().strip()
# brightness = [illumipy.data.light_data(
    #     time, "2024-09-21", "San Francisco", "USA", weather_api_key, 0
    # )['illuminance'] for time in times]

def brightness_at(time_s) -> float:
    time_h = time_s / 3600
    return np.sin(np.pi / 12 * (time_h - 7)) * 0.5 + 0.5

def main():
    with open(DIRIGERA_TOKEN_PATH, "r") as token_file:
        token = token_file.read().strip()
    
    hub = dirigera.Hub(token, HUB_IP)

    top_light = next(light for light in hub.get_lights() if light.attributes.custom_name == "Top Lamp")
    
    start_time = time.time()
    animation_duration = 10
    min_interval = 1
    writes = 0
    seconds_per_day = 60 * 60 * 24
    while True:
        writes += 1
        then = time.time()
        progress = min(1, (then - start_time) / animation_duration)
        seconds_into_day = seconds_per_day * progress
        brightness = brightness_at(seconds_into_day)
        top_light.set_light_level(max(1, int(100 * brightness)))
        elapsed = time.time() - then
        compensation = min_interval - elapsed
        if compensation > 0:
            time.sleep(compensation)
        
        if then - start_time > animation_duration:
            print(f"Finished animation in f{then - start_time:.2f} seconds")
            break
    
    wps = writes / animation_duration
    print(f"Writes per second: {wps:.1f}")
        

    # try:
    #     while True:
    #         for light in active_lights:
    #             light.set_light_level(randint(1, 100))
    #             print(light)
    #             sleep(0.3)
    #         # sleep(1)
    # except KeyboardInterrupt:
    #     for light in active_lights:
    #         light.set_light_level(1)

    
    # print([light for light in hub.get_lights()])

if __name__ == "__main__":
    main()