import logging
from logging import Logger
from typing import Optional, List
from pathlib import Path
from datetime import date, timedelta, datetime
from concurrent.futures import ThreadPoolExecutor
import time

import click
import yaml
from astral.location import LocationInfo
from matplotlib import pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from dirigera import Hub
from dirigera.devices.light import Light

from .solar_times import SolarTimes
from .solar_timestamp import SolarTimestamp
from .config import Config, RoutineData, Zone
from .interpolation import get_interpolation_window

BOLD_SEQ = "\033[1m"
RESET_SEQ = "\033[0m"
LOG = logging.getLogger(__name__)

@click.group()
@click.pass_context
@click.option("--verbose", default=False, type=bool)
@click.option(
    '--config',
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path),
    default="lighting.yaml",
    show_default=True,
    help="Config path override. Default is 'lighting.yaml'."
)
def main(ctx: click.Context, verbose: bool, config: Path):
    logging.basicConfig(format="[%(asctime)s] (%(levelname)s @ %(name)s) " + BOLD_SEQ + "%(message)s" + RESET_SEQ,
                        datefmt="%Y-%m-%d %H:%M:%S")
    log_level = logging.DEBUG if verbose else logging.INFO
    LOG.setLevel(log_level)

    LOG.debug("Reading config file")
    config_yaml = yaml.safe_load(config.read_text())
    config: Config = Config(**config_yaml)

    LOG.debug("Setting SolarTimes city class var")
    SolarTimes.CITY = LocationInfo(
        config.location.name,
        config.location.region,
        config.location.timezone,
        config.location.lat,
        config.location.lon)

    # Make config available to subcommands
    ctx.ensure_object(dict)
    ctx.obj['config'] = config

@main.group()
def solartime():
    """Manage solar times."""
    pass

@solartime.command()
def now():
    """Display the current solar time as a SolarTimestamp."""
    current_solar_time = SolarTimestamp.from_datetime()
    click.echo(f"Current solar time: {str(current_solar_time)}")

@solartime.command()
@click.argument("solar_timestamp", type=str)
def convert(solar_timestamp: str):
    """Convert a solar timestamp string into a datetime."""
    solar_ts = SolarTimestamp.from_str(solar_timestamp)
    normalized_time = solar_ts.normalize()
    click.echo(f"{solar_timestamp} corresponds to datetime: {normalized_time}")

@solartime.command()
def list():
    """List solar segment times for yesterday, today, and tomorrow."""
    days = {
        "Yesterday": date.today() - timedelta(days=1),
        "Today": date.today(),
        "Tomorrow": date.today() + timedelta(days=1),
    }

    for day_name, day in days.items():
        solar_times = SolarTimes.from_cache(day)
        click.echo(f"\n{BOLD_SEQ}{day.isoformat()} ({day_name}){RESET_SEQ}")

        # Justifying output for segment names and times
        max_segment_length = max(len(segment) for segment in SolarTimes.SEGMENT_NAMES)
        for segment_name in SolarTimes.SEGMENT_NAMES:
            segment_time = solar_times.times.get(segment_name)
            if segment_time:
                click.echo(f"  {segment_name.ljust(max_segment_length)} : {segment_time}")

@main.group()
def plot():
    pass

@plot.command
@click.pass_context
def windows(ctx):
    from .config import Routine, RoutineData
    import matplotlib.dates as mdates
    from datetime import datetime, timedelta
    import numpy as np
    import matplotlib.pyplot as plt

    routines = ctx.obj['config'].routines  # Get all routines
    now = datetime.now().replace(tzinfo=SolarTimes.CITY.tzinfo)
    window = timedelta(days=2.5)
    start = now - window / 2
    stop = now + window / 2

    times = np.linspace(start, stop, 1 + int(window / timedelta(minutes=10)))

    # Create subplots based on the number of routines
    fig, axes = plt.subplots(len(routines), 1, figsize=(10, 5 * len(routines)))
    if len(routines) == 1:
        axes = [axes]  # Ensure axes is always a list for consistency

    for idx, routine in enumerate(routines):
        lows = np.zeros_like(times)
        his = np.zeros_like(times)
        
        for i, time in enumerate(times):
            window = get_interpolation_window(routine, time.replace(tzinfo=SolarTimes.CITY.tzinfo))
            lows[i] = window.start.time
            his[i] = window.end.time

        ax = axes[idx]
        myFmt = mdates.DateFormatter('%d/%H:%m', SolarTimes.CITY.tzinfo)
        ax.xaxis.set_major_formatter(myFmt)
        ax.yaxis.set_major_formatter(myFmt)
        ax.set_xlabel("Time")
        ax.set_ylabel("Interpolation Coordinate")

        ax.plot(times, times, label="Realtime", color='black', alpha=0.5)
        ax.plot(times, lows, label="Prev source", color='blue')
        ax.plot(times, his, label="Next source", color='green')

        for day in set([time.date() for time in times]):
            for state in routine.data:
                time = SolarTimestamp.normalize_any(state, day, LOG)
                ax.axvline(time, color='k', linestyle='--', alpha=0.3)

        ax.set_xlim(start, stop)
        ax.set_ylim(start, stop)
        ax.set_title(f"Interpolation Schedule - {routine.name}")
        ax.legend()

    plt.tight_layout()
    plt.show()

@plot.command
@click.argument('routine_name')
@click.pass_context
def interpolant(ctx, routine_name):
    # Retrieve the specific routine by name
    routines = ctx.obj['config'].routines
    routine = next((r for r in routines if r.name == routine_name), None)
    if routine is None:
        click.echo(f"Routine '{routine_name}' not found.")
        return

    now = datetime.now().replace(tzinfo=SolarTimes.CITY.tzinfo)
    window = timedelta(days=2.5)  # Time window
    start = now - window / 2
    stop = now + window / 2

    # Generate timestamps for the window
    times = np.linspace(start, stop, 1 + int(window / timedelta(minutes=10)))

    # Create arrays to hold the interpolated values for each property
    intensities = np.zeros_like(times, dtype=float)
    temps = np.zeros_like(times, dtype=float)
    sats = np.zeros_like(times, dtype=float)
    hues = np.zeros_like(times, dtype=float)

    # Interpolate values for each timestamp using InterpolationWindow.lerp
    for i, time in enumerate(times):
        window = get_interpolation_window(routine, time.replace(tzinfo=SolarTimes.CITY.tzinfo))
        routine_data = window.lerp(time.replace(tzinfo=SolarTimes.CITY.tzinfo))
        intensities[i] = routine_data.intensity
        temps[i] = routine_data.temp
        sats[i] = routine_data.saturation
        hues[i] = routine_data.hue

    # Create a 4x1 plot with shared x-axis for time and different y-axis for each property
    fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)

    # Define x-axis formatter for time
    myFmt = mdates.DateFormatter('%d/%H:%m', SolarTimes.CITY.tzinfo)

    # Plot intensity (0-100%)
    ax = axes[0]
    ax.plot(times, intensities, label="Intensity", color='blue')
    ax.set_ylabel("Intensity (%)")
    ax.xaxis.set_major_formatter(myFmt)
    ax.set_ylim(0, 100)

    # Plot temperature (2202-4000K)
    ax = axes[1]
    ax.plot(times, temps, label="Temperature", color='red')
    ax.set_ylabel("Temperature (K)")
    ax.xaxis.set_major_formatter(myFmt)
    ax.set_ylim(2202, 4000)

    # Plot saturation (0-1)
    ax = axes[2]
    ax.plot(times, sats, label="Saturation", color='green')
    ax.set_ylabel("Saturation")
    ax.xaxis.set_major_formatter(myFmt)
    ax.set_ylim(0, 1)

    # Plot hue (0-360°)
    ax = axes[3]
    ax.plot(times, hues, label="Hue", color='purple')
    ax.set_ylabel("Hue (°)")
    ax.xaxis.set_major_formatter(myFmt)
    ax.set_ylim(0, 360)

    # Set common x-axis label
    axes[-1].set_xlabel("Time")

    # Adjust layout and show the plot
    fig.suptitle(f"Lighting State for Routine '{routine_name}' vs Time")
    plt.tight_layout()
    plt.show()

@main.command()
@click.pass_context
def preview(ctx):
    # from noon-12 to midnight:
    today = date.today()
    times_today = SolarTimes.from_cache(today, LOG).times
    start = times_today["noon"] - timedelta(hours=12)
    end = times_today["midnight"]
    step = timedelta(minutes=15)
    now = start
    hub = ctx.obj['config'].dirigera.get_hub()
    lights = hub.get_lights()

    while now < end:
        apply_lighting(ctx.obj['config'], now, hub, lights)
        print(now)
        now += step

@main.command()
@click.pass_context
def run(ctx):
    while True:
        hub = ctx.obj['config'].dirigera.get_hub()
        lights = hub.get_lights()

        apply_lighting(ctx.obj['config'], datetime.now(tz=SolarTimes.CITY.tzinfo), hub, lights)

        del hub
        time.sleep(60)

def apply_lighting(config: Config, time: datetime, hub: Optional[Hub] = None, lights: Optional[List[Light]] = None):
    if hub is None:
        hub = config.dirigera.get_hub()
    
    if lights is None:
        lights = hub.get_lights()
    
    # Compute what each routine should output
    routines_now = {}
    
    for routine in config.routines:
        window = get_interpolation_window(routine, time, LOG)
        routines_now[routine.name] = window.lerp(time)
    
    # Bin the lights into their respective zones:
    lights_in_zone: dict[Zone, list[Light]] = {}
    thread_count = 0
    
    for zone in config.zones:
        acc = []

        for light in lights:
            if light.attributes.custom_name in zone.devices:
                acc.append(light)
                continue
            
            for ds in light.device_set:
                if ds["name"] in zone.device_sets:
                    acc.append(light)
                    break
        
        thread_count += len(acc)
        lights_in_zone[zone] = acc
    
    with ThreadPoolExecutor(max_workers = thread_count) as executor:
        for zone, lights in lights_in_zone.items():
            state_now = routines_now[zone.routine]
            for light in lights:
                executor.submit(set_light, hub, light, state_now)

def set_light(hub: Hub, light: Light, state: RoutineData):
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
        data.append({"attributes": {"colorTemperature": state.temp}})

    hub.patch(f"/devices/{light.id}", data=data)

if __name__ == "__main__":
    main()
