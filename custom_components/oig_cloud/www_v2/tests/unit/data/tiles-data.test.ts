import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockCallWS = vi.fn();
const mockCallService = vi.fn();
const mockGet = vi.fn();

vi.mock('../../../src/data/ha-client', () => ({
  haClient: {
    callWS: (...args: unknown[]) => mockCallWS(...args),
    callService: (...args: unknown[]) => mockCallService(...args),
  },
}));

vi.mock('../../../src/data/entity-store', () => ({
  getEntityStore: () => ({
    get: (id: string) => mockGet(id),
  }),
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
  DEFAULT_TILES_CONFIG,
  loadTilesConfig,
  saveTilesConfig,
  resolveTiles,
  executeTileAction,
  getTileEntityIds,
  type TileConfig,
  type TilesConfig,
} from '../../../src/data/tiles-data';

describe('tiles-data', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('DEFAULT_TILES_CONFIG', () => {
    it('should have correct default values', () => {
      expect(DEFAULT_TILES_CONFIG.tiles_left).toHaveLength(6);
      expect(DEFAULT_TILES_CONFIG.tiles_right).toHaveLength(6);
      expect(DEFAULT_TILES_CONFIG.left_count).toBe(4);
      expect(DEFAULT_TILES_CONFIG.right_count).toBe(4);
      expect(DEFAULT_TILES_CONFIG.visible).toBe(true);
      expect(DEFAULT_TILES_CONFIG.version).toBe(1);
    });

    it('should have null placeholders in tile arrays', () => {
      expect(DEFAULT_TILES_CONFIG.tiles_left.every(t => t === null)).toBe(true);
      expect(DEFAULT_TILES_CONFIG.tiles_right.every(t => t === null)).toBe(true);
    });
  });

  describe('loadTilesConfig', () => {
    it('should load config from HA WebSocket', async () => {
      const haConfig: TilesConfig = {
        tiles_left: [
          { type: 'entity', entity_id: 'sensor.temp', label: 'Temperature' },
          null,
          null,
          null,
        ],
        tiles_right: [null, null, null, null],
        left_count: 4,
        right_count: 4,
        visible: true,
        version: 1,
      };

      mockCallWS.mockResolvedValueOnce({
        response: { config: haConfig },
      });

      const result = await loadTilesConfig();

      expect(result.tiles_left).toHaveLength(4);
      expect(result.tiles_left[0]).toEqual(haConfig.tiles_left[0]);
      expect(result.visible).toBe(true);
      expect(mockCallWS).toHaveBeenCalledWith({
        type: 'call_service',
        domain: 'oig_cloud',
        service: 'get_dashboard_tiles',
        service_data: {},
        return_response: true,
      });
    });

    it('should fall back to localStorage when HA fails', async () => {
      const storedConfig: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.humidity', label: 'Humidity' }],
        tiles_right: [],
        left_count: 2,
        right_count: 2,
        visible: false,
        version: 1,
      };

      mockCallWS.mockRejectedValueOnce(new Error('WS failed'));
      localStorage.setItem('oig_dashboard_tiles', JSON.stringify(storedConfig));

      const result = await loadTilesConfig();

      expect(result.left_count).toBe(2);
      expect(result.visible).toBe(false);
      expect(result.tiles_left[0]).toEqual(storedConfig.tiles_left[0]);
    });

    it('should return default config when no sources available', async () => {
      mockCallWS.mockRejectedValueOnce(new Error('WS failed'));

      const result = await loadTilesConfig();

      expect(result).toEqual(DEFAULT_TILES_CONFIG);
    });

    it('should handle malformed localStorage data', async () => {
      mockCallWS.mockRejectedValueOnce(new Error('WS failed'));
      localStorage.setItem('oig_dashboard_tiles', 'invalid json');

      const result = await loadTilesConfig();

      expect(result).toEqual(DEFAULT_TILES_CONFIG);
    });

    it('should normalize config with missing fields', async () => {
      const partialConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.test' }],
        left_count: 1,
      };

      mockCallWS.mockResolvedValueOnce({
        response: { config: partialConfig },
      });

      const result = await loadTilesConfig();

      expect(result.tiles_left).toHaveLength(1);
      expect(result.tiles_right).toHaveLength(6);
      expect(result.left_count).toBe(1);
      expect(result.right_count).toBe(4);
      expect(result.visible).toBe(true);
    });

    it('should cap tile arrays at 6 items', async () => {
      const oversizedConfig: TilesConfig = {
        tiles_left: Array(10).fill({ type: 'entity', entity_id: 'sensor.test' }),
        tiles_right: Array(10).fill({ type: 'entity', entity_id: 'sensor.test2' }),
        left_count: 10,
        right_count: 10,
        visible: true,
        version: 1,
      };

      mockCallWS.mockResolvedValueOnce({
        response: { config: oversizedConfig },
      });

      const result = await loadTilesConfig();

      expect(result.tiles_left).toHaveLength(6);
      expect(result.tiles_right).toHaveLength(6);
    });
  });

  describe('saveTilesConfig', () => {
    it('should save config to HA and localStorage', async () => {
      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.temp', label: 'Temp' }],
        tiles_right: [],
        left_count: 2,
        right_count: 2,
        visible: true,
        version: 1,
      };

      mockCallService.mockResolvedValueOnce(true);

      const result = await saveTilesConfig(config);

      expect(result).toBe(true);
      expect(localStorage.getItem('oig_dashboard_tiles')).toBe(JSON.stringify(config));
      expect(mockCallService).toHaveBeenCalledWith('oig_cloud', 'save_dashboard_tiles', {
        config: JSON.stringify(config),
      });
    });

    it('should return false on save failure', async () => {
      const config: TilesConfig = DEFAULT_TILES_CONFIG;

      mockCallService.mockRejectedValueOnce(new Error('Save failed'));

      const result = await saveTilesConfig(config);

      expect(result).toBe(false);
    });
  });

  describe('resolveTiles', () => {
    const createMockEntity = (state: string, unit?: string, attributes?: Record<string, unknown>) => ({
      entity_id: `sensor.${state}`,
      state,
      attributes: { unit_of_measurement: unit, ...attributes },
    });

    beforeEach(() => {
      mockGet.mockImplementation((id: string) => {
        if (id === 'sensor.temp') return createMockEntity('22.5', '°C');
        if (id === 'sensor.power') return createMockEntity('500', 'W');
        if (id === 'sensor.energy') return createMockEntity('500', 'Wh');
        if (id === 'switch.light') return { entity_id: 'switch.light', state: 'on', attributes: {} };
        if (id === 'binary_sensor.motion') return { entity_id: 'binary_sensor.motion', state: 'off', attributes: {} };
        return null;
      });
    });

    it('should resolve entity tiles with numeric values', () => {
      const config: TilesConfig = {
        tiles_left: [
          { type: 'entity', entity_id: 'sensor.temp', label: 'Temperature' },
          { type: 'entity', entity_id: 'sensor.power', label: 'Power' },
        ],
        tiles_right: [],
        left_count: 2,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left).toHaveLength(2);
      expect(result.left[0].value).toBe('22.5');
      expect(result.left[0].unit).toBe('°C');
      expect(result.left[0].isActive).toBe(true);
      expect(result.left[1].value).toBe('500');
      expect(result.left[1].unit).toBe('W');
    });

    it('should format power values in kW when >= 1000', () => {
      mockGet.mockImplementation((id: string) => {
        if (id === 'sensor.high_power') return createMockEntity('2500', 'W');
        if (id === 'sensor.high_energy') return createMockEntity('3500', 'Wh');
        return null;
      });

      const config: TilesConfig = {
        tiles_left: [
          { type: 'entity', entity_id: 'sensor.high_power', label: 'High Power' },
          { type: 'entity', entity_id: 'sensor.high_energy', label: 'High Energy' },
        ],
        tiles_right: [],
        left_count: 2,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].value).toBe('2.50');
      expect(result.left[0].unit).toBe('kW');
      expect(result.left[1].value).toBe('3.50');
      expect(result.left[1].unit).toBe('kWh');
    });

    it('should handle switch entities', () => {
      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'switch.light', label: 'Light' }],
        tiles_right: [],
        left_count: 1,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].value).toBe('Zapnuto');
      expect(result.left[0].isActive).toBe(true);
      expect(result.left[0].unit).toBe('');
    });

    it('should handle binary_sensor entities', () => {
      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'binary_sensor.motion', label: 'Motion' }],
        tiles_right: [],
        left_count: 1,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].value).toBe('Vypnuto');
      expect(result.left[0].isActive).toBe(false);
    });

    it('should handle unavailable entities', () => {
      mockGet.mockImplementation(() => ({ entity_id: 'sensor.unavailable', state: 'unavailable', attributes: {} }));

      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.unavailable', label: 'Unavailable' }],
        tiles_right: [],
        left_count: 1,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].value).toBe('--');
      expect(result.left[0].isActive).toBe(false);
    });

    it('should handle missing entities', () => {
      mockGet.mockImplementation(() => null);

      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.missing', label: 'Missing' }],
        tiles_right: [],
        left_count: 1,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].value).toBe('--');
      expect(result.left[0].isActive).toBe(false);
    });

    it('should resolve support entities', () => {
      mockGet.mockImplementation((id: string) => {
        if (id === 'sensor.main') return createMockEntity('100', 'W');
        if (id === 'sensor.top') return createMockEntity('50', 'W');
        if (id === 'sensor.bottom') return createMockEntity('25', '%');
        return null;
      });

      const config: TilesConfig = {
        tiles_left: [
          {
            type: 'entity',
            entity_id: 'sensor.main',
            label: 'Main',
            support_entities: {
              top_right: 'sensor.top',
              bottom_right: 'sensor.bottom',
            },
          },
        ],
        tiles_right: [],
        left_count: 1,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left[0].supportValues.topRight).toEqual({ value: '50', unit: 'W' });
      expect(result.left[0].supportValues.bottomRight).toEqual({ value: '25.0', unit: '%' });
    });

    it('should skip null tiles', () => {
      const config: TilesConfig = {
        tiles_left: [null, { type: 'entity', entity_id: 'sensor.temp', label: 'Temp' }],
        tiles_right: [],
        left_count: 2,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = resolveTiles(config);

      expect(result.left).toHaveLength(1);
      expect(result.left[0].config.entity_id).toBe('sensor.temp');
    });

    it('should respect count limits', () => {
      const config: TilesConfig = {
        tiles_left: [
          { type: 'entity', entity_id: 'sensor.1', label: '1' },
          { type: 'entity', entity_id: 'sensor.2', label: '2' },
          { type: 'entity', entity_id: 'sensor.3', label: '3' },
          { type: 'entity', entity_id: 'sensor.4', label: '4' },
          { type: 'entity', entity_id: 'sensor.5', label: '5' },
        ],
        tiles_right: [],
        left_count: 3,
        right_count: 0,
        visible: true,
        version: 1,
      };

      mockGet.mockImplementation((id: string) => createMockEntity('10', 'W'));

      const result = resolveTiles(config);

      expect(result.left).toHaveLength(3);
    });
  });

  describe('executeTileAction', () => {
    it('should toggle switch entity', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await executeTileAction('switch.light', 'toggle');

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('switch', 'toggle', { entity_id: 'switch.light' });
    });

    it('should turn on entity', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await executeTileAction('switch.light', 'turn_on');

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('switch', 'turn_on', { entity_id: 'switch.light' });
    });

    it('should default to toggle when no action specified', async () => {
      mockCallService.mockResolvedValueOnce(true);

      const result = await executeTileAction('switch.light');

      expect(result).toBe(true);
      expect(mockCallService).toHaveBeenCalledWith('switch', 'toggle', { entity_id: 'switch.light' });
    });

    it('should propagate service call errors', async () => {
      mockCallService.mockRejectedValueOnce(new Error('Service failed'));

      await expect(executeTileAction('switch.light', 'toggle')).rejects.toThrow('Service failed');
    });
  });

  describe('getTileEntityIds', () => {
    it('should collect all entity IDs from tiles', () => {
      const config: TilesConfig = {
        tiles_left: [
          {
            type: 'entity',
            entity_id: 'sensor.main',
            support_entities: {
              top_right: 'sensor.top',
              bottom_right: 'sensor.bottom',
            },
          },
        ],
        tiles_right: [{ type: 'entity', entity_id: 'sensor.right' }],
        left_count: 1,
        right_count: 1,
        visible: true,
        version: 1,
      };

      const result = getTileEntityIds(config);

      expect(result).toContain('sensor.main');
      expect(result).toContain('sensor.top');
      expect(result).toContain('sensor.bottom');
      expect(result).toContain('sensor.right');
      expect(result).toHaveLength(4);
    });

    it('should deduplicate entity IDs', () => {
      const config: TilesConfig = {
        tiles_left: [{ type: 'entity', entity_id: 'sensor.shared' }],
        tiles_right: [{ type: 'entity', entity_id: 'sensor.shared' }],
        left_count: 1,
        right_count: 1,
        visible: true,
        version: 1,
      };

      const result = getTileEntityIds(config);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe('sensor.shared');
    });

    it('should skip null tiles', () => {
      const config: TilesConfig = {
        tiles_left: [null, { type: 'entity', entity_id: 'sensor.temp' }],
        tiles_right: [null],
        left_count: 2,
        right_count: 1,
        visible: true,
        version: 1,
      };

      const result = getTileEntityIds(config);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe('sensor.temp');
    });

    it('should respect count limits', () => {
      const config: TilesConfig = {
        tiles_left: [
          { type: 'entity', entity_id: 'sensor.1' },
          { type: 'entity', entity_id: 'sensor.2' },
          { type: 'entity', entity_id: 'sensor.3' },
        ],
        tiles_right: [],
        left_count: 2,
        right_count: 0,
        visible: true,
        version: 1,
      };

      const result = getTileEntityIds(config);

      expect(result).toHaveLength(2);
      expect(result).toContain('sensor.1');
      expect(result).toContain('sensor.2');
      expect(result).not.toContain('sensor.3');
    });
  });
});
