import logging
from logging import Logger
from typing import Optional
from pathlib import Path

import click
import yaml
from astral.location import LocationInfo

from .solar_times import SolarTimes
from .solar_timestamp import SolarTimestamp
from .config import Config

BOLD_SEQ = "\033[1m"
RESET_SEQ = "\033[0m"
LOG = logging.getLogger(__name__)

@click.group(invoke_without_command=True)
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

    if ctx.invoked_subcommand is None:
        pass

@click.command()
@click.argument("solar-timestamp", type=str, required=False)
def solartime(solar_timestamp: Optional[str]):
    if solar_timestamp is None:
        print(SolarTimestamp.from_datetime())
    else:
        print(f"{solar_timestamp} will occur at {SolarTimestamp.from_str(solar_timestamp).normalize()}.")

main.add_command(solartime, "solartime")