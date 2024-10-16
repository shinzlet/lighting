from datetime import date, datetime, timedelta
from .config import Routine, RoutineData
from typing import Tuple, Optional, ClassVar
from logging import Logger
import logging
from dataclasses import dataclass

from .solar_timestamp import SolarTimestamp
from .solar_times import SolarTimes

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

@dataclass
class InterpolationWindow:
    routine: Routine
    start: InterpolationPoint
    end: InterpolationPoint

    def duration(self) -> timedelta:
        return self.end.time - self.start.time

    def lerp(self, time: datetime) -> RoutineData:
        start_data = self.routine.data[self.start.state]
        if time <= self.start.time:
            return start_data
        
        end_data = self.routine.data[self.end.state]
        if time >= self.end.time:
            return end_data
        
        rise = (time - self.start.time) / self.duration()
        fall = 1 - rise
        
        # To interpolate between two routine data objects, we interpolate temp and intensity
        # and saturation naively, and then interpolate hue along the shortest path:
        temp = start_data.temp * fall + end_data.temp * rise
        intensity = start_data.intensity * fall + end_data.intensity * rise
        saturation = start_data.saturation * fall + end_data.saturation * rise
        hue = interpolate_hue(start_data.hue, end_data.hue, rise)

        return RoutineData(
            temp=int(temp),
            intensity=int(intensity),
            saturation=saturation,
            hue=hue
        )
        
def interpolate_hue(a: float, b: float, t: float) -> float:
    # Ensure the hues are within the [0, 360) range
    a = a % 360
    b = b % 360
    
    # Compute the difference and choose the shortest path
    delta = (b - a) % 360
    if delta > 180:
        delta -= 360
    
    # Interpolate and return the result, ensuring the result is also within [0, 360)
    return (a + t * delta) % 360


# Sorted list of (state_name_str, datetime)
NormalizedRoutine = list[Tuple[str, datetime]]
    
class RoutineCache:
    """
    It is probably overkill to cache routines, as the solar times used in their calculations are already cached...
    However it is very low hanging fruit and it feels wasteful to normalize each timepoint for each routine thousands
    of times per day when you only have to do it once :c
    """
    # {routine_name: {date_of_interest: normalized_routine_for_date, ...}, ...}
    CACHES: ClassVar[dict[str, dict[date, NormalizedRoutine]]] = {}
    # We limit the number of days per routine, not the number of routines
    CACHE_DAY_LIMIT: ClassVar[int] = 20

    @classmethod
    def from_cache(cls, routine: Routine, day: date, log: Logger = LOG):
        if routine.name not in cls.CACHES:
            cls.CACHES[routine.name] = {}

        cache = cls.CACHES[routine.name]
        ret = cache.get(day, None)

        if ret is None:
            ret = get_normalized_routine(routine, day)
            cache[day] = ret

            if len(cache) > cls.CACHE_DAY_LIMIT:
                oldest_key = next(iter(cache))
                cache.pop(oldest_key)

        return ret

def get_normalized_routine(routine: Routine, day: date, log: Optional[Logger] = LOG) -> NormalizedRoutine:
    # Normalize each timestamp in today's routine and sort them
    timestamps: NormalizedRoutine = []

    for segment_name in routine.data.keys():
        solar_ts = SolarTimestamp.from_str(segment_name, day, log=log)
        normalized_time = solar_ts.normalize(log=log)
        timestamps.append((segment_name, normalized_time))

    timestamps.sort(key=lambda x: x[1])

    return timestamps

def get_interpolation_window(
        routine: Routine,
        current_time: datetime,
        log: Optional[Logger] = LOG
    ) -> Tuple[InterpolationPoint, InterpolationPoint]:
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

    # Note: this code is pretty complicated - I am really not sure if that's because it's inherently a very
    # weird peicewise analysis, or if i have missed something cleaner...

    timestamps = RoutineCache.from_cache(routine, current_time.date(), log)

    # Identify the previous and next state:
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
            else:
                # If there is no previous state today, the previous state is the *last* state
                # from yesterday.
                yesterday = current_time.date() - timedelta(days=1)
                last_segment_name = SolarTimes.SEGMENT_NAMES[-1]
                last_segment_time = SolarTimestamp.from_str(last_segment_name, yesterday, log=log).normalize(log)
                before_state_info = InterpolationPoint(state=last_segment_name, time=last_segment_time, date=yesterday)
            break
    else:
        # If no "after" state found, the last state today is the "before" state,
        # and the first state of tomorrow becomes the "after" state.
        prev_segment_name, prev_segment_time = timestamps[-1]
        before_state_info = InterpolationPoint(state=prev_segment_name, time=prev_segment_time, date=current_time.date())

        # Handle next day's first state as "after" state
        tomorrow = current_time.date() + timedelta(days=1)
        first_segment_name = SolarTimes.SEGMENT_NAMES[0]
        first_segment_time = SolarTimestamp.from_str(first_segment_name, tomorrow, log=log).normalize(log)
        after_state_info = InterpolationPoint(state=first_segment_name, time=first_segment_time, date=tomorrow)

    # Handle the special case of "midnight" spanning into the next day
    if before_state_info and before_state_info.state == "midnight":
        before_state_info.date = before_state_info.time - timedelta(days=1)

    return before_state_info, after_state_info

def get_interpolation_window(
        routine: Routine,
        current_time: datetime,
        log: Optional[Logger] = LOG
    ) -> InterpolationWindow:

    today = current_time.date()
    one_day = timedelta(days=1)
    yesterday_routine = RoutineCache.from_cache(routine, today - one_day, log)
    today_routine = RoutineCache.from_cache(routine, today, log)
    tomorrow_routine = RoutineCache.from_cache(routine, today + one_day, log)

    # This is overkill - with clever execution, we could only require the previous and 
    # next individual timestamp from yesterday and tomorrow. But i'm tired of this project lol
    timestamps = [
        *yesterday_routine,
        *today_routine,
        *tomorrow_routine
    ]

    for i, (segment_name, segment_time) in enumerate(timestamps):
        # The list is sorted, so this is first true when state i-1 < now < state i
        if segment_time > current_time:
            before_date = current_time.date()
            after_date = current_time.date()

            if i == 0:
                # If the before state is timestamp 0, it is the one we borrowed from yesterday
                before_date -= one_day
            
            if i == len(timestamps) - 1:
                # If the after state is the last timestamp, it is the one we borrowed from tomorrow
                after_date += one_day
                
            after_state_info = InterpolationPoint(state=segment_name, time=segment_time, date=current_time.date())

            prev_segment_name, prev_segment_time = timestamps[i - 1]
            before_state_info = InterpolationPoint(state=prev_segment_name, time=prev_segment_time, date=current_time.date())

            return InterpolationWindow(routine, before_state_info, after_state_info)