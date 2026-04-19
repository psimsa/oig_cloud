import { describe, it, expect } from 'vitest';
import {
  BoxMode,
  GridDelivery,
  ShieldQueueItem,
  BatteryChargeParams,
  BOX_MODE_LABELS,
  BOX_MODE_SERVICE_MAP,
  GRID_DELIVERY_LABELS,
  GRID_DELIVERY_SERVICE_MAP,
  BOILER_MODE_LABELS,
  BOILER_MODE_SERVICE_MAP,
  QUEUE_STATUS_COLORS,
  SupplementaryState,
  EMPTY_SHIELD_STATE,
} from '@/ui/features/control-panel/types';

describe('Control Panel types', () => {
  describe('BOX_MODE_LABELS', () => {
    it('should have labels for all 4 main modes', () => {
      expect(BOX_MODE_LABELS.home_1).toBe('Home 1');
      expect(BOX_MODE_LABELS.home_2).toBe('Home 2');
      expect(BOX_MODE_LABELS.home_3).toBe('Home 3');
      expect(BOX_MODE_LABELS.home_ups).toBe('Home UPS');
    });

    it('should have exactly 4 modes (home_5 / home_6 removed)', () => {
      expect(Object.keys(BOX_MODE_LABELS)).toHaveLength(4);
    });

    it('should not contain home_5 or home_6', () => {
      expect(Object.keys(BOX_MODE_LABELS)).not.toContain('home_5');
      expect(Object.keys(BOX_MODE_LABELS)).not.toContain('home_6');
    });
  });

  describe('BOX_MODE_SERVICE_MAP', () => {
    it('should send canonical machine values (not labels)', () => {
      expect(BOX_MODE_SERVICE_MAP.home_1).toBe('home_1');
      expect(BOX_MODE_SERVICE_MAP.home_2).toBe('home_2');
      expect(BOX_MODE_SERVICE_MAP.home_3).toBe('home_3');
      expect(BOX_MODE_SERVICE_MAP.home_ups).toBe('home_ups');
    });

    it('should not send human-readable labels as service values', () => {
      Object.values(BOX_MODE_SERVICE_MAP).forEach(value => {
        expect(value).not.toContain(' ');
        expect(value).not.toMatch(/^Home \d/);
      });
    });

    it('should not contain home_5 or home_6 entries', () => {
      const keys = Object.keys(BOX_MODE_SERVICE_MAP);
      expect(keys).not.toContain('home_5');
      expect(keys).not.toContain('home_6');
    });
  });

  describe('GRID_DELIVERY_SERVICE_MAP', () => {
    it('should send canonical machine values (not labels)', () => {
      expect(GRID_DELIVERY_SERVICE_MAP.off).toBe('off');
      expect(GRID_DELIVERY_SERVICE_MAP.on).toBe('on');
      expect(GRID_DELIVERY_SERVICE_MAP.limited).toBe('limited');
    });

    it('should not send bilingual label strings as service values', () => {
      Object.values(GRID_DELIVERY_SERVICE_MAP).forEach(value => {
        expect(value).not.toContain('/');
        expect(value).not.toContain('Vypnuto');
      });
    });
  });

  describe('BOILER_MODE_SERVICE_MAP', () => {
    it('should send canonical machine values (not labels)', () => {
      expect(BOILER_MODE_SERVICE_MAP.cbb).toBe('cbb');
      expect(BOILER_MODE_SERVICE_MAP.manual).toBe('manual');
    });

    it('should not send legacy uppercase values as service values', () => {
      (Object.values(BOILER_MODE_SERVICE_MAP) as string[]).forEach(value => {
        expect(value).toBe(value.toLowerCase());
      });
    });
  });
  describe('GRID_DELIVERY_LABELS', () => {
    it('should have labels for all options', () => {
      expect(GRID_DELIVERY_LABELS.off).toBe('Vypnuto');
      expect(GRID_DELIVERY_LABELS.on).toBe('Zapnuto');
      expect(GRID_DELIVERY_LABELS.limited).toBe('S omezením');
    });

    it('should have 3 options', () => {
      expect(Object.keys(GRID_DELIVERY_LABELS)).toHaveLength(3);
    });
  });

  describe('QUEUE_STATUS_COLORS', () => {
    it('should have colors for all statuses', () => {
      expect(QUEUE_STATUS_COLORS.queued).toBeDefined();
      expect(QUEUE_STATUS_COLORS.running).toBeDefined();
    });

    it('should use hex colors', () => {
      Object.values(QUEUE_STATUS_COLORS).forEach(color => {
        expect(color).toMatch(/^#[0-9a-f]{6}$/i);
      });
    });
  });

  describe('ShieldQueueItem', () => {
    it('should have required properties', () => {
      const item: ShieldQueueItem = {
        id: '123',
        type: 'mode_change',
        status: 'queued',
        service: 'set_box_mode',
        targetValue: 'Home 2',
        changes: ['mode'],
        createdAt: '2024-01-15T14:00:00',
        position: 1,
      };

      expect(item.id).toBe('123');
      expect(item.type).toBe('mode_change');
      expect(item.status).toBe('queued');
    });

    it('should support all item types', () => {
      const types: ShieldQueueItem['type'][] = [
        'mode_change',
        'grid_delivery',
        'grid_limit',
        'boiler_mode',
        'battery_formating',
      ];

      expect(types).toHaveLength(5);
    });

    it('should support all statuses', () => {
      const statuses: ShieldQueueItem['status'][] = [
        'queued',
        'running',
      ];

      expect(statuses).toHaveLength(2);
    });
  });

  describe('BatteryChargeParams', () => {
    it('should have required properties', () => {
      const params: BatteryChargeParams = {
        targetSoc: 80,
        estimatedCost: 25.50,
        estimatedTime: 3600,
      };

      expect(params.targetSoc).toBe(80);
      expect(params.estimatedCost).toBe(25.50);
      expect(params.estimatedTime).toBe(3600);
    });
  });

  describe('SupplementaryState', () => {
    it('should have all required fields', () => {
      const state: SupplementaryState = {
        home_grid_v: true,
        home_grid_vi: false,
        flexibilita: false,
        available: true,
      };

      expect(state.home_grid_v).toBe(true);
      expect(state.home_grid_vi).toBe(false);
      expect(state.flexibilita).toBe(false);
      expect(state.available).toBe(true);
    });
  });

  describe('EMPTY_SHIELD_STATE', () => {
    it('should include supplementary field with all toggles off', () => {
      expect(EMPTY_SHIELD_STATE.supplementary).toBeDefined();
      expect(EMPTY_SHIELD_STATE.supplementary.home_grid_v).toBe(false);
      expect(EMPTY_SHIELD_STATE.supplementary.home_grid_vi).toBe(false);
      expect(EMPTY_SHIELD_STATE.supplementary.flexibilita).toBe(false);
      expect(EMPTY_SHIELD_STATE.supplementary.available).toBe(false);
    });
  });
});

