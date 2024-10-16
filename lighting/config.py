from typing import List, Dict, Optional
from typing_extensions import Annotated
from pydantic import BaseModel, Field
import dirigera

class Location(BaseModel):
    name: str  # Name of the location (e.g., "San Francisco")
    region: str  # Region of the location (e.g., "America")
    timezone: str  # Timezone string (e.g., "America/Los_Angeles")
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]

class DirigeraData(BaseModel):
    hub_ip: str
    token_file: str

    def get_hub(self) -> dirigera.Hub:
        with open(self.token_file, "r") as token_file:
            token = token_file.read().strip()
        
        return dirigera.Hub(token, self.hub_ip)

class RoutineData(BaseModel):
    temp: Annotated[int, Field(ge=2202, lt=4000)]  # Mandatory
    intensity: Annotated[int, Field(ge=0, le=100)]  # Mandatory
    hue: Optional[Annotated[float, Field(ge=0, le=360)]] = None  # Optional
    saturation: Optional[Annotated[float, Field(ge=0, le=100)]] = None  # Optional

    def __init__(self, **data):
        super().__init__(**data)
        
        if self.hue is None or self.saturation is None:
            rise = (self.temp - 2202) / (4000 - 2202)
            fall = 1 - rise

            # I found these linear relationships of hue, sat as a function of temperature
            # by setting one bulb to a temperature and adjusting another to match via hue and
            # saturation.
            self.hue = fall * 25 + rise * 30
            self.saturation = fall * 1.0 + rise * 0.4

class Routine(BaseModel):
    name: str
    data: Dict[str, RoutineData]  # The key will be like "dawn", "dusk+10%"

class Zone(BaseModel):
    name: str
    routine: str  # This should match a routine's name
    device_sets: List[str]
    devices: List[str]

    def __hash__(self):
        return hash(self.name)


class Config(BaseModel):
    dirigera: DirigeraData
    location: Location
    zones: List[Zone]
    routines: List[Routine]