import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { OigShieldQueue } from '@/ui/features/control-panel/queue';
import type { ShieldQueueItem } from '@/ui/features/control-panel/types';

describe('OigShieldQueue', () => {
  let element: OigShieldQueue;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-15T14:30:00Z'));
    element = new OigShieldQueue();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('properties', () => {
    it('should have default items as empty array', () => {
      expect(element.items).toEqual([]);
    });

    it('should have default expanded as false', () => {
      expect(element.expanded).toBe(false);
    });

    it('should have default shieldStatus as idle', () => {
      expect(element.shieldStatus).toBe('idle');
    });

    it('should have default queueCount as 0', () => {
      expect(element.queueCount).toBe(0);
    });

    it('should accept items array', () => {
      const items: ShieldQueueItem[] = [
        {
          id: '1',
          type: 'mode_change',
          status: 'queued',
          service: 'set_box_mode',
          targetValue: 'home_1',
          changes: ["mode: 'home_2' → 'home_1'"],
          createdAt: '2024-01-15T14:00:00Z',
          position: 1,
        },
      ];
      element.items = items;
      expect(element.items).toEqual(items);
    });

    it('should accept expanded state', () => {
      element.expanded = true;
      expect(element.expanded).toBe(true);
    });

    it('should accept shieldStatus running', () => {
      element.shieldStatus = 'running';
      expect(element.shieldStatus).toBe('running');
    });

    it('should accept queueCount', () => {
      element.queueCount = 5;
      expect(element.queueCount).toBe(5);
    });
  });

  describe('activeCount getter', () => {
    it('should return 0 for empty items', () => {
      expect(element.activeCount).toBe(0);
    });

    it('should return correct count for items', () => {
      element.items = [
        { id: '1', type: 'mode_change', status: 'queued', service: 'set_box_mode', targetValue: 'home_1', changes: [], createdAt: '2024-01-15T14:00:00Z', position: 1 },
        { id: '2', type: 'grid_delivery', status: 'running', service: 'set_grid_delivery', targetValue: 'on', changes: [], createdAt: '2024-01-15T14:00:00Z', position: 2 },
      ];
      expect(element.activeCount).toBe(2);
    });
  });

  describe('formatServiceName', () => {
    it('should format set_box_mode service', () => {
      const result = (element as any).formatServiceName('set_box_mode');
      expect(result).toBe('🏠 Změna režimu boxu');
    });

    it('should format set_grid_delivery service', () => {
      const result = (element as any).formatServiceName('set_grid_delivery');
      expect(result).toBe('💧 Změna nastavení přetoků');
    });

    it('should format set_grid_delivery_limit service', () => {
      const result = (element as any).formatServiceName('set_grid_delivery_limit');
      expect(result).toBe('🔢 Změna limitu přetoků');
    });

    it('should format set_boiler_mode service', () => {
      const result = (element as any).formatServiceName('set_boiler_mode');
      expect(result).toBe('🔥 Změna nastavení bojleru');
    });

    it('should format set_formating_mode service', () => {
      const result = (element as any).formatServiceName('set_formating_mode');
      expect(result).toBe('🔋 Změna nabíjení baterie');
    });

    it('should format set_battery_capacity service', () => {
      const result = (element as any).formatServiceName('set_battery_capacity');
      expect(result).toBe('⚡ Změna kapacity baterie');
    });

    it('should return original service name for unknown service', () => {
      const result = (element as any).formatServiceName('unknown_service');
      expect(result).toBe('unknown_service');
    });

    it('should return N/A for empty string', () => {
      const result = (element as any).formatServiceName('');
      expect(result).toBe('N/A');
    });

    it('should return N/A for undefined', () => {
      const result = (element as any).formatServiceName(undefined as any);
      expect(result).toBe('N/A');
    });
  });

  describe('formatChanges', () => {
    it('should return N/A for empty changes', () => {
      const result = (element as any).formatChanges([]);
      expect(result).toBe('N/A');
    });

    it('should return N/A for null changes', () => {
      const result = (element as any).formatChanges(null as any);
      expect(result).toBe('N/A');
    });

    it('should format simple change without arrow', () => {
      const result = (element as any).formatChanges(['simple change']);
      expect(result).toBe('simple change');
    });

    it('should format mode change with arrow', () => {
      const result = (element as any).formatChanges(["mode: 'home_2' → 'home_1'"]);
      expect(result).toContain('→');
    });

    it('should format multiple changes', () => {
      const changes = [
        "mode: 'home_2' → 'home_1'",
        "limit: '1000' → '2000'",
      ];
      const result = (element as any).formatChanges(changes);
      expect(result).toContain(',');
    });

    it('should map CBB to Inteligentní', () => {
      const result = (element as any).formatChanges(["mode: 'Manual' → 'CBB'"]);
      expect(result).toContain('Inteligentní');
    });

    it('should map Manual to Manuální', () => {
      const result = (element as any).formatChanges(["mode: 'CBB' → 'Manual'"]);
      expect(result).toContain('Manuální');
    });

    it('should remove quotes from values', () => {
      const result = (element as any).formatChanges(["mode: 'home_1' → 'home_2'"]);
      expect(result).not.toContain("'");
    });
  });

  describe('formatTimestamp', () => {
    it('should return -- for empty timestamp', () => {
      const result = (element as any).formatTimestamp('');
      expect(result).toEqual({ time: '--', duration: '--' });
    });

    it('should return -- for null timestamp', () => {
      const result = (element as any).formatTimestamp(null as any);
      expect(result).toEqual({ time: '--', duration: '--' });
    });

    it('should format time for same day', () => {
      const timestamp = '2024-01-15T14:00:00Z';
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.time).toMatch(/^\d{2}:\d{2}$/);
      expect(result.time).not.toContain('.');
    });

    it('should format time with date for different day', () => {
      const timestamp = '2024-01-14T10:00:00Z';
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.time).toContain('.');
    });

    it('should format duration in seconds for recent items', () => {
      const timestamp = new Date(Date.now() - 30 * 1000).toISOString();
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.duration).toMatch(/^\d+s$/);
    });

    it('should format duration in minutes for older items', () => {
      const timestamp = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.duration).toMatch(/^\d+m \d+s$/);
    });

    it('should format duration in hours for very old items', () => {
      const timestamp = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.duration).toMatch(/^\d+h \d+m$/);
    });

    it('should return -- for invalid timestamp', () => {
      const result = (element as any).formatTimestamp('invalid');
      expect(result).toEqual({ time: '--', duration: '--' });
    });
  });

  describe('toggleExpanded', () => {
    it('should toggle expanded from false to true', () => {
      element.expanded = false;
      (element as any).toggleExpanded();
      expect(element.expanded).toBe(true);
    });

    it('should toggle expanded from true to false', () => {
      element.expanded = true;
      (element as any).toggleExpanded();
      expect(element.expanded).toBe(false);
    });
  });

  describe('removeItem', () => {
    it('should dispatch remove-item event', () => {
      const dispatchSpy = vi.spyOn(element, 'dispatchEvent');
      const mockEvent = { stopPropagation: vi.fn() } as unknown as Event;

      (element as any).removeItem(5, mockEvent);

      expect(mockEvent.stopPropagation).toHaveBeenCalled();
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'remove-item',
          detail: { position: 5 },
        })
      );
    });

    it('should include correct position in event detail', () => {
      const dispatchSpy = vi.spyOn(element, 'dispatchEvent');
      const mockEvent = { stopPropagation: vi.fn() } as unknown as Event;

      (element as any).removeItem(42, mockEvent);

      const dispatchedEvent = dispatchSpy.mock.calls[0][0] as CustomEvent;
      expect(dispatchedEvent.detail.position).toBe(42);
    });

    it('should bubble the event', () => {
      const dispatchSpy = vi.spyOn(element, 'dispatchEvent');
      const mockEvent = { stopPropagation: vi.fn() } as unknown as Event;

      (element as any).removeItem(1, mockEvent);

      const dispatchedEvent = dispatchSpy.mock.calls[0][0] as CustomEvent;
      expect(dispatchedEvent.bubbles).toBe(true);
    });
  });

  describe('lifecycle', () => {
    it('should set up interval on connectedCallback', () => {
      const setIntervalSpy = vi.spyOn(window, 'setInterval');
      element.connectedCallback();
      expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 1000);
    });

    it('should clear interval on disconnectedCallback', () => {
      element.connectedCallback();
      const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
      element.disconnectedCallback();
      expect(clearIntervalSpy).toHaveBeenCalled();
    });

    it('should update _now every second', () => {
      const initialNow = element['_now'];
      element.connectedCallback();
      vi.advanceTimersByTime(1000);
      expect(element['_now']).toBeGreaterThan(initialNow);
    });
  });

  describe('edge cases', () => {
    it('should handle items with missing properties', () => {
      const items = [
        {
          id: '1',
          type: 'mode_change',
          status: 'queued',
          service: 'set_box_mode',
          targetValue: 'home_1',
          changes: [],
          createdAt: '',
          position: 1,
        },
      ];
      element.items = items;
      expect(element.activeCount).toBe(1);
    });

    it('should handle items with running status', () => {
      const items: ShieldQueueItem[] = [
        {
          id: '1',
          type: 'mode_change',
          status: 'running',
          service: 'set_box_mode',
          targetValue: 'home_1',
          changes: [],
          createdAt: '2024-01-15T14:00:00Z',
          position: 1,
        },
      ];
      element.items = items;
      expect(element.items[0].status).toBe('running');
    });

    it('should handle formatChanges with colon in left side', () => {
      const changes = ["param:value → new_value"];
      const result = (element as any).formatChanges(changes);
      expect(result).toContain('value');
    });

    it('should handle formatTimestamp at exact hour boundary', () => {
      const timestamp = new Date(Date.now() - 60 * 60 * 1000).toISOString();
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.duration).toMatch(/^\d+h \d+m$/);
    });

    it('should handle formatTimestamp at exact minute boundary', () => {
      const timestamp = new Date(Date.now() - 60 * 1000).toISOString();
      const result = (element as any).formatTimestamp(timestamp);
      expect(result.duration).toMatch(/^\d+m \d+s$/);
    });
  });
});
