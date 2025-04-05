"""Tests for the OIG Cloud data models."""
import json
import unittest
from unittest.mock import patch

import pytest

from custom_components.oig_cloud.models import (
    AcInData, 
    AcOutData,
    BatteryData,
    DcInData,
    ActualData,
    BoxParams,
    InvertorParams,
    InvertorParams1,
    BoilerData,
    BoilerParams,
    OigCloudDeviceData,
    OigCloudData
)


class TestDataModels(unittest.TestCase):
    """Test the OIG Cloud data models."""

    def test_ac_in_data(self):
        """Test AcInData model."""
        data = AcInData(
            aci_wr=100.0,
            aci_ws=200.0,
            aci_wt=300.0,
            aci_vr=230.0,
            aci_vs=231.0,
            aci_vt=229.0,
            aci_f=50.0,
            ac_ad=1000.0,
            ac_pd=500.0,
        )
        
        self.assertEqual(data.aci_wr, 100.0)
        self.assertEqual(data.aci_ws, 200.0)
        self.assertEqual(data.aci_wt, 300.0)
        self.assertEqual(data.total_load, 600.0)  # Test computed property
    
    def test_battery_data(self):
        """Test BatteryData model."""
        data = BatteryData(
            bat_i=10.0,
            bat_v=48.0,
            bat_t=25.0,
            bat_q=95.0,
            bat_and=500.0,
            bat_apd=800.0,
            bat_am=30.0,
            bat_ay=300.0,
        )
        
        self.assertEqual(data.bat_i, 10.0)
        self.assertEqual(data.bat_v, 48.0)
        self.assertEqual(data.power, 480.0)  # Test computed property
    
    def test_dc_in_data(self):
        """Test DcInData model."""
        data = DcInData(
            fv_p1=1000.0,
            fv_p2=1200.0,
            fv_i1=4.0,
            fv_i2=4.5,
            fv_v1=250.0,
            fv_v2=260.0,
        )
        
        self.assertEqual(data.fv_p1, 1000.0)
        self.assertEqual(data.fv_p2, 1200.0)
        self.assertEqual(data.total_power, 2200.0)  # Test computed property
    
    def test_device_data_from_dict(self):
        """Test creating OigCloudDeviceData from a dictionary."""
        test_data = {
            "ac_in": {
                "aci_wr": 100.0,
                "aci_ws": 200.0,
                "aci_wt": 300.0,
                "aci_vr": 230.0,
                "aci_vs": 231.0,
                "aci_vt": 229.0,
                "aci_f": 50.0,
                "ac_ad": 1000.0,
                "ac_pd": 500.0,
            },
            "ac_out": {
                "aco_p": 450.0,
                "aco_vr": 230.0,
                "aco_vs": 231.0,
                "aco_vt": 229.0,
            },
            "batt": {
                "bat_i": 10.0,
                "bat_v": 48.0,
                "bat_t": 25.0,
                "bat_q": 95.0,
                "bat_and": 500.0,
                "bat_apd": 800.0,
                "bat_am": 30.0,
                "bat_ay": 300.0,
            },
            "dc_in": {
                "fv_p1": 1000.0,
                "fv_p2": 1200.0,
                "fv_i1": 4.0,
                "fv_i2": 4.5,
                "fv_v1": 250.0,
                "fv_v2": 260.0,
            },
            "actual": {
                "aci_wr": 100.0,
                "aci_ws": 200.0,
                "aci_wt": 300.0,
                "fv_p1": 1000.0,
                "fv_p2": 1200.0,
                "bat_p": 480.0,
            },
            "box_prms": {
                "mode": 1,
                "sw": "1.2.3",
                "crcte": 1,
            },
            "invertor_prms": {
                "to_grid": 1,
            },
            "invertor_prm1": {
                "p_max_feed_grid": 9000,
            },
            "boiler": {
                "p": 1500.0,
                "ssr1": 1,
                "ssr2": 0,
                "ssr3": 0,
            },
            "boiler_prms": {
                "manual": 0,
            },
            "queen": True,
        }
        
        device_data = OigCloudDeviceData.from_dict(test_data)
        
        # Test that the model parsed correctly
        self.assertEqual(device_data.ac_in.aci_wr, 100.0)
        self.assertEqual(device_data.dc_in.total_power, 2200.0)
        self.assertEqual(device_data.batt.power, 480.0)
        self.assertEqual(device_data.box_prms.mode, 1)
        self.assertEqual(device_data.invertor_prm1.p_max_feed_grid, 9000)
        self.assertTrue(device_data.queen)
        self.assertEqual(device_data.boiler.p, 1500.0)
    
    def test_cloud_data_from_dict(self):
        """Test creating OigCloudData from a dictionary with multiple devices."""
        test_data = {
            "device1": {
                "ac_in": {
                    "aci_wr": 100.0,
                    "aci_ws": 200.0,
                    "aci_wt": 300.0,
                    "aci_vr": 230.0,
                    "aci_vs": 231.0,
                    "aci_vt": 229.0,
                    "aci_f": 50.0,
                    "ac_ad": 1000.0,
                    "ac_pd": 500.0,
                },
                "ac_out": {
                    "aco_p": 450.0,
                    "aco_vr": 230.0,
                    "aco_vs": 231.0,
                    "aco_vt": 229.0,
                },
                "batt": {
                    "bat_i": 10.0,
                    "bat_v": 48.0,
                    "bat_t": 25.0,
                    "bat_q": 95.0,
                    "bat_and": 500.0,
                    "bat_apd": 800.0,
                    "bat_am": 30.0,
                    "bat_ay": 300.0,
                },
                "dc_in": {
                    "fv_p1": 1000.0,
                    "fv_p2": 1200.0,
                    "fv_i1": 4.0,
                    "fv_i2": 4.5,
                    "fv_v1": 250.0,
                    "fv_v2": 260.0,
                },
                "actual": {
                    "aci_wr": 100.0,
                    "aci_ws": 200.0,
                    "aci_wt": 300.0,
                    "fv_p1": 1000.0,
                    "fv_p2": 1200.0,
                    "bat_p": 480.0,
                },
                "box_prms": {
                    "mode": 1,
                    "sw": "1.2.3",
                    "crcte": 1,
                },
                "invertor_prms": {
                    "to_grid": 1,
                },
                "invertor_prm1": {
                    "p_max_feed_grid": 9000,
                },
                "queen": False,
            }
        }
        
        cloud_data = OigCloudData.from_dict(test_data)
        
        # Test that the model parsed correctly
        self.assertIn("device1", cloud_data.devices)
        self.assertEqual(cloud_data.devices["device1"].box_prms.mode, 1)
        self.assertEqual(cloud_data.devices["device1"].ac_in.total_load, 600.0)
        self.assertEqual(cloud_data.devices["device1"].dc_in.total_power, 2200.0)
        self.assertFalse(cloud_data.devices["device1"].queen)