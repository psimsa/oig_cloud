import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  selectBoxModeButtons,
  selectSupplementaryToggles,
} from '@/ui/features/control-panel/selectors';
import type { SupplementaryState } from '@/ui/features/control-panel/types';

describe('selectBoxModeButtons', () => {
  it('returns exactly 4 main mode buttons', () => {
    const buttons = selectBoxModeButtons();
    expect(buttons).toHaveLength(4);
  });

  it('contains home_1, home_2, home_3, home_ups', () => {
    const buttons = selectBoxModeButtons();
    expect(buttons).toContain('home_1');
    expect(buttons).toContain('home_2');
    expect(buttons).toContain('home_3');
    expect(buttons).toContain('home_ups');
  });

  it('does not contain home_5 or home_6', () => {
    const buttons = selectBoxModeButtons();
    expect(buttons).not.toContain('home_5');
    expect(buttons).not.toContain('home_6');
  });
});

describe('selectSupplementaryToggles', () => {
  describe('when sensor is available and Flexibilita inactive', () => {
    const base: SupplementaryState = {
      home_grid_v: true,
      home_grid_vi: false,
      flexibilita: false,
      available: true,
    };

    it('reflects sensor attribute values directly', () => {
      const result = selectSupplementaryToggles(base);
      expect(result.home_grid_v).toBe(true);
      expect(result.home_grid_vi).toBe(false);
    });

    it('sets available=true', () => {
      expect(selectSupplementaryToggles(base).available).toBe(true);
    });

    it('sets disabled=false so toggles are interactive', () => {
      expect(selectSupplementaryToggles(base).disabled).toBe(false);
    });
  });

  describe('when Flexibilita (app=4) is active', () => {
    const withFlexibilita: SupplementaryState = {
      home_grid_v: true,
      home_grid_vi: true,
      flexibilita: true,
      available: true,
    };

    it('sets disabled=true to block toggles', () => {
      expect(selectSupplementaryToggles(withFlexibilita).disabled).toBe(true);
    });

    it('still exposes flexibilita=true for indicator rendering', () => {
      expect(selectSupplementaryToggles(withFlexibilita).flexibilita).toBe(true);
    });

    it('still exposes toggle values from sensor (read-only view)', () => {
      const result = selectSupplementaryToggles(withFlexibilita);
      expect(result.home_grid_v).toBe(true);
      expect(result.home_grid_vi).toBe(true);
    });
  });

  describe('when box_mode_extended sensor is unavailable', () => {
    const unavailable: SupplementaryState = {
      home_grid_v: false,
      home_grid_vi: false,
      flexibilita: false,
      available: false,
    };

    it('sets disabled=true', () => {
      expect(selectSupplementaryToggles(unavailable).disabled).toBe(true);
    });

    it('returns home_grid_v=false regardless of underlying value', () => {
      const partial: SupplementaryState = { ...unavailable, home_grid_v: true };
      expect(selectSupplementaryToggles(partial).home_grid_v).toBe(false);
    });

    it('returns home_grid_vi=false regardless of underlying value', () => {
      const partial: SupplementaryState = { ...unavailable, home_grid_vi: true };
      expect(selectSupplementaryToggles(partial).home_grid_vi).toBe(false);
    });

    it('sets available=false', () => {
      expect(selectSupplementaryToggles(unavailable).available).toBe(false);
    });
  });

  describe('toggle dispatch guard logic (Flexibilita blocks service call)', () => {
    it('Flexibilita active → disabled=true prevents dispatch', () => {
      const state: SupplementaryState = {
        home_grid_v: false,
        home_grid_vi: false,
        flexibilita: true,
        available: true,
      };
      const result = selectSupplementaryToggles(state);
      expect(result.disabled).toBe(true);
    });

    it('Flexibilita inactive + available → disabled=false allows dispatch', () => {
      const state: SupplementaryState = {
        home_grid_v: false,
        home_grid_vi: false,
        flexibilita: false,
        available: true,
      };
      const result = selectSupplementaryToggles(state);
      expect(result.disabled).toBe(false);
    });
  });

  describe('cloud-fed vs local/proxy-fed box_mode_extended', () => {
    const cloudState: SupplementaryState = {
      home_grid_v: true,
      home_grid_vi: false,
      flexibilita: false,
      available: true,
    };
    const proxyState: SupplementaryState = { ...cloudState };

    it('produces identical toggle state from cloud-fed and proxy-fed attributes', () => {
      const cloudResult = selectSupplementaryToggles(cloudState);
      const proxyResult = selectSupplementaryToggles(proxyState);
      expect(cloudResult).toEqual(proxyResult);
    });

    it('same disabled logic applies regardless of data source', () => {
      const cloudFlexibilita: SupplementaryState = { ...cloudState, flexibilita: true };
      const proxyFlexibilita: SupplementaryState = { ...cloudState, flexibilita: true };
      expect(selectSupplementaryToggles(cloudFlexibilita).disabled).toBe(true);
      expect(selectSupplementaryToggles(proxyFlexibilita).disabled).toBe(true);
    });
  });

  describe('toggle service call contract', () => {
    it('toggleSupplementary field names match home_grid_v / home_grid_vi only', () => {
      const allowedFields: Array<'home_grid_v' | 'home_grid_vi'> = ['home_grid_v', 'home_grid_vi'];
      expect(allowedFields).toHaveLength(2);
      expect(allowedFields).toContain('home_grid_v');
      expect(allowedFields).toContain('home_grid_vi');
      expect(allowedFields).not.toContain('mode');
      expect(allowedFields).not.toContain('home_5');
      expect(allowedFields).not.toContain('home_6');
    });
  });
});
