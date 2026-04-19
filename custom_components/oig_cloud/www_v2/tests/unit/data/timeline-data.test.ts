import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockLoadDetailTabs = vi.fn();
const mockFetchOIGAPI = vi.fn();
const mockFetchSettings = vi.fn();
const mockSavePlannerSettings = vi.fn();
const mockInvalidate = vi.fn();

vi.mock('../../../src/data/ha-client', () => ({
  haClient: {
    loadDetailTabs: (...args: unknown[]) => mockLoadDetailTabs(...args),
    fetchOIGAPI: (...args: unknown[]) => mockFetchOIGAPI(...args),
    savePlannerSettings: (...args: unknown[]) => mockSavePlannerSettings(...args),
  },
  plannerState: {
    fetchSettings: (...args: unknown[]) => mockFetchSettings(...args),
    invalidate: () => mockInvalidate(),
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

import {
  TIMELINE_MODE_CONFIG,
  TIMELINE_TAB_LABELS,
  loadTimelineTab,
  loadAllTimelineTabs,
  loadPlannerSettings,
  savePlannerSettings,
  type TimelineTab,
  type ModeBlock,
  type TimelineDayData,
} from '../../../src/data/timeline-data';

describe('timeline-data', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('TIMELINE_MODE_CONFIG', () => {
    it('should define mode configurations', () => {
      expect(TIMELINE_MODE_CONFIG['HOME I']).toEqual({
        icon: '🏠',
        color: '#4CAF50',
        label: 'HOME I',
      });
      expect(TIMELINE_MODE_CONFIG['HOME II']).toEqual({
        icon: '⚡',
        color: '#2196F3',
        label: 'HOME II',
      });
      expect(TIMELINE_MODE_CONFIG['HOME III']).toEqual({
        icon: '🔋',
        color: '#9C27B0',
        label: 'HOME III',
      });
    });

    it('should include all expected modes', () => {
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('HOME I');
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('HOME II');
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('HOME III');
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('HOME UPS');
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('FULL HOME UPS');
      expect(Object.keys(TIMELINE_MODE_CONFIG)).toContain('DO NOTHING');
    });
  });

  describe('TIMELINE_TAB_LABELS', () => {
    it('should define tab labels', () => {
      expect(TIMELINE_TAB_LABELS.yesterday).toBe('📊 Včera');
      expect(TIMELINE_TAB_LABELS.today).toBe('📆 Dnes');
      expect(TIMELINE_TAB_LABELS.tomorrow).toBe('📅 Zítra');
      expect(TIMELINE_TAB_LABELS.history).toBe('📈 Historie');
      expect(TIMELINE_TAB_LABELS.detail).toBe('💎 Detail');
    });
  });

  describe('loadTimelineTab', () => {
    const mockRawDayData = {
      date: '2024-01-15',
      mode_blocks: [
        {
          mode_historical: 'HOME I',
          mode_planned: 'HOME I',
          mode_match: true,
          status: 'completed',
          start_time: '06:00',
          end_time: '08:00',
          duration_hours: 2,
          cost_historical: 5.5,
          cost_planned: 5.5,
          cost_delta: 0,
          solar_total_kwh: 1.2,
          consumption_total_kwh: 2.5,
          grid_import_total_kwh: 1.3,
          grid_export_total_kwh: 0,
          interval_reasons: [{ time: '06:00', reason: 'Solar available' }],
        },
        {
          mode_historical: 'HOME II',
          mode_planned: 'HOME II',
          mode_match: true,
          status: 'current',
          start_time: '08:00',
          end_time: '10:00',
          duration_hours: 2,
          cost_historical: 8.2,
          cost_planned: 8.0,
          cost_delta: -0.2,
          solar_total_kwh: 0.8,
          consumption_total_kwh: 3.0,
          grid_import_total_kwh: 2.2,
          grid_export_total_kwh: 0.1,
          interval_reasons: [],
        },
      ],
      summary: {
        overall_adherence: 95.5,
        mode_switches: 3,
        total_cost: 25.5,
        metrics: {
          cost: { plan: 25.0, actual: 25.5, has_actual: true, unit: 'Kč' },
          solar: { plan: 5.0, actual: 5.2, has_actual: true, unit: 'kWh' },
          consumption: { plan: 12.0, actual: 12.5, has_actual: true, unit: 'kWh' },
          grid: { plan: 7.0, actual: 7.3, has_actual: true, unit: 'kWh' },
        },
        completed_summary: {
          count: 6,
          total_cost: 15.0,
          adherence_pct: 98.0,
        },
        planned_summary: {
          count: 4,
          total_cost: 10.0,
        },
        progress_pct: 60,
        actual_total_cost: 25.5,
        plan_total_cost: 25.0,
        vs_plan_pct: 2.0,
        eod_prediction: {
          predicted_total: 30.0,
          predicted_savings: 5.0,
        },
      },
      metadata: {
        active_plan: 'hybrid',
        comparison_plan_available: 'autonomy',
      },
      comparison: {
        plan: 'autonomy',
        mode_blocks: [
          {
            mode_historical: 'HOME I',
            mode_planned: 'HOME I',
            mode_match: true,
            status: 'completed',
            start_time: '06:00',
            end_time: '08:00',
            duration_hours: 2,
            cost_historical: 5.5,
            cost_planned: 5.5,
            cost_delta: 0,
            solar_total_kwh: 1.2,
            consumption_total_kwh: 2.5,
            grid_import_total_kwh: 1.3,
            grid_export_total_kwh: 0,
            interval_reasons: [],
          },
        ],
      },
    };

    it('should load and transform timeline tab data', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce({ today: mockRawDayData });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result).not.toBeNull();
      expect(result!.date).toBe('2024-01-15');
      expect(result!.modeBlocks).toHaveLength(2);
      expect(result!.modeBlocks[0].modeHistorical).toBe('HOME I');
      expect(result!.modeBlocks[0].status).toBe('completed');
      expect(result!.modeBlocks[0].durationHours).toBe(2);
      expect(result!.modeBlocks[0].solarKwh).toBe(1.2);
      expect(result!.modeBlocks[0].intervalReasons).toHaveLength(1);
    });

    it('should handle null API response', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce(null);

      const result = await loadTimelineTab('SN123', 'today');

      expect(result).toBeNull();
    });

    it('should handle API errors', async () => {
      mockLoadDetailTabs.mockRejectedValueOnce(new Error('Network error'));

      const result = await loadTimelineTab('SN123', 'today');

      expect(result).toBeNull();
    });

    it('should transform all mode block fields correctly', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce({ today: mockRawDayData });

      const result = await loadTimelineTab('SN123', 'today');

      const block = result!.modeBlocks[1];
      expect(block.modeHistorical).toBe('HOME II');
      expect(block.modePlanned).toBe('HOME II');
      expect(block.modeMatch).toBe(true);
      expect(block.status).toBe('current');
      expect(block.startTime).toBe('08:00');
      expect(block.endTime).toBe('10:00');
      expect(block.costHistorical).toBe(8.2);
      expect(block.costPlanned).toBe(8.0);
      expect(block.costDelta).toBe(-0.2);
      expect(block.consumptionKwh).toBe(3.0);
      expect(block.gridImportKwh).toBe(2.2);
      expect(block.gridExportKwh).toBe(0.1);
    });

    it('should transform summary correctly', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce({ today: mockRawDayData });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result!.summary.overallAdherence).toBe(95.5);
      expect(result!.summary.modeSwitches).toBe(3);
      expect(result!.summary.totalCost).toBe(25.5);
      expect(result!.summary.metrics.cost.plan).toBe(25.0);
      expect(result!.summary.metrics.cost.actual).toBe(25.5);
      expect(result!.summary.metrics.cost.hasActual).toBe(true);
      expect(result!.summary.completedSummary).toEqual({
        count: 6,
        totalCost: 15.0,
        adherencePct: 98.0,
      });
      expect(result!.summary.eodPrediction).toEqual({
        predictedTotal: 30.0,
        predictedSavings: 5.0,
      });
    });

    it('should transform metadata correctly', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce({ today: mockRawDayData });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result!.metadata?.activePlan).toBe('hybrid');
      expect(result!.metadata?.comparisonPlanAvailable).toBe('autonomy');
    });

    it('should transform comparison data correctly', async () => {
      mockLoadDetailTabs.mockResolvedValueOnce({ today: mockRawDayData });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result!.comparison?.plan).toBe('autonomy');
      expect(result!.comparison?.modeBlocks).toHaveLength(1);
    });

    it('should handle missing optional fields', async () => {
      const minimalData = {
        date: '2024-01-15',
        mode_blocks: [],
        summary: {
          overall_adherence: 0,
          mode_switches: 0,
          total_cost: 0,
          metrics: {},
        },
      };

      mockLoadDetailTabs.mockResolvedValueOnce({ today: minimalData });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result).not.toBeNull();
      expect(result!.modeBlocks).toEqual([]);
      expect(result!.metadata).toBeUndefined();
      expect(result!.comparison).toBeUndefined();
    });
  });

  describe('loadAllTimelineTabs', () => {
    const mockAllTabsData = {
      yesterday: { date: '2024-01-14', mode_blocks: [], summary: { overall_adherence: 90, mode_switches: 2, total_cost: 20, metrics: {} } },
      today: { date: '2024-01-15', mode_blocks: [], summary: { overall_adherence: 95, mode_switches: 3, total_cost: 25, metrics: {} } },
      tomorrow: { date: '2024-01-16', mode_blocks: [], summary: { overall_adherence: 0, mode_switches: 0, total_cost: 0, metrics: {} } },
      history: { date: '2024-01-01', mode_blocks: [], summary: { overall_adherence: 85, mode_switches: 5, total_cost: 100, metrics: {} } },
      detail: { date: '2024-01-15', mode_blocks: [], summary: { overall_adherence: 95, mode_switches: 3, total_cost: 25, metrics: {} } },
    };

    it('should load all timeline tabs', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockAllTabsData);

      const result = await loadAllTimelineTabs('SN123');

      expect(result.yesterday).not.toBeNull();
      expect(result.today).not.toBeNull();
      expect(result.tomorrow).not.toBeNull();
      expect(result.history).not.toBeNull();
      expect(result.detail).not.toBeNull();
      expect(result.yesterday!.date).toBe('2024-01-14');
      expect(result.today!.date).toBe('2024-01-15');
    });

    it('should use custom plan parameter', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(mockAllTabsData);

      await loadAllTimelineTabs('SN123', 'autonomy');

      expect(mockFetchOIGAPI).toHaveBeenCalledWith(
        '/battery_forecast/SN123/detail_tabs?plan=autonomy'
      );
    });

    it('should handle null API response', async () => {
      mockFetchOIGAPI.mockResolvedValueOnce(null);

      const result = await loadAllTimelineTabs('SN123');

      expect(result).toEqual({});
    });

    it('should handle API errors', async () => {
      mockFetchOIGAPI.mockRejectedValueOnce(new Error('Network error'));

      const result = await loadAllTimelineTabs('SN123');

      expect(result).toEqual({});
    });
  });

  describe('loadPlannerSettings', () => {
    it('should load planner settings', async () => {
      mockFetchSettings.mockResolvedValueOnce({
        auto_mode_switch_enabled: true,
        planner_mode: 'hybrid',
      });

      const result = await loadPlannerSettings('SN123');

      expect(result).not.toBeNull();
      expect(result!.autoModeSwitchEnabled).toBe(true);
      expect(result!.plannerMode).toBe('hybrid');
    });

    it('should handle null API response', async () => {
      mockFetchSettings.mockResolvedValueOnce(null);

      const result = await loadPlannerSettings('SN123');

      expect(result).toBeNull();
    });

    it('should handle API errors', async () => {
      mockFetchSettings.mockRejectedValueOnce(new Error('Network error'));

      const result = await loadPlannerSettings('SN123');

      expect(result).toBeNull();
    });

    it('should default autoModeSwitchEnabled to false', async () => {
      mockFetchSettings.mockResolvedValueOnce({});

      const result = await loadPlannerSettings('SN123');

      expect(result!.autoModeSwitchEnabled).toBe(false);
    });
  });

  describe('savePlannerSettings', () => {
    it('should save planner settings', async () => {
      mockSavePlannerSettings.mockResolvedValueOnce(undefined);

      const result = await savePlannerSettings('SN123', {
        autoModeSwitchEnabled: true,
        plannerMode: 'autonomy',
      });

      expect(result).toBe(true);
      expect(mockSavePlannerSettings).toHaveBeenCalledWith('SN123', {
        auto_mode_switch_enabled: true,
      });
      expect(mockInvalidate).toHaveBeenCalled();
    });

    it('should only send changed fields', async () => {
      mockSavePlannerSettings.mockResolvedValueOnce(undefined);

      await savePlannerSettings('SN123', { plannerMode: 'hybrid' });

      expect(mockSavePlannerSettings).toHaveBeenCalledWith('SN123', {});
    });

    it('should handle API errors', async () => {
      mockSavePlannerSettings.mockRejectedValueOnce(new Error('Save failed'));

      const result = await savePlannerSettings('SN123', {
        autoModeSwitchEnabled: true,
      });

      expect(result).toBe(false);
    });
  });

  describe('edge cases', () => {
    it('should handle mode blocks with null values', async () => {
      const dataWithNulls = {
        date: '2024-01-15',
        mode_blocks: [
          {
            mode_historical: null,
            mode_planned: undefined,
            mode_match: null,
            status: null,
            start_time: null,
            end_time: null,
            duration_hours: null,
            cost_historical: null,
            cost_planned: null,
            cost_delta: null,
            solar_total_kwh: null,
            consumption_total_kwh: null,
            grid_import_total_kwh: null,
            grid_export_total_kwh: null,
            interval_reasons: null,
          },
        ],
        summary: {
          overall_adherence: null,
          mode_switches: null,
          total_cost: null,
          metrics: null,
        },
      };

      mockLoadDetailTabs.mockResolvedValueOnce({ today: dataWithNulls });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result).not.toBeNull();
      expect(result!.modeBlocks[0].modeHistorical).toBe('');
      expect(result!.modeBlocks[0].status).toBe('planned');
      expect(result!.modeBlocks[0].durationHours).toBe(0);
      expect(result!.modeBlocks[0].solarKwh).toBe(0);
      expect(result!.modeBlocks[0].intervalReasons).toEqual([]);
      expect(result!.summary.overallAdherence).toBe(0);
    });

    it('should handle empty mode blocks array', async () => {
      const dataWithEmptyBlocks = {
        date: '2024-01-15',
        mode_blocks: [],
        summary: {
          overall_adherence: 100,
          mode_switches: 0,
          total_cost: 0,
          metrics: {},
        },
      };

      mockLoadDetailTabs.mockResolvedValueOnce({ today: dataWithEmptyBlocks });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result!.modeBlocks).toEqual([]);
    });

    it('should handle missing metrics', async () => {
      const dataWithMissingMetrics = {
        date: '2024-01-15',
        mode_blocks: [],
        summary: {
          overall_adherence: 100,
          mode_switches: 0,
          total_cost: 0,
        },
      };

      mockLoadDetailTabs.mockResolvedValueOnce({ today: dataWithMissingMetrics });

      const result = await loadTimelineTab('SN123', 'today');

      expect(result!.summary.metrics).toBeDefined();
      expect(result!.summary.metrics.cost).toBeDefined();
    });
  });
});
