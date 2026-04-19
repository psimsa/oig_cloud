import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchTimeline,
  invalidateTimelineCache,
  buildModeSegments,
  loadPricingData,
} from '@/data/pricing-data';
import { haClient } from '@/data/ha-client';
import { EMPTY_PRICING_DATA } from '@/ui/features/pricing/types';

vi.mock('@/data/ha-client', () => ({
  haClient: {
    getHass: vi.fn(),
    fetchOIGAPI: vi.fn(),
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

describe('pricing-data', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-15T12:00:00Z'));
    invalidateTimelineCache();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('fetchTimeline', () => {
    it('should fetch timeline from API', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 },
        { timestamp: '2025-01-15T12:15:00', spot_price_czk: 5.8 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      const result = await fetchTimeline('hybrid');

      expect(result).toEqual(mockTimeline);
      expect(haClient.getHass).toHaveBeenCalled();
    });

    it('should use fallback fetchOIGAPI when callApi not available', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: undefined,
      } as any);
      vi.mocked(haClient.fetchOIGAPI).mockResolvedValue({ active: mockTimeline });

      const result = await fetchTimeline('hybrid');

      expect(result).toEqual(mockTimeline);
      expect(haClient.fetchOIGAPI).toHaveBeenCalled();
    });

    it('should return cached data within TTL', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      await fetchTimeline('hybrid');
      await fetchTimeline('hybrid');

      expect(haClient.getHass).toHaveBeenCalledTimes(1);
    });

    it('should refetch after cache TTL expires', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      await fetchTimeline('hybrid');

      vi.advanceTimersByTime(6 * 60 * 1000);

      await fetchTimeline('hybrid');

      expect(haClient.getHass).toHaveBeenCalledTimes(2);
    });

    it('should return empty array when hass is null', async () => {
      vi.mocked(haClient.getHass).mockResolvedValue(null);

      const result = await fetchTimeline('hybrid');

      expect(result).toEqual([]);
    });

    it('should handle API errors gracefully', async () => {
      vi.mocked(haClient.getHass).mockRejectedValue(new Error('Network error'));

      const result = await fetchTimeline('hybrid');

      expect(result).toEqual([]);
    });

    it('should extract timeline from data.timeline when active not present', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ timeline: mockTimeline }),
      } as any);

      const result = await fetchTimeline('hybrid');

      expect(result).toEqual(mockTimeline);
    });
  });

  describe('invalidateTimelineCache', () => {
    it('should invalidate specific plan cache', async () => {
      const mockTimeline = [{ timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 }];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      await fetchTimeline('hybrid');
      invalidateTimelineCache('hybrid');
      await fetchTimeline('hybrid');

      expect(haClient.getHass).toHaveBeenCalledTimes(2);
    });

    it('should invalidate all caches when no plan specified', async () => {
      const mockTimeline = [{ timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.5 }];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      await fetchTimeline('hybrid');
      await fetchTimeline('autonomy');
      invalidateTimelineCache();
      await fetchTimeline('hybrid');
      await fetchTimeline('autonomy');

      expect(haClient.getHass).toHaveBeenCalledTimes(4);
    });
  });

  describe('buildModeSegments', () => {
    it('should return empty array for empty timeline', () => {
      const result = buildModeSegments([]);
      expect(result).toEqual([]);
    });

    it('should build segments from timeline points', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:15:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:30:00', mode_name: 'HOME II' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result).toHaveLength(2);
      expect(result[0].mode).toBe('HOME I');
      expect(result[1].mode).toBe('HOME II');
      expect(result[0].icon).toBe('🏠');
      expect(result[1].icon).toBe('⚡');
    });

    it('should merge consecutive same modes', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:15:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:30:00', mode_name: 'HOME I' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result).toHaveLength(1);
      expect(result[0].mode).toBe('HOME I');
    });

    it('should handle mode_planned fallback', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_planned: 'HOME II' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result).toHaveLength(1);
      expect(result[0].mode).toBe('HOME II');
    });

    it('should skip points with no mode', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:15:00' },
        { timestamp: '2025-01-15T12:30:00', mode_name: 'HOME II' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result).toHaveLength(2);
    });

    it('should generate short labels correctly', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_name: 'HOME I' },
        { timestamp: '2025-01-15T12:15:00', mode_name: 'FULL HOME UPS' },
        { timestamp: '2025-01-15T12:30:00', mode_name: 'DO NOTHING' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result[0].shortLabel).toBe('I');
      expect(result[1].shortLabel).toBe('UPS');
      expect(result[2].shortLabel).toBe('DN');
    });

    it('should use unknown icon for unrecognized modes', () => {
      const timeline = [
        { timestamp: '2025-01-15T12:00:00', mode_name: 'UNKNOWN MODE' },
      ];

      const result = buildModeSegments(timeline as any);

      expect(result[0].icon).toBe('❓');
    });
  });

  describe('loadPricingData', () => {
    it('should return EMPTY_PRICING_DATA when no timeline', async () => {
      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: [] }),
      } as any);

      const result = await loadPricingData({}, 'hybrid');

      expect(result).toEqual(EMPTY_PRICING_DATA);
    });

    it('should load complete pricing data', async () => {
      const mockTimeline = [
        {
          timestamp: '2025-01-15T12:00:00',
          spot_price_czk: 5.5,
          export_price_czk: 3.0,
          battery_capacity_kwh: 10,
          solar_charge_kwh: 0.5,
          grid_charge_kwh: 0.2,
          grid_net: 0.1,
          load_kwh: 0.3,
          mode_name: 'HOME I',
        },
        {
          timestamp: '2025-01-15T12:15:00',
          spot_price_czk: 5.8,
          export_price_czk: 3.2,
          battery_capacity_kwh: 10.2,
          solar_charge_kwh: 0.3,
          grid_charge_kwh: 0.1,
          grid_net: -0.1,
          load_kwh: 0.25,
          mode_name: 'HOME I',
        },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      const mockHass = {
        states: {
          'sensor.oig_2206237016_spot_price_current_15min': { state: '5.6' },
          'sensor.oig_2206237016_export_price_current_15min': { state: '3.1' },
          'sensor.oig_2206237016_battery_forecast': {
            state: 'on',
            attributes: {
              planned_consumption_today: 5.5,
              planned_consumption_tomorrow: 6.0,
              profile_today: 'Standard',
              mode_optimization: {
                total_cost_czk: 100,
                total_savings_vs_home_i_czk: 20,
                alternatives: {},
              },
            },
          },
          'sensor.oig_2206237016_ac_out_en_day': { state: '1000' },
          'sensor.oig_2206237016_solar_forecast': {
            attributes: {
              today_total_kwh: 15,
              today_hourly_string1_kw: { '2025-01-15T12:00:00': 2.5 },
              today_hourly_string2_kw: { '2025-01-15T12:00:00': 1.5 },
            },
          },
        },
      };

      const result = await loadPricingData(mockHass as any, 'hybrid');

      expect(result.timeline).toHaveLength(2);
      expect(result.prices).toHaveLength(2);
      expect(result.exportPrices).toHaveLength(2);
      expect(result.modeSegments).toHaveLength(1);
      expect(result.battery).toBeDefined();
      expect(result.solar).toBeDefined();
      expect(result.plannedConsumption).toBeDefined();
      expect(result.whatIf).toBeDefined();
    });

    it('should find cheapest and most expensive buy blocks', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 3.0 },
        { timestamp: '2025-01-15T12:15:00', spot_price_czk: 3.2 },
        { timestamp: '2025-01-15T12:30:00', spot_price_czk: 3.1 },
        { timestamp: '2025-01-15T12:45:00', spot_price_czk: 3.0 },
        { timestamp: '2025-01-15T13:00:00', spot_price_czk: 3.2 },
        { timestamp: '2025-01-15T13:15:00', spot_price_czk: 3.1 },
        { timestamp: '2025-01-15T13:30:00', spot_price_czk: 3.0 },
        { timestamp: '2025-01-15T13:45:00', spot_price_czk: 3.2 },
        { timestamp: '2025-01-15T14:00:00', spot_price_czk: 3.1 },
        { timestamp: '2025-01-15T14:15:00', spot_price_czk: 3.0 },
        { timestamp: '2025-01-15T14:30:00', spot_price_czk: 3.2 },
        { timestamp: '2025-01-15T14:45:00', spot_price_czk: 3.1 },
        { timestamp: '2025-01-15T15:00:00', spot_price_czk: 8.0 },
        { timestamp: '2025-01-15T15:15:00', spot_price_czk: 8.5 },
        { timestamp: '2025-01-15T15:30:00', spot_price_czk: 8.2 },
        { timestamp: '2025-01-15T15:45:00', spot_price_czk: 7.9 },
        { timestamp: '2025-01-15T16:00:00', spot_price_czk: 8.1 },
        { timestamp: '2025-01-15T16:15:00', spot_price_czk: 8.3 },
        { timestamp: '2025-01-15T16:30:00', spot_price_czk: 8.4 },
        { timestamp: '2025-01-15T16:45:00', spot_price_czk: 8.2 },
        { timestamp: '2025-01-15T17:00:00', spot_price_czk: 8.0 },
        { timestamp: '2025-01-15T17:15:00', spot_price_czk: 8.1 },
        { timestamp: '2025-01-15T17:30:00', spot_price_czk: 8.2 },
        { timestamp: '2025-01-15T17:45:00', spot_price_czk: 8.0 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      const mockHass = {
        states: {
          'sensor.oig_2206237016_spot_price_current_15min': { state: '8.0' },
          'sensor.oig_2206237016_export_price_current_15min': { state: '3.0' },
          'sensor.oig_2206237016_battery_forecast': {
            state: 'unavailable',
            attributes: {},
          },
          'sensor.oig_2206237016_ac_out_en_day': { state: 'unavailable' },
          'sensor.oig_2206237016_solar_forecast': { attributes: {} },
        },
      };

      const result = await loadPricingData(mockHass as any, 'hybrid');

      expect(result.cheapestBuyBlock).not.toBeNull();
      expect(result.expensiveBuyBlock).not.toBeNull();
      expect(result.cheapestBuyBlock?.type).toBe('cheapest-buy');
      expect(result.expensiveBuyBlock?.type).toBe('expensive-buy');
      expect(result.cheapestBuyBlock?.avg).toBeLessThan(result.expensiveBuyBlock?.avg || Infinity);
    });

    it('should handle errors gracefully', async () => {
      vi.mocked(haClient.getHass).mockRejectedValue(new Error('API Error'));

      const result = await loadPricingData({}, 'hybrid');

      expect(result).toEqual(EMPTY_PRICING_DATA);
    });

    it('should calculate average spot price', async () => {
      const mockTimeline = [
        { timestamp: '2025-01-15T12:00:00', spot_price_czk: 5.0 },
        { timestamp: '2025-01-15T12:15:00', spot_price_czk: 7.0 },
        { timestamp: '2025-01-15T12:30:00', spot_price_czk: 9.0 },
      ];

      vi.mocked(haClient.getHass).mockResolvedValue({
        callApi: vi.fn().mockResolvedValue({ active: mockTimeline }),
      } as any);

      const mockHass = {
        states: {
          'sensor.oig_2206237016_spot_price_current_15min': { state: '6.0' },
          'sensor.oig_2206237016_export_price_current_15min': { state: '3.0' },
          'sensor.oig_2206237016_battery_forecast': {
            state: 'unavailable',
            attributes: {},
          },
          'sensor.oig_2206237016_ac_out_en_day': { state: 'unavailable' },
          'sensor.oig_2206237016_solar_forecast': { attributes: {} },
        },
      };

      const result = await loadPricingData(mockHass as any, 'hybrid');

      expect(result.avgSpotPrice).toBe(7.0);
    });
  });
});
