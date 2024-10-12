import logging
from logging import Logger
from typing import Optional
from pathlib import Path
from datetime import date, timedelta, datetime

import click
import yaml
from astral.location import LocationInfo

from .solar_times import SolarTimes
from .solar_timestamp import SolarTimestamp
from .config import Config
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

@main.command
@click.pass_context
def test(ctx):
    routine = ctx.obj['config'].routines[0]
    for i in get_interpolation_window(routine, datetime.now().replace(tzinfo=SolarTimes.CITY.tzinfo)):
        print(i)

if __name__ == "__main__":
    main()
