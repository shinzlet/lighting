from typing import ClassVar, Optional
from datetime import date, datetime, timedelta
import logging
from logging import Logger
import re

from .solar_times import SolarTimes

LOG = logging.getLogger(__name__)


class SolarTimestamp:
    # (segment name)(whitespace*)(+ or -)(whitespace*)(1 to 3 digits)(percent sign)
    FORMAT: ClassVar[re.Pattern] = re.compile(rf"""
        ^                    # Start of the line
        ({'|'.join(map(re.escape, SolarTimes.SEGMENT_NAMES))})  # Match any of the segment names
        (?:                  # Begin optional group for +10% part
            \s*              # Any amount of whitespace
            \+               # Plus sign
            \s*              # Any amount of whitespace
            ([1-9][0-9]?)    # An integer from 1 to 99, no leading zeros (captured in group 2)
            \s*%?            # Optional percentage sign and any surrounding whitespace
        )?                   # End of optional group, making this whole section optional
        $                    # End of the line
        """, re.VERBOSE)

    def __init__(self, day: date, segment: str, offset: float):
        self.day = day
        self.segment = segment
        self.offset = offset
    
    @staticmethod
    def from_str(text: str, day: Optional[date] = None, log: Logger = LOG) -> 'SolarTimestamp':
        day = day or date.today() # python evaluates the default arg at import time :(
        match: Optional[re.Match] = SolarTimestamp.FORMAT.match(text)

        if match is None:
            raise ValueError(f"Failed to construct solar timestamp from string {repr(text)}")
        
        if match.group(2) is None:
            offset = 0
        else:
            offset = int(match.group(2))

        return SolarTimestamp(day, segment=match.group(1), offset=offset)
    
    def normalize(self, log: Logger = LOG) -> datetime:
        st_today = SolarTimes.from_cache(self.day, log)

        # If there is no offset, we don't have to interpolate at all:
        if self.offset == 0:
            return st_today.times[self.segment]
        
        window_start = st_today.times[self.segment]
        
        # Otherwise, we need to find the start and end time for our interpolation
        # window:
        if self.offset > 0 and self.segment == SolarTimes.MIDNIGHT:
            # Special case: midnight + x% requires knowing when dawn is tomorrow.
            tomorrow = self.day + timedelta(days=1)
            st_tomorrow = SolarTimes.from_cache(tomorrow, log)
            window_end = st_tomorrow.times[SolarTimes.DAWN]
        else:
            segment_index = SolarTimes.SEGMENT_NAMES.index(self.segment)
            next_segment_name = SolarTimes.SEGMENT_NAMES[segment_index + 1]
            window_end = st_today.times[next_segment_name]
        
        # Now we interpolate between these times:
        window_duration = window_end - window_start
        offset_duration = (self.offset / 100) * window_duration
        return window_start + offset_duration
    
    @classmethod
    def from_datetime(cls, dt: Optional[datetime] = None, log: Logger = LOG) -> 'SolarTimestamp':
        """
        Constructs a SolarTimestamp from a given datetime. If no datetime is provided,
        it defaults to the current time.
        """
        dt = dt or datetime.now()  # If no datetime is provided, use the current time
        st_today = SolarTimes.from_cache(dt.date(), log)

        # Determine which segment this datetime is closest to
        for i, segment_name in enumerate(SolarTimes.SEGMENT_NAMES):
            segment_time = st_today.times[segment_name]
            
            dt = dt.replace(tzinfo=SolarTimes.CITY.tzinfo)
            if dt < segment_time:
                previous_segment_name = SolarTimes.SEGMENT_NAMES[i - 1]
                previous_segment_time = st_today.times[previous_segment_name]
                
                # Find where the time falls between the previous and current segment
                window_duration = segment_time - previous_segment_time
                elapsed_duration = dt - previous_segment_time
                
                # Calculate the percentage offset
                offset = (elapsed_duration.total_seconds() / window_duration.total_seconds()) * 100
                
                # Return a SolarTimestamp for the previous segment with the calculated offset
                return cls(dt.date(), previous_segment_name, offset)
        
        # Special case for "midnight" segment (as it technically spans into the next day)
        tomorrow = dt.date() + timedelta(days=1)
        st_tomorrow = SolarTimes.from_cache(tomorrow, log)
        midnight_time = st_today.times[SolarTimes.MIDNIGHT]
        dawn_time = st_tomorrow.times[SolarTimes.DAWN]
        
        if midnight_time <= dt < dawn_time:
            window_duration = dawn_time - midnight_time
            elapsed_duration = dt - midnight_time
            offset = (elapsed_duration.total_seconds() / window_duration.total_seconds()) * 100
            return cls(dt.date(), SolarTimes.MIDNIGHT, offset)

        # If the datetime is exactly equal to a segment's time, return a SolarTimestamp with no offset
        return cls(dt.date(), SolarTimes.MIDNIGHT, 0)

    def __str__(self) -> str:
        """
        Returns a string representation of the SolarTimestamp in the format:
        'midnight + 10%' or 'dawn'.
        """
        if self.offset == 0:
            return f"{self.segment}"
        else:
            return f"{self.segment} + {self.offset:.0f}%"