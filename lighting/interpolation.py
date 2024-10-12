from datetime import date, datetime, timedelta
from .config import Routine
from typing import Tuple, Optional
from logging import Logger
import logging
from dataclasses import dataclass

from .solar_timestamp import SolarTimestamp

LOG = logging.getLogger(__name__)


@dataclass
class InterpolationPoint:
    """Stores the state name, time, and the logical date (even if time spills into the next day)."""
    state: str
    time: datetime
    date: date

    def __str__(self) -> str:
        return (
            f"{self.state} on solar day {self.date}: {self.time.strftime('%Y-%m-%d %H:%M:%S')})"
        )

def get_interpolation_window(routine: Routine, current_time: datetime, log: Optional[Logger] = LOG) -> Tuple[Optional[InterpolationPoint], Optional[InterpolationPoint]]:
    """
    Find the routine state before and after the current time, along with their respective datetimes and dates.
    If the time is past all routine states today, it will consider the first state of tomorrow as the 'after' state.
    
    Parameters:
    - routine: A Pydantic Routine object containing a routine schedule.
    - current_time: The datetime for which to find the routine states.
    - log: Optional logger for debugging.
    
    Returns:
    - A 2-tuple containing:
        - InterpolationPoint for the "before" state
        - InterpolationPoint for the "after" state
    """

    # Collect all timestamps as SolarTimestamp objects and sort them by datetime
    timestamps: list[Tuple[str, datetime]] = []

    for segment_name in routine.data.keys():
        try:
            # Get SolarTimestamp and normalize to get the exact datetime
            solar_ts = SolarTimestamp.from_str(segment_name, current_time.date(), log=log)
            normalized_time = solar_ts.normalize(log=log)
            timestamps.append((segment_name, normalized_time))
        except ValueError as e:
            log.error(f"Invalid routine segment: {segment_name}. Skipping.")

    # Sort by the normalized datetime
    timestamps.sort(key=lambda x: x[1])

    before_state_info: Optional[InterpolationPoint] = None
    after_state_info: Optional[InterpolationPoint] = None

    for i, (segment_name, segment_time) in enumerate(timestamps):
        if segment_time > current_time:
            # We found the "after" state
            after_state_info = InterpolationPoint(state=segment_name, time=segment_time, date=current_time.date())

            # The "before" state is the previous one if it exists
            if i > 0:
                prev_segment_name, prev_segment_time = timestamps[i - 1]
                before_state_info = InterpolationPoint(state=prev_segment_name, time=prev_segment_time, date=current_time.date())
            break
    else:
        # If no "after" state found, the last state today is the "before" state,
        # and the first state of tomorrow becomes the "after" state.
        if timestamps:
            prev_segment_name, prev_segment_time = timestamps[-1]
            before_state_info = InterpolationPoint(state=prev_segment_name, time=prev_segment_time, date=current_time.date())

            # Handle next day's first state as "after" state
            tomorrow = current_time.date() + timedelta(days=1)
            first_segment_name = timestamps[0][0]
            first_segment_time = SolarTimestamp.from_str(first_segment_name, tomorrow, log=log).normalize(log=log)
            after_state_info = InterpolationPoint(state=first_segment_name, time=first_segment_time, date=tomorrow)

    # Handle the special case of "midnight" spanning into the next day
    if before_state_info and before_state_info.state == "midnight":
        before_state_info.date = before_state_info.time - timedelta(days=1)

    return before_state_info, after_state_info