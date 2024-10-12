from typing import List, Dict
from pydantic import BaseModel, conint, confloat, Field

class Location(BaseModel):
    name: str  # Name of the location (e.g., "San Francisco")
    region: str  # Region of the location (e.g., "America")
    timezone: str  # Timezone string (e.g., "America/Los_Angeles")
    lat: confloat(ge=-90, le=90)  # type: ignore
    lon: confloat(ge=-180, le=180)  # type: ignore

class RoutineData(BaseModel):
    temp: conint(ge=0)  # type: ignore
    intensity: conint(ge=0, le=100)  # type: ignore
    hue: conint(ge=0, le=360)  # type: ignore
    saturation: conint(ge=0, le=100)  # type: ignore

class Routine(BaseModel):
    name: str
    data: Dict[str, RoutineData]  # The key will be like "dawn", "dusk+10%"

class Zone(BaseModel):
    name: str
    routine: str  # This should match a routine's name
    device_sets: List[str]
    devices: List[str]

class Config(BaseModel):
    location: Location
    zones: List[Zone]
    routines: List[Routine]