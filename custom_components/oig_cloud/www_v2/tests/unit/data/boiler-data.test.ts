import { describe, it, expect, vi, beforeEach } from 'vitest';

interface MockBoilerPlanAPI {
  state?: {
    current_temp?: number;
    target_temp?: number;
    heating?: boolean;
    next_profile?: string;
    next_start?: string;
    temperatures?: {
      upper_zone?: number;
      lower_zone?: number;
      top?: number;
      bottom?: number;
    };
    energy_state?: {
      avg_temp?: number;
      energy_needed_kwh?: number;
    };
    recommended_source?: string;
    circulation_recommended?: boolean;
  };
  profiles?: Record<string, {
    id?: string;
    name?: string;
    target_temp?: number;
    start_time?: string;
    end_time?: string;
    days?: number[];
    enabled?: boolean;
    hourly_avg?: Record<string, number>;
    heatmap?: number[][];
  }>;
  current_category?: string;
  config?: {
    min_temp?: number;
    max_temp?: number;
    volume_l?: number;
    target_temp_c?: number;
    deadline_time?: string;
    stratification_mode?: string;
    cold_inlet_temp_c?: number;
  };
  summary?: {
    today_hours?: number[];
    predicted_total_kwh?: number;
    predicted_cost?: number;
    peak_hours?: number[];
    water_liters_40c?: number;
    circulation_windows?: Array<{ start: string; end: string }>;
    avg_confidence?: number;
  };
  slots?: Array<{
    start?: string;
    end?: string;
    consumption_kwh?: number;
    avg_consumption_kwh?: number;
    recommended_source?: string;
    spot_price?: number;
    temp_top?: number;
    soc?: number;
  }>;
  total_consumption_kwh?: number;
  fve_kwh?: number;
  grid_kwh?: number;
  alt_kwh?: number;
  estimated_cost_czk?: number;
  next_slot?: {
    start?: string;
    end?: string;
    consumption_kwh?: number;
    recommended_source?: string;
    spot_price?: number;
  };
}

const mockFetchOIGAPI = vi.fn();
const mockCallService = vi.fn();
const mockLoadBatteryTimeline = vi.fn();

vi.mock('../../../src/data/ha-client', () => ({
  haClient: {
    fetchOIGAPI: (...args: unknown[]) => mockFetchOIGAPI(...args),
    callService: (...args: unknown[]) => mockCallService(...args),
    loadBatteryTimeline: (...args: unknown[]) => mockLoadBatteryTimeline(...args),
  },
}));

vi.mock('../../../src/core/logger', () => ({
  oigLog: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

describe('boiler-data', () => {
  let boilerData: typeof import('../../../src/data/boiler-data');

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();
    
    Object.defineProperty(window, 'location', {
      value: { search: '?entry_id=test_entry&sn=2206237016' },
      writable: true,
      configurable: true,
    });
    
    boilerData = await import('../../../src/data/boiler-data');
  });

  describe('getSensorId', () => {
    it('should generate correct sensor ID with default inverter SN', () => {
      const result = boilerData.getSensorId('boiler_temp');
      expect(result).toBe('sensor.oig_2206237016_boiler_temp');
    });

    it('should handle different sensor names', () => {
      expect(boilerData.getSensorId('heating_status')).toBe('sensor.oig_2206237016_heating_status');
      expect(boilerData.getSensorId('energy_consumption')).toBe('sensor.oig_2206237016_energy_consumption');
    });
  });

  describe('loadBoilerData', () => {
    const mockProfileData: MockBoilerPlanAPI = {
      state: {
        current_temp: 45,
        target_temp: 60,
        heating: true,
        next_profile: 'workday_summer',
        next_start: '2024-01-15T06:00:00',
        temperatures: {
          upper_zone: 55,
          lower_zone: 35,
        },
        energy_state: {
          avg_temp: 45,
          energy_needed_kwh: 2.5,
        },
        recommended_source: 'fve',
        circulation_recommended: true,
      },
      profiles: {
        workday_summer: {
          id: 'workday_summer',
          name: 'Workday Summer',
          target_temp: 60,
          start_time: '06:00',
          end_time: '22:00',
          days: [1, 1, 1, 1, 1, 0, 0],
          enabled: true,
          hourly_avg: { '6': 1.2, '7': 0.8, '18': 1.5 },
        },
      },
      current_category: 'workday_summer',
      config: {
        min_temp: 40,
        max_temp: 70,
        volume_l: 200,
        target_temp_c: 60,
        deadline_time: '22:00',
        stratification_mode: 'standard',
        cold_inlet_temp_c: 10,
      },
      summary: {
        today_hours: [6, 7, 18],
        predicted_total_kwh: 3.5,
        predicted_cost: 15.2,
        peak_hours: [6, 18],
        water_liters_40c: 150,
        circulation_windows: [{ start: '06:00', end: '08:00' }],
        avg_confidence: 0.85,
      },
    };

    const mockPlanData: MockBoilerPlanAPI = {
      state: {
        current_temp: 45,
        target_temp: 60,
        heating: true,
        temperatures: {
          upper_zone: 55,
          lower_zone: 35,
        },
        energy_state: {
          avg_temp: 45,
          energy_needed_kwh: 2.5,
        },
        recommended_source: 'fve',
      },
      slots: [
        {
          start: '2024-01-15T06:00:00',
          end: '2024-01-15T07:00:00',
          consumption_kwh: 1.2,
          avg_consumption_kwh: 1.2,
          recommended_source: 'fve',
          spot_price: 1.5,
          temp_top: 55,
          soc: 80,
        },
        {
          start: '2024-01-15T18:00:00',
          end: '2024-01-15T19:00:00',
          consumption_kwh: 1.5,
          avg_consumption_kwh: 1.5,
          recommended_source: 'grid',
          spot_price: 3.2,
          temp_top: 60,
          soc: 75,
        },
      ],
      total_consumption_kwh: 2.7,
      fve_kwh: 1.2,
      grid_kwh: 1.5,
      alt_kwh: 0,
      estimated_cost_czk: 8.7,
      next_slot: {
        start: '2024-01-15T18:00:00',
        end: '2024-01-15T19:00:00',
        consumption_kwh: 1.5,
        recommended_source: 'grid',
        spot_price: 3.2,
      },
    };

    it('should load and parse boiler data correctly', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.state.currentTemp).toBe(45);
      expect(result.state.targetTemp).toBe(60);
      expect(result.state.heating).toBe(true);
      expect(result.state.tempTop).toBe(55);
      expect(result.state.tempBottom).toBe(35);
      expect(result.state.avgTemp).toBe(45);
      expect(result.state.energyNeeded).toBe(2.5);
      expect(result.state.recommendedSource).toBe('FVE');
    });

    it('should handle null API responses gracefully', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(null);
      mockFetchOIGAPI.mockResolvedValueOnce(null);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.state.currentTemp).toBe(45);
      expect(result.state.targetTemp).toBe(60);
      expect(result.state.heating).toBe(false);
      expect(result.state.tempTop).toBeNull();
      expect(result.state.tempBottom).toBeNull();
      expect(result.state.avgTemp).toBeNull();
      expect(result.state.heatingPercent).toBeNull();
    });

    it('should parse plan data with source digest', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.plan).not.toBeNull();
      expect(result.plan!.totalConsumptionKwh).toBe(2.7);
      expect(result.plan!.fveKwh).toBe(1.2);
      expect(result.plan!.gridKwh).toBe(1.5);
      expect(result.plan!.altKwh).toBe(0);
      expect(result.plan!.estimatedCostCzk).toBe(8.7);
      expect(result.plan!.sourceDigest).toBe('Mix: FVE 44% · Síť 56% · Alt 0%');
      expect(result.plan!.activeSlotCount).toBe(2);
    });

    it('should calculate energy breakdown percentages', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.energyBreakdown.fveKwh).toBe(1.2);
      expect(result.energyBreakdown.gridKwh).toBe(1.5);
      expect(result.energyBreakdown.altKwh).toBe(0);
      expect(result.energyBreakdown.fvePercent).toBeCloseTo(44.44, 1);
      expect(result.energyBreakdown.gridPercent).toBeCloseTo(55.56, 1);
      expect(result.energyBreakdown.altPercent).toBe(0);
    });

    it('should parse predicted usage with circulation windows', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.predictedUsage.predictedTodayKwh).toBe(3.5);
      expect(result.predictedUsage.peakHours).toEqual([6, 18]);
      expect(result.predictedUsage.waterLiters40c).toBe(150);
      expect(result.predictedUsage.circulationWindows).toBe('06:00–08:00');
    });

    it('should parse config correctly', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.config.volumeL).toBe(200);
      expect(result.config.targetTempC).toBe(60);
      expect(result.config.deadlineTime).toBe('22:00');
      expect(result.config.stratificationMode).toBe('standard');
      expect(result.config.coldInletTempC).toBe(10);
      expect(result.config.kCoefficient).toBe('0.2326');
    });

    it('should parse profiles correctly', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.profiles).toHaveLength(1);
      expect(result.profiles[0].id).toBe('workday_summer');
      expect(result.profiles[0].name).toBe('Workday Summer');
      expect(result.profiles[0].targetTemp).toBe(60);
      expect(result.profiles[0].startTime).toBe('06:00');
      expect(result.profiles[0].endTime).toBe('22:00');
      expect(result.profiles[0].days).toEqual([1, 1, 1, 1, 1, 0, 0]);
      expect(result.profiles[0].enabled).toBe(true);
    });

    it('should generate heatmap data from planData summary', async () => {
      const planDataWithSummary: MockBoilerPlanAPI = {
        ...mockPlanData,
        summary: {
          today_hours: [6, 7, 18],
        },
      };
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(planDataWithSummary);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.heatmap).toHaveLength(24);
      expect(result.heatmap[6].heating).toBe(true);
      expect(result.heatmap[6].temp).toBe(55);
      expect(result.heatmap[8].heating).toBe(false);
      expect(result.heatmap[8].temp).toBe(25);
    });

    it('should generate 7x24 heatmap', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.heatmap7x24).toHaveLength(7);
      expect(result.heatmap7x24[0].day).toBe('Po');
      expect(result.heatmap7x24[0].hours).toHaveLength(24);
    });

    it('should parse profiling data', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockProfileData);
      mockFetchOIGAPI.mockResolvedValueOnce(mockPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.profiling.hourlyAvg).toHaveLength(24);
      expect(result.profiling.peakHours).toEqual([6, 18]);
      expect(result.profiling.predictedTotalKwh).toBe(3.5);
      expect(result.profiling.confidence).toBe(0.85);
      expect(result.profiling.daysTracked).toBe(7);
    });

    it('should handle API errors gracefully', async () => {
      mockFetchOIGAPI.mockRejectedValueOnce(new Error('Network error'));
      mockFetchOIGAPI.mockRejectedValueOnce(new Error('Network error'));
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.state.currentTemp).toBe(45);
      expect(result.profiles).toEqual([]);
      expect(result.plan).toBeNull();
    });
  });

  describe('recomputeForCategory', () => {
    const mockProfileData: MockBoilerPlanAPI = {
      profiles: {
        workday_summer: {
          name: 'Workday Summer',
          hourly_avg: { '6': 1.2, '18': 1.5 },
          heatmap: [Array(24).fill(0.5)],
        },
        weekend: {
          name: 'Weekend',
          hourly_avg: { '8': 1.0, '20': 1.2 },
          heatmap: [Array(24).fill(0.3)],
        },
      },
      summary: {
        predicted_total_kwh: 3.5,
        peak_hours: [6, 18],
        avg_confidence: 0.85,
      },
    };

    const mockPlanData: MockBoilerPlanAPI = {
      slots: [],
    };

    it('should recompute data for different category', () => {
      const result = boilerData.recomputeForCategory(mockProfileData, mockPlanData, 'weekend');

      expect(result.currentCategory).toBe('weekend');
      expect(result.profiling).toBeDefined();
      expect(result.predictedUsage).toBeDefined();
      expect(result.heatmap7x24).toBeDefined();
    });

    it('should handle missing category gracefully', () => {
      const result = boilerData.recomputeForCategory(mockProfileData, mockPlanData, 'nonexistent');

      expect(result.currentCategory).toBe('nonexistent');
      expect(result.heatmap7x24).toBeDefined();
      expect(result.heatmap7x24![0].hours.every(h => h === 0)).toBe(true);
    });
  });

  describe('service calls', () => {
    it('should call plan boiler heating service', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await boilerData.planBoilerHeating();

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('oig_cloud', 'plan_boiler_heating', {});
    });

    it('should call apply boiler plan service', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await boilerData.applyBoilerPlan();

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('oig_cloud', 'apply_boiler_plan', {});
    });

    it('should call cancel boiler plan service', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await boilerData.cancelBoilerPlan();

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('oig_cloud', 'cancel_boiler_plan', {});
    });

    it('should propagate service call errors', async () => {
      mockCallService.mockRejectedValueOnce(new Error('Service failed'));

      await expect(boilerData.planBoilerHeating()).rejects.toThrow('Service failed');
    });
  });

  describe('edge cases', () => {
    it('should handle zero energy values in breakdown', async () => {
      const emptyPlanData: MockBoilerPlanAPI = {
        slots: [],
        total_consumption_kwh: 0,
        fve_kwh: 0,
        grid_kwh: 0,
        alt_kwh: 0,
      };

      mockFetchOIGAPI.mockResolvedValueOnce({});
      mockFetchOIGAPI.mockResolvedValueOnce(emptyPlanData);
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.energyBreakdown.fvePercent).toBe(0);
      expect(result.energyBreakdown.gridPercent).toBe(0);
      expect(result.energyBreakdown.altPercent).toBe(0);
    });

    it('should handle missing temperature values', async () => {
      const incompleteData: MockBoilerPlanAPI = {
        state: {
          temperatures: {},
          energy_state: {},
        },
      };

      mockFetchOIGAPI.mockResolvedValueOnce(incompleteData);
      mockFetchOIGAPI.mockResolvedValueOnce({});
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.state.tempTop).toBeNull();
      expect(result.state.tempBottom).toBeNull();
      expect(result.state.avgTemp).toBeNull();
      expect(result.state.heatingPercent).toBeNull();
    });

    it('should handle invalid temperature values', async () => {
      const invalidData: MockBoilerPlanAPI = {
        state: {
          temperatures: {
            upper_zone: NaN,
            lower_zone: Infinity,
          },
          energy_state: {
            avg_temp: -Infinity,
          },
        },
      };

      mockFetchOIGAPI.mockResolvedValueOnce(invalidData);
      mockFetchOIGAPI.mockResolvedValueOnce({});
      mockLoadBatteryTimeline.mockResolvedValue(null);

      const result = await boilerData.loadBoilerData();

      expect(result.state.tempTop).toBeNull();
      expect(result.state.tempBottom).toBeNull();
      expect(result.state.avgTemp).toBeNull();
    });
  });
});
