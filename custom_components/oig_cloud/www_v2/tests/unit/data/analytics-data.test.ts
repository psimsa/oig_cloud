import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  loadAnalyticsData,
  extractAnalyticsSensors,
  EMPTY_ANALYTICS,
  type BatteryEfficiencyData,
  type BatteryHealthData,
  type BatteryBalancingData,
  type CostComparisonData,
} from '@/data/analytics-data';
import { getEntityStore } from '@/data/entity-store';
import { haClient } from '@/data/ha-client';

vi.mock('@/data/entity-store', () => ({
  getEntityStore: vi.fn(),
}));

vi.mock('@/data/ha-client', () => ({
  haClient: {
    loadUnifiedCostTile: vi.fn(),
    loadBatteryTimeline: vi.fn(),
  },
}));

vi.mock('@/core/logger', () => ({
  oigLog: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

describe('analytics-data', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('extractEfficiency', () => {
    it('should return null when entity store is not available', () => {
      vi.mocked(getEntityStore).mockReturnValue(null);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).toBeNull();
    });

    it('should return null when battery_efficiency sensor not found', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_efficiency'),
        get: vi.fn().mockReturnValue(null),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).toBeNull();
    });

    it('should extract efficiency data from sensor attributes', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_efficiency'),
        get: vi.fn().mockReturnValue({
          state: '92.5',
          attributes: {
            efficiency_last_month_pct: 91.0,
            last_month_charge_kwh: 50.5,
            last_month_discharge_kwh: 46.0,
            losses_last_month_kwh: 4.5,
            losses_last_month_pct: 8.9,
            efficiency_current_month_pct: 92.5,
            current_month_charge_kwh: 30.2,
            current_month_discharge_kwh: 27.9,
            losses_current_month_kwh: 2.3,
            losses_current_month_pct: 7.6,
            current_month_days: 15,
          },
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).not.toBeNull();
      expect(result.efficiency?.efficiency).toBe(91.0);
      expect(result.efficiency?.charged).toBe(50.5);
      expect(result.efficiency?.discharged).toBe(46.0);
      expect(result.efficiency?.losses).toBe(4.5);
      expect(result.efficiency?.period).toBe('last_month');
      expect(result.efficiency?.trend).toBe(1.5);
      expect(result.efficiency?.lastMonth).not.toBeNull();
      expect(result.efficiency?.currentMonth).not.toBeNull();
    });

    it('should fall back to current month when last month not available', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_efficiency'),
        get: vi.fn().mockReturnValue({
          state: '92.5',
          attributes: {
            efficiency_current_month_pct: 92.5,
            current_month_charge_kwh: 30.2,
            current_month_discharge_kwh: 27.9,
            losses_current_month_kwh: 2.3,
            losses_current_month_pct: 7.6,
            current_month_days: 15,
          },
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).not.toBeNull();
      expect(result.efficiency?.efficiency).toBe(92.5);
      expect(result.efficiency?.period).toBe('current_month');
      expect(result.efficiency?.lastMonth).toBeNull();
      expect(result.efficiency?.currentMonth).not.toBeNull();
    });

    it('should return null when no efficiency data available', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_efficiency'),
        get: vi.fn().mockReturnValue({
          state: 'unavailable',
          attributes: {},
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).toBeNull();
    });
  });

  describe('extractHealth', () => {
    it('should return null when battery_health sensor not found', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_health'),
        get: vi.fn().mockReturnValue(null),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.health).toBeNull();
    });

    it('should extract health data with excellent status', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_health'),
        get: vi.fn().mockReturnValue({
          state: '96.5',
          attributes: {
            capacity_p80_last_20: 4.8,
            current_capacity_kwh: 5.0,
            capacity_p20_last_20: 4.5,
            measurement_count: 150,
            last_analysis: '2025-01-15T10:00:00',
            quality_score: 0.85,
            soh_selection_method: 'weighted_average',
            soh_method_description: 'Weighted average of last 20 measurements',
            measurement_history: [
              { timestamp: '2025-01-15T10:00:00', soh_percent: 96.5, capacity_kwh: 4.8, delta_soc: 20, charge_wh: 1000, duration_hours: 2 },
            ],
            degradation_3_months_percent: -0.5,
            degradation_6_months_percent: -1.2,
            degradation_12_months_percent: -2.5,
            degradation_per_year_percent: -2.5,
            estimated_eol_date: '2035-01-15',
            years_to_80pct: 6.2,
            trend_confidence: 0.78,
          },
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.health).not.toBeNull();
      expect(result.health?.soh).toBe(96.5);
      expect(result.health?.capacity).toBe(4.8);
      expect(result.health?.nominalCapacity).toBe(5.0);
      expect(result.health?.minCapacity).toBe(4.5);
      expect(result.health?.measurementCount).toBe(150);
      expect(result.health?.status).toBe('excellent');
      expect(result.health?.statusLabel).toBe('Vynikající');
      expect(result.health?.qualityScore).toBe(0.85);
    });

    it('should classify status correctly', () => {
      const testCases = [
        { soh: 96, expectedStatus: 'excellent', expectedLabel: 'Vynikající' },
        { soh: 92, expectedStatus: 'good', expectedLabel: 'Dobrý' },
        { soh: 85, expectedStatus: 'fair', expectedLabel: 'Uspokojivý' },
        { soh: 75, expectedStatus: 'poor', expectedLabel: 'Špatný' },
      ];

      for (const testCase of testCases) {
        const mockStore = {
          findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_health'),
          get: vi.fn().mockReturnValue({
            state: String(testCase.soh),
            attributes: {},
          }),
        };
        vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

        const result = extractAnalyticsSensors('2206237016');

        expect(result.health?.status).toBe(testCase.expectedStatus);
        expect(result.health?.statusLabel).toBe(testCase.expectedLabel);
      }
    });

    it('should handle empty measurement history', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_health'),
        get: vi.fn().mockReturnValue({
          state: '90.0',
          attributes: {
            measurement_history: null,
          },
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.health?.measurementHistory).toEqual([]);
    });
  });

  describe('extractBalancing', () => {
    it('should return null when no balancing data available', () => {
      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_balancing'),
        get: vi.fn().mockReturnValue(null),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.balancing).toBeNull();
    });

    it('should extract balancing data from dedicated sensor', () => {
      const mockStore = {
        findSensorId: vi.fn().mockImplementation((name: string) => `sensor.oig_2206237016_${name}`),
        get: vi.fn().mockImplementation((id: string) => {
          if (id.includes('battery_balancing')) {
            return {
              state: 'idle',
              attributes: {
                last_balancing: '2025-01-10T08:00:00',
                cost: 15.5,
                next_scheduled: '2025-02-10T08:00:00',
                interval_days: 30,
                estimated_next_cost: 16.0,
              },
            };
          }
          return null;
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.balancing).not.toBeNull();
      expect(result.balancing?.status).toBe('idle');
      expect(result.balancing?.lastBalancing).toBe('2025-01-10T08:00:00');
      expect(result.balancing?.cost).toBe(15.5);
      expect(result.balancing?.nextScheduled).toBe('2025-02-10T08:00:00');
      expect(result.balancing?.intervalDays).toBe(30);
      expect(result.balancing?.estimatedNextCost).toBe(16.0);
    });

    it('should fall back to battery_health attributes', () => {
      const mockStore = {
        findSensorId: vi.fn().mockImplementation((name: string) => `sensor.oig_2206237016_${name}`),
        get: vi.fn().mockImplementation((id: string) => {
          if (id.includes('battery_balancing')) {
            return null;
          }
          if (id.includes('battery_health')) {
            return {
              state: '90.0',
              attributes: {
                balancing_status: 'planned',
                last_balancing: '2025-01-05T10:00:00',
                balancing_cost: 12.0,
                next_balancing: '2025-02-05T10:00:00',
                balancing_interval_days: 31,
                estimated_next_cost: 12.5,
              },
            };
          }
          return null;
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.balancing).not.toBeNull();
      expect(result.balancing?.status).toBe('planned');
      expect(result.balancing?.lastBalancing).toBe('2025-01-05T10:00:00');
      expect(result.balancing?.cost).toBe(12.0);
    });

    it('should compute progress and days remaining', () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2025-01-20T12:00:00Z'));

      const mockStore = {
        findSensorId: vi.fn().mockReturnValue('sensor.oig_2206237016_battery_balancing'),
        get: vi.fn().mockReturnValue({
          state: 'idle',
          attributes: {
            last_balancing: '2025-01-01T00:00:00',
            next_scheduled: '2025-02-01T00:00:00',
            interval_days: 31,
          },
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.balancing?.daysRemaining).toBe(12);
      expect(result.balancing?.progressPercent).toBeGreaterThan(0);
      expect(result.balancing?.progressPercent).toBeLessThanOrEqual(100);

      vi.useRealTimers();
    });
  });

  describe('fetchCostComparison', () => {
    it('should fetch cost comparison from API', async () => {
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue({
        hybrid: {
          today: {
            actual_cost_so_far: 45.5,
            future_plan_cost: 30.2,
            plan_total_cost: 75.7,
          },
          tomorrow: {
            plan_total_cost: 68.3,
          },
        },
      });
      vi.mocked(haClient.loadBatteryTimeline).mockResolvedValue({
        timeline_extended: {
          yesterday: {
            summary: {
              planned_total_cost: 50.0,
              actual_total_cost: 52.5,
              delta_cost: 2.5,
              accuracy_pct: 95.2,
            },
          },
        },
      });

      const result = await loadAnalyticsData('2206237016');

      expect(result.costComparison).not.toBeNull();
      expect(result.costComparison?.actualSpent).toBe(45.5);
      expect(result.costComparison?.futurePlanCost).toBe(30.2);
      expect(result.costComparison?.planTotalCost).toBe(75.7);
      expect(result.costComparison?.tomorrowCost).toBe(68.3);
      expect(result.costComparison?.yesterdayPlannedCost).toBe(50.0);
      expect(result.costComparison?.yesterdayActualCost).toBe(52.5);
      expect(result.costComparison?.yesterdayDelta).toBe(2.5);
      expect(result.costComparison?.yesterdayAccuracy).toBe(95.2);
    });

    it('should handle missing yesterday data gracefully', async () => {
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue({
        hybrid: {
          today: {
            actual_total_cost: 45.5,
            future_plan_cost: 30.2,
            plan_total_cost: 75.7,
          },
        },
      });
      vi.mocked(haClient.loadBatteryTimeline).mockRejectedValue(new Error('API Error'));

      const result = await loadAnalyticsData('2206237016');

      expect(result.costComparison).not.toBeNull();
      expect(result.costComparison?.yesterdayPlannedCost).toBeNull();
      expect(result.costComparison?.yesterdayActualCost).toBeNull();
    });

    it('should handle null API response', async () => {
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue(null);

      const result = await loadAnalyticsData('2206237016');

      expect(result.costComparison).toBeNull();
    });

    it('should use actual_total_cost fallback', async () => {
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue({
        hybrid: {
          today: {
            actual_total_cost: 50.0,
            future_plan_cost: 25.0,
          },
        },
      });
      vi.mocked(haClient.loadBatteryTimeline).mockResolvedValue({ active: [] });

      const result = await loadAnalyticsData('2206237016');

      expect(result.costComparison?.actualSpent).toBe(50.0);
    });
  });

  describe('loadAnalyticsData', () => {
    it('should return EMPTY_ANALYTICS when no data available', async () => {
      vi.mocked(getEntityStore).mockReturnValue(null);
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue(null);

      const result = await loadAnalyticsData('2206237016');

      expect(result).toEqual(EMPTY_ANALYTICS);
    });

    it('should load all analytics data', async () => {
      const mockStore = {
        findSensorId: vi.fn().mockImplementation((name: string) => `sensor.oig_2206237016_${name}`),
        get: vi.fn().mockImplementation((id: string) => {
          if (id.includes('battery_efficiency')) {
            return {
              state: '92.5',
              attributes: {
                efficiency_current_month_pct: 92.5,
                current_month_charge_kwh: 30.2,
                current_month_discharge_kwh: 27.9,
                losses_current_month_kwh: 2.3,
                losses_current_month_pct: 7.6,
                current_month_days: 15,
              },
            };
          }
          if (id.includes('battery_health')) {
            return {
              state: '95.0',
              attributes: {
                capacity_p80_last_20: 4.8,
                current_capacity_kwh: 5.0,
                capacity_p20_last_20: 4.5,
                measurement_count: 150,
                last_analysis: '2025-01-15T10:00:00',
              },
            };
          }
          return null;
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);
      vi.mocked(haClient.loadUnifiedCostTile).mockResolvedValue({
        hybrid: {
          today: {
            actual_cost_so_far: 45.5,
            future_plan_cost: 30.2,
            plan_total_cost: 75.7,
          },
        },
      });
      vi.mocked(haClient.loadBatteryTimeline).mockResolvedValue({ active: [] });

      const result = await loadAnalyticsData('2206237016');

      expect(result.efficiency).not.toBeNull();
      expect(result.health).not.toBeNull();
      expect(result.costComparison).not.toBeNull();
    });
  });

  describe('extractAnalyticsSensors', () => {
    it('should extract only sensor-based data', () => {
      const mockStore = {
        findSensorId: vi.fn().mockImplementation((name: string) => `sensor.oig_2206237016_${name}`),
        get: vi.fn().mockImplementation((id: string) => {
          if (id.includes('battery_efficiency')) {
            return {
              state: '92.5',
              attributes: {
                efficiency_current_month_pct: 92.5,
                current_month_charge_kwh: 30.2,
                current_month_discharge_kwh: 27.9,
                losses_current_month_kwh: 2.3,
                losses_current_month_pct: 7.6,
                current_month_days: 15,
              },
            };
          }
          if (id.includes('battery_health')) {
            return {
              state: '95.0',
              attributes: {},
            };
          }
          return null;
        }),
      };
      vi.mocked(getEntityStore).mockReturnValue(mockStore as any);

      const result = extractAnalyticsSensors('2206237016');

      expect(result.efficiency).not.toBeNull();
      expect(result.health).not.toBeNull();
      expect(result.balancing).toBeNull();
      expect(result).not.toHaveProperty('costComparison');
    });
  });
});
