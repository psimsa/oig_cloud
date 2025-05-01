"""Data models for OIG Cloud integration."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, cast


@dataclass
class AcInData:
    """Model for AC input data."""
    
    aci_vr: float
    aci_vs: float
    aci_vt: float
    aci_wr: float
    aci_ws: float
    aci_wt: float
    aci_f: float
    ac_ad: Optional[float] = None
    ac_am: Optional[float] = None
    ac_ay: Optional[float] = None
    ac_pd: Optional[float] = None
    ac_pm: Optional[float] = None
    ac_py: Optional[float] = None
    
    @property
    def total_load(self) -> float:
        """Calculate total grid load across all phases."""
        return self.aci_wr + self.aci_ws + self.aci_wt


@dataclass
class AcInBData:
    """Model for secondary AC input data."""
    
    aci_wr: float = 0
    aci_ws: float = 0
    aci_wt: float = 0
    
    @property
    def total_load(self) -> float:
        """Calculate total grid load across all phases."""
        return self.aci_wr + self.aci_ws + self.aci_wt


@dataclass
class AcOutData:
    """Model for AC output data."""
    
    aco_p: float
    aco_pr: Optional[float] = None
    aco_ps: Optional[float] = None
    aco_pt: Optional[float] = None
    aco_vr: Optional[float] = None
    aco_vs: Optional[float] = None
    aco_vt: Optional[float] = None
    en_day: Optional[float] = None


@dataclass
class BatteryData:
    """Model for battery data."""
    
    bat_i: Optional[float] = None
    bat_v: Optional[float] = None
    bat_t: Optional[float] = None
    bat_q: Optional[float] = None
    bat_c: Optional[float] = None
    bat_and: Optional[float] = None
    bat_apd: Optional[float] = None
    bat_am: Optional[float] = None
    bat_ay: Optional[float] = None
    
    @property
    def power(self) -> Optional[float]:
        """Calculate battery power."""
        if self.bat_i is not None and self.bat_v is not None:
            return self.bat_i * self.bat_v
        return None


@dataclass
class BatteryParams:
    """Model for battery parameters."""
    
    bat_min: float
    bat_gl_min: float
    bat_hdo: int
    bal_on: int
    hdo1_s: int
    hdo1_e: int
    hdo2_s: int
    hdo2_e: int


@dataclass
class BoilerData:
    """Model for boiler data."""
    
    p: Optional[float] = None
    ssr1: Optional[int] = None
    ssr2: Optional[int] = None
    ssr3: Optional[int] = None


@dataclass
class BoilerParams:
    """Model for boiler parameters."""
    
    ison: int = 0
    prrty: int = 0
    p_set: float = 0
    p_set2: Optional[float] = None
    p_set3: Optional[float] = None
    zone1_s: int = 0
    zone1_e: int = 0
    zone2_s: int = 0
    zone2_e: int = 0
    zone3_s: int = 0
    zone3_e: int = 0
    zone4_s: int = 0
    zone4_e: int = 0
    hdo: int = 0
    termostat: int = 0
    manual: int = 0
    wd: int = 50000
    ssr0: int = 1
    ssr1: int = 1
    ssr2: int = 1
    id_subd: int = 0
    stht: int = 0
    offset: int = 100
    offset2: int = 0
    offset3: int = 0
    tset: float = 0
    tset2: float = 0


@dataclass
class BoxData:
    """Model for box environment data."""
    
    temp: float
    humid: float


@dataclass
class BoxParams:
    """Model for box parameters."""
    
    bat_ac: int
    p_fve: float
    p_bat: float
    mode: int
    mode1: int
    crct: int
    crcte: int
    sw: Optional[str] = None


@dataclass
class BoxParams2:
    """Model for secondary box parameters."""
    
    app: int = 0
    wdogx: int = 0


@dataclass
class DcInData:
    """Model for DC input (solar) data."""
    
    fv_proc: float = 0
    fv_p1: float = 0
    fv_p2: float = 0
    fv_i1: Optional[float] = None
    fv_i2: Optional[float] = None
    fv_v1: Optional[float] = None
    fv_v2: Optional[float] = None
    fv_ad: Optional[float] = None
    fv_am: Optional[float] = None
    fv_ay: Optional[float] = None
    
    @property
    def total_power(self) -> float:
        """Calculate total solar power."""
        return self.fv_p1 + self.fv_p2


@dataclass
class DeviceData:
    """Model for device metadata."""
    
    id_type: int
    lastcall: str


@dataclass
class InvertorParams:
    """Model for invertor parameters."""
    
    to_grid: int


@dataclass
class InvertorParams1:
    """Model for secondary invertor parameters."""
    
    p_max_feed_grid: int


@dataclass
class ActualData:
    """Model for actual/current data."""
    
    aci_wr: float
    aci_ws: float
    aci_wt: float
    aco_p: float
    fv_p1: float
    fv_p2: float
    bat_p: float
    bat_c: float
    viz: int
    
    @property
    def grid_total(self) -> float:
        """Calculate total grid power."""
        return self.aci_wr + self.aci_ws + self.aci_wt
        
    @property
    def solar_total(self) -> float:
        """Calculate total solar power."""
        return self.fv_p1 + self.fv_p2


@dataclass
class OigCloudDeviceData:
    """Model for a single OIG Cloud device."""
    
    ac_in: AcInData
    ac_out: AcOutData
    actual: ActualData
    batt: BatteryData
    dc_in: DcInData
    box_prms: BoxParams
    invertor_prms: InvertorParams
    invertor_prm1: InvertorParams1
    queen: bool = False
    device: Optional[DeviceData] = None
    boiler: Optional[BoilerData] = None
    boiler_prms: Optional[BoilerParams] = None
    batt_prms: Optional[BatteryParams] = None
    box: Optional[BoxData] = None
    box_prm2: Optional[BoxParams2] = None
    ac_in_b: Optional[AcInBData] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OigCloudDeviceData':
        """Create a device data instance from a dictionary."""
        # Required fields
        ac_in = AcInData(**data.get("ac_in", {}))
        ac_out = AcOutData(**data.get("ac_out", {}))
        actual = ActualData(**data.get("actual", {}))
        batt_data = data.get("batt", {})
        # Handle the case where bat_c might be the only field in batt
        if len(batt_data) == 1 and "bat_c" in batt_data:
            batt = BatteryData(
                bat_c=batt_data["bat_c"],
                bat_i=0,
                bat_v=0
            )
        else:
            batt = BatteryData(**batt_data)
        dc_in = DcInData(**data.get("dc_in", {}))
        box_prms = BoxParams(**data.get("box_prms", {}))
        invertor_prms = InvertorParams(**data.get("invertor_prms", {}))
        invertor_prm1 = InvertorParams1(**data.get("invertor_prm1", {}))
        
        # Optional fields
        device = DeviceData(**data["device"]) if "device" in data else None
        queen = bool(data.get("queen", False))
        
        # Handle boiler data which could be empty list or dict
        boiler = None
        if "boiler" in data and isinstance(data["boiler"], dict) and data["boiler"]:
            boiler = BoilerData(**data["boiler"])
            
        # Other optional components
        boiler_prms = BoilerParams(**data["boiler_prms"]) if "boiler_prms" in data else None
        batt_prms = BatteryParams(**data["batt_prms"]) if "batt_prms" in data else None
        box = BoxData(**data["box"]) if "box" in data else None
        box_prm2 = BoxParams2(**data["box_prm2"]) if "box_prm2" in data else None
        ac_in_b = AcInBData(**data["ac_in_b"]) if "ac_in_b" in data else None
        
        return cls(
            ac_in=ac_in,
            ac_out=ac_out,
            actual=actual,
            batt=batt,
            dc_in=dc_in,
            box_prms=box_prms,
            invertor_prms=invertor_prms,
            invertor_prm1=invertor_prm1,
            queen=queen,
            device=device,
            boiler=boiler,
            boiler_prms=boiler_prms,
            batt_prms=batt_prms,
            box=box,
            box_prm2=box_prm2,
            ac_in_b=ac_in_b,
        )


@dataclass
class OigCloudData:
    """Model for complete OIG Cloud API data."""
    
    devices: Dict[str, OigCloudDeviceData] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, Any]]) -> 'OigCloudData':
        """Create an instance from a dictionary."""
        devices = {}
        for device_id, device_data in data.items():
            devices[device_id] = OigCloudDeviceData.from_dict(device_data)
            
        return cls(devices=devices)