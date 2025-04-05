"""Tests for the OIG Cloud data models."""
import json
import unittest
from datetime import datetime
from unittest.mock import Mock

from custom_components.oig_cloud.models import (
    AcInData,
    AcInBData,
    AcOutData,
    BatteryData,
    BatteryParams, 
    BoilerData,
    BoilerParams,
    BoxData,
    BoxParams,
    BoxParams2,
    DcInData,
    DeviceData,
    InvertorParams,
    InvertorParams1,
    ActualData,
    OigCloudDeviceData,
    OigCloudData
)


class TestModels(unittest.TestCase):
    """Tests for the OIG Cloud data models."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Load sample data from the sample-response.json file
        with open("tests/sample-response.json", "r") as f:
            self.raw_data = json.load(f)
            
        # Get a single device for testing
        first_device_id = next(iter(self.raw_data))
        self.single_device_data = self.raw_data[first_device_id]
            
    def test_ac_in_data(self):
        """Test AcInData class."""
        ac_in_data = {
            "aci_vr": 230.5,
            "aci_vs": 231.0,
            "aci_vt": 229.8,
            "aci_wr": 250.0,
            "aci_ws": 300.0,
            "aci_wt": 200.0,
            "aci_f": 50.0,
            "ac_ad": 5.0,
            "ac_am": 150.0,
            "ac_ay": 1500.0,
            "ac_pd": 1.2,
            "ac_pm": 25.0,
            "ac_py": 300.0
        }
        
        model = AcInData(**ac_in_data)
        
        self.assertEqual(model.aci_vr, 230.5)
        self.assertEqual(model.aci_vs, 231.0)
        self.assertEqual(model.aci_vt, 229.8)
        self.assertEqual(model.aci_wr, 250.0)
        self.assertEqual(model.aci_ws, 300.0)
        self.assertEqual(model.aci_wt, 200.0)
        self.assertEqual(model.aci_f, 50.0)
        self.assertEqual(model.ac_ad, 5.0)
        self.assertEqual(model.ac_am, 150.0)
        self.assertEqual(model.ac_ay, 1500.0)
        self.assertEqual(model.ac_pd, 1.2)
        self.assertEqual(model.ac_pm, 25.0)
        self.assertEqual(model.ac_py, 300.0)
        
        # Test calculated property
        self.assertEqual(model.total_load, 750.0)
        
    def test_ac_in_b_data(self):
        """Test AcInBData class."""
        ac_in_b_data = {
            "aci_wr": 100.0,
            "aci_ws": 200.0,
            "aci_wt": 300.0
        }
        
        model = AcInBData(**ac_in_b_data)
        
        self.assertEqual(model.aci_wr, 100.0)
        self.assertEqual(model.aci_ws, 200.0)
        self.assertEqual(model.aci_wt, 300.0)
        
        # Test calculated property
        self.assertEqual(model.total_load, 600.0)
        
    def test_ac_in_b_data_defaults(self):
        """Test AcInBData class with defaults."""
        model = AcInBData()
        
        self.assertEqual(model.aci_wr, 0)
        self.assertEqual(model.aci_ws, 0)
        self.assertEqual(model.aci_wt, 0)
        self.assertEqual(model.total_load, 0)
        
    def test_ac_out_data(self):
        """Test AcOutData class."""
        ac_out_data = {
            "aco_p": 1500.0,
            "aco_pr": 500.0,
            "aco_ps": 500.0,
            "aco_pt": 500.0,
            "aco_vr": 230.0,
            "aco_vs": 231.0,
            "aco_vt": 229.0,
            "en_day": 15.5
        }
        
        model = AcOutData(**ac_out_data)
        
        self.assertEqual(model.aco_p, 1500.0)
        self.assertEqual(model.aco_pr, 500.0)
        self.assertEqual(model.aco_ps, 500.0)
        self.assertEqual(model.aco_pt, 500.0)
        self.assertEqual(model.aco_vr, 230.0)
        self.assertEqual(model.aco_vs, 231.0)
        self.assertEqual(model.aco_vt, 229.0)
        self.assertEqual(model.en_day, 15.5)
        
    def test_ac_out_data_optional_fields(self):
        """Test AcOutData with only required fields."""
        model = AcOutData(aco_p=1500.0)
        
        self.assertEqual(model.aco_p, 1500.0)
        self.assertIsNone(model.aco_pr)
        self.assertIsNone(model.aco_ps)
        self.assertIsNone(model.aco_pt)
        self.assertIsNone(model.aco_vr)
        self.assertIsNone(model.aco_vs)
        self.assertIsNone(model.aco_vt)
        self.assertIsNone(model.en_day)
        
    def test_battery_data(self):
        """Test BatteryData class."""
        battery_data = {
            "bat_i": 10.0,
            "bat_v": 48.0,
            "bat_t": 25.0,
            "bat_q": 95.0,
            "bat_c": 90.0,
            "bat_and": 2.0,
            "bat_apd": 8.0,
            "bat_am": 150.0,
            "bat_ay": 1800.0
        }
        
        model = BatteryData(**battery_data)
        
        self.assertEqual(model.bat_i, 10.0)
        self.assertEqual(model.bat_v, 48.0)
        self.assertEqual(model.bat_t, 25.0)
        self.assertEqual(model.bat_q, 95.0)
        self.assertEqual(model.bat_c, 90.0)
        self.assertEqual(model.bat_and, 2.0)
        self.assertEqual(model.bat_apd, 8.0)
        self.assertEqual(model.bat_am, 150.0)
        self.assertEqual(model.bat_ay, 1800.0)
        
        # Test calculated property
        self.assertEqual(model.power, 480.0)
        
    def test_battery_data_partial(self):
        """Test BatteryData with partial data."""
        model = BatteryData(bat_c=90.0)
        
        self.assertIsNone(model.bat_i)
        self.assertIsNone(model.bat_v)
        self.assertEqual(model.bat_c, 90.0)
        self.assertIsNone(model.power)
        
    def test_battery_params(self):
        """Test BatteryParams class."""
        battery_params = {
            "bat_min": 20.0,
            "bat_gl_min": 10.0,
            "bat_hdo": 1,
            "bal_on": 1,
            "hdo1_s": 22,
            "hdo1_e": 6,
            "hdo2_s": 13,
            "hdo2_e": 15
        }
        
        model = BatteryParams(**battery_params)
        
        self.assertEqual(model.bat_min, 20.0)
        self.assertEqual(model.bat_gl_min, 10.0)
        self.assertEqual(model.bat_hdo, 1)
        self.assertEqual(model.bal_on, 1)
        self.assertEqual(model.hdo1_s, 22)
        self.assertEqual(model.hdo1_e, 6)
        self.assertEqual(model.hdo2_s, 13)
        self.assertEqual(model.hdo2_e, 15)
        
    def test_boiler_data(self):
        """Test BoilerData class."""
        boiler_data = {
            "p": 2000.0,
            "ssr1": 1,
            "ssr2": 1,
            "ssr3": 0
        }
        
        model = BoilerData(**boiler_data)
        
        self.assertEqual(model.p, 2000.0)
        self.assertEqual(model.ssr1, 1)
        self.assertEqual(model.ssr2, 1)
        self.assertEqual(model.ssr3, 0)
        
    def test_boiler_data_empty(self):
        """Test BoilerData with no data."""
        model = BoilerData()
        
        self.assertIsNone(model.p)
        self.assertIsNone(model.ssr1)
        self.assertIsNone(model.ssr2)
        self.assertIsNone(model.ssr3)
        
    def test_boiler_params(self):
        """Test BoilerParams class."""
        boiler_params = {
            "ison": 1,
            "prrty": 2,
            "p_set": 2000.0,
            "p_set2": 1500.0,
            "p_set3": 1000.0,
            "zone1_s": 6,
            "zone1_e": 9,
            "zone2_s": 17,
            "zone2_e": 22,
            "zone3_s": 0,
            "zone3_e": 0,
            "zone4_s": 0,
            "zone4_e": 0,
            "hdo": 1,
            "termostat": 0,
            "manual": 1,
            "wd": 12345,
            "ssr0": 1,
            "ssr1": 1,
            "ssr2": 1,
            "id_subd": 0,
            "stht": 0,
            "offset": 100,
            "offset2": 0,
            "offset3": 0,
            "tset": 22.0,
            "tset2": 20.0
        }
        
        model = BoilerParams(**boiler_params)
        
        self.assertEqual(model.ison, 1)
        self.assertEqual(model.prrty, 2)
        self.assertEqual(model.p_set, 2000.0)
        self.assertEqual(model.p_set2, 1500.0)
        self.assertEqual(model.p_set3, 1000.0)
        self.assertEqual(model.zone1_s, 6)
        self.assertEqual(model.zone1_e, 9)
        self.assertEqual(model.zone2_s, 17)
        self.assertEqual(model.zone2_e, 22)
        self.assertEqual(model.hdo, 1)
        self.assertEqual(model.manual, 1)
        
    def test_boiler_params_defaults(self):
        """Test BoilerParams defaults."""
        model = BoilerParams()
        
        self.assertEqual(model.ison, 0)
        self.assertEqual(model.prrty, 0)
        self.assertEqual(model.p_set, 0)
        self.assertEqual(model.zone1_s, 0)
        self.assertEqual(model.zone1_e, 0)
        self.assertEqual(model.manual, 0)
        self.assertEqual(model.wd, 50000)
        
    def test_box_data(self):
        """Test BoxData class."""
        box_data = {
            "temp": 25.5,
            "humid": 45.2
        }
        
        model = BoxData(**box_data)
        
        self.assertEqual(model.temp, 25.5)
        self.assertEqual(model.humid, 45.2)
        
    def test_box_params(self):
        """Test BoxParams class."""
        box_params = {
            "bat_ac": 0,
            "p_fve": 5000.0,
            "p_bat": 2500.0,
            "mode": 1,
            "mode1": 2,
            "crct": 123456,
            "crcte": 654321,
            "sw": "1.2.3"
        }
        
        model = BoxParams(**box_params)
        
        self.assertEqual(model.bat_ac, 0)
        self.assertEqual(model.p_fve, 5000.0)
        self.assertEqual(model.p_bat, 2500.0)
        self.assertEqual(model.mode, 1)
        self.assertEqual(model.mode1, 2)
        self.assertEqual(model.crct, 123456)
        self.assertEqual(model.crcte, 654321)
        self.assertEqual(model.sw, "1.2.3")
        
    def test_box_params_no_sw(self):
        """Test BoxParams without sw field."""
        box_params = {
            "bat_ac": 0,
            "p_fve": 5000.0,
            "p_bat": 2500.0,
            "mode": 1,
            "mode1": 2,
            "crct": 123456,
            "crcte": 654321
        }
        
        model = BoxParams(**box_params)
        
        self.assertEqual(model.bat_ac, 0)
        self.assertEqual(model.p_fve, 5000.0)
        self.assertEqual(model.p_bat, 2500.0)
        self.assertEqual(model.mode, 1)
        self.assertEqual(model.mode1, 2)
        self.assertEqual(model.crct, 123456)
        self.assertEqual(model.crcte, 654321)
        self.assertIsNone(model.sw)
        
    def test_box_params2(self):
        """Test BoxParams2 class."""
        box_params2 = {
            "app": 1,
            "wdogx": 12345
        }
        
        model = BoxParams2(**box_params2)
        
        self.assertEqual(model.app, 1)
        self.assertEqual(model.wdogx, 12345)
        
    def test_box_params2_defaults(self):
        """Test BoxParams2 defaults."""
        model = BoxParams2()
        
        self.assertEqual(model.app, 0)
        self.assertEqual(model.wdogx, 0)
        
    def test_dc_in_data(self):
        """Test DcInData class."""
        dc_in_data = {
            "fv_proc": 80.0,
            "fv_p1": 2000.0,
            "fv_p2": 3000.0,
            "fv_i1": 8.0,
            "fv_i2": 12.0,
            "fv_v1": 250.0,
            "fv_v2": 250.0,
            "fv_ad": 12.0,
            "fv_am": 300.0,
            "fv_ay": 3600.0
        }
        
        model = DcInData(**dc_in_data)
        
        self.assertEqual(model.fv_proc, 80.0)
        self.assertEqual(model.fv_p1, 2000.0)
        self.assertEqual(model.fv_p2, 3000.0)
        self.assertEqual(model.fv_i1, 8.0)
        self.assertEqual(model.fv_i2, 12.0)
        self.assertEqual(model.fv_v1, 250.0)
        self.assertEqual(model.fv_v2, 250.0)
        self.assertEqual(model.fv_ad, 12.0)
        self.assertEqual(model.fv_am, 300.0)
        self.assertEqual(model.fv_ay, 3600.0)
        
        # Test calculated property
        self.assertEqual(model.total_power, 5000.0)
        
    def test_dc_in_data_defaults(self):
        """Test DcInData defaults."""
        model = DcInData()
        
        self.assertEqual(model.fv_proc, 0)
        self.assertEqual(model.fv_p1, 0)
        self.assertEqual(model.fv_p2, 0)
        self.assertEqual(model.total_power, 0)
        
    def test_device_data(self):
        """Test DeviceData class."""
        device_data = {
            "id_type": 1,
            "lastcall": "2025-04-05 12:34:56"
        }
        
        model = DeviceData(**device_data)
        
        self.assertEqual(model.id_type, 1)
        self.assertEqual(model.lastcall, "2025-04-05 12:34:56")
        
    def test_invertor_params(self):
        """Test InvertorParams class."""
        invertor_params = {
            "to_grid": 1
        }
        
        model = InvertorParams(**invertor_params)
        
        self.assertEqual(model.to_grid, 1)
        
    def test_invertor_params1(self):
        """Test InvertorParams1 class."""
        invertor_params1 = {
            "p_max_feed_grid": 5000
        }
        
        model = InvertorParams1(**invertor_params1)
        
        self.assertEqual(model.p_max_feed_grid, 5000)
        
    def test_actual_data(self):
        """Test ActualData class."""
        actual_data = {
            "aci_wr": 100.0,
            "aci_ws": 200.0,
            "aci_wt": 300.0,
            "aco_p": 1500.0,
            "fv_p1": 2000.0,
            "fv_p2": 3000.0,
            "bat_p": 1000.0,
            "bat_c": 85.0,
            "viz": 1
        }
        
        model = ActualData(**actual_data)
        
        self.assertEqual(model.aci_wr, 100.0)
        self.assertEqual(model.aci_ws, 200.0)
        self.assertEqual(model.aci_wt, 300.0)
        self.assertEqual(model.aco_p, 1500.0)
        self.assertEqual(model.fv_p1, 2000.0)
        self.assertEqual(model.fv_p2, 3000.0)
        self.assertEqual(model.bat_p, 1000.0)
        self.assertEqual(model.bat_c, 85.0)
        self.assertEqual(model.viz, 1)
        
        # Test calculated properties
        self.assertEqual(model.grid_total, 600.0)
        self.assertEqual(model.solar_total, 5000.0)
        
    def test_oig_cloud_device_data_from_dict(self):
        """Test OigCloudDeviceData.from_dict method."""
        device_data = self.single_device_data
        
        model = OigCloudDeviceData.from_dict(device_data)
        
        # Check that core components are parsed correctly
        self.assertIsInstance(model.ac_in, AcInData)
        self.assertIsInstance(model.ac_out, AcOutData)
        self.assertIsInstance(model.actual, ActualData)
        self.assertIsInstance(model.batt, BatteryData)
        self.assertIsInstance(model.dc_in, DcInData)
        self.assertIsInstance(model.box_prms, BoxParams)
        self.assertIsInstance(model.invertor_prms, InvertorParams)
        self.assertIsInstance(model.invertor_prm1, InvertorParams1)
        
        # Optional components might be present depending on test data
        if model.device is not None:
            self.assertIsInstance(model.device, DeviceData)
        if model.boiler is not None:
            self.assertIsInstance(model.boiler, BoilerData)
        if model.boiler_prms is not None:
            self.assertIsInstance(model.boiler_prms, BoilerParams)
        if model.batt_prms is not None:
            self.assertIsInstance(model.batt_prms, BatteryParams)
        if model.box is not None:
            self.assertIsInstance(model.box, BoxData)
        if model.box_prm2 is not None:
            self.assertIsInstance(model.box_prm2, BoxParams2)
        if model.ac_in_b is not None:
            self.assertIsInstance(model.ac_in_b, AcInBData)
            
    def test_oig_cloud_device_data_special_bat_c_case(self):
        """Test special case where batt only contains bat_c."""
        device_data = {
            "ac_in": {
                "aci_vr": 230.0,
                "aci_vs": 230.0,
                "aci_vt": 230.0,
                "aci_wr": 100.0,
                "aci_ws": 100.0,
                "aci_wt": 100.0,
                "aci_f": 50.0
            },
            "ac_out": {
                "aco_p": 1500.0
            },
            "actual": {
                "aci_wr": 100.0,
                "aci_ws": 100.0,
                "aci_wt": 100.0,
                "aco_p": 1500.0,
                "fv_p1": 2000.0,
                "fv_p2": 3000.0,
                "bat_p": 1000.0,
                "bat_c": 85.0,
                "viz": 1
            },
            "batt": {
                "bat_c": 85.0
            },
            "dc_in": {
                "fv_p1": 2000.0,
                "fv_p2": 3000.0
            },
            "box_prms": {
                "bat_ac": 0,
                "p_fve": 5000.0,
                "p_bat": 2500.0,
                "mode": 1,
                "mode1": 2,
                "crct": 123456,
                "crcte": 654321
            },
            "invertor_prms": {
                "to_grid": 1
            },
            "invertor_prm1": {
                "p_max_feed_grid": 5000
            }
        }
        
        model = OigCloudDeviceData.from_dict(device_data)
        
        self.assertIsInstance(model.batt, BatteryData)
        self.assertEqual(model.batt.bat_c, 85.0)
        self.assertEqual(model.batt.bat_i, 0)
        self.assertEqual(model.batt.bat_v, 0)
        self.assertEqual(model.batt.power, 0)
        
    def test_oig_cloud_data_from_dict(self):
        """Test OigCloudData.from_dict method."""
        data = self.raw_data
        
        model = OigCloudData.from_dict(data)
        
        # Check that we have the right number of devices
        self.assertEqual(len(model.devices), len(data))
        
        # Check that each device is parsed correctly
        for device_id, device_data in model.devices.items():
            self.assertIsInstance(device_data, OigCloudDeviceData)
            
            # Check that the device contains the core components
            self.assertIsInstance(device_data.ac_in, AcInData)
            self.assertIsInstance(device_data.ac_out, AcOutData)
            self.assertIsInstance(device_data.actual, ActualData)
            self.assertIsInstance(device_data.batt, BatteryData)
            self.assertIsInstance(device_data.dc_in, DcInData)
            self.assertIsInstance(device_data.box_prms, BoxParams)
            self.assertIsInstance(device_data.invertor_prms, InvertorParams)
            self.assertIsInstance(device_data.invertor_prm1, InvertorParams1)


if __name__ == "__main__":
    unittest.main()