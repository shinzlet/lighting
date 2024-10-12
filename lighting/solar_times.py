from typing import ClassVar, Optional
from datetime import date, datetime, timedelta
import logging
from logging import Logger
import re

from astral.sun import sun
from astral import LocationInfo

LOG = logging.getLogger(__name__)

class SolarTimes:
    """
    Stores the datetime of various solar events throughout a specified solar day in `SolarTimes.CITY`.
    On a given day, midnight is defined such that it is chronologically after dusk - so midnight on september 1st
    is after dusk on september 1st, NOT before dawn on september 1st.
    """

    # This design is a bit crazy, but city is literally only used here and will always be the same for a program
    # instance unless you're like. unit testing. I did not want to route the city through plumbing and
    # import astral in like ten files just to get it to solartimes
    CITY: ClassVar[Optional[LocationInfo]] = None
    CACHE: ClassVar[dict[date, 'SolarTimes']] = {}
    CACHE_LIMIT: ClassVar[int] = 20
    
    DAWN: ClassVar[str] = "dawn"
    SUNRISE: ClassVar[str] = "sunrise"
    NOON: ClassVar[str] = "noon"
    SUNSET: ClassVar[str] = "sunset"
    DUSK: ClassVar[str] = "dusk"
    MIDNIGHT: ClassVar[str] = "midnight"

    SEGMENT_NAMES: ClassVar[list[str]] = [DAWN, SUNRISE, NOON, SUNSET, DUSK, MIDNIGHT]

    day: date
    times: dict[str, datetime]

    def __init__(self, day: date, log: Logger = LOG):
        if SolarTimes.CITY is None:
            log.critical("The SolarTimes CITY class variable is not set! This must be done by the caller.")
            raise ValueError("SolarTimes.CITY not set!")

        self.day = day

        s = sun(
            observer=SolarTimes.CITY.observer,
            date=day,
            tzinfo=SolarTimes.CITY.tzinfo)
        self.times = s
        self.times[SolarTimes.MIDNIGHT] = self.times[SolarTimes.NOON] + timedelta(days=0.5)

    @classmethod
    def from_cache(cls, day: date, log: Logger = LOG):
        """
        Returns the solar times for a given day, using the cache to avoid
        recomputation where possible.
        """
        ret = cls.CACHE.get(day, None)
        if ret is None:
            ret = cls(day, log)
            cls.CACHE[day] = ret

            if len(cls.CACHE) > cls.CACHE_LIMIT:
                oldest_key = next(iter(cls.CACHE))
                cls.CACHE.pop(oldest_key)

        return ret