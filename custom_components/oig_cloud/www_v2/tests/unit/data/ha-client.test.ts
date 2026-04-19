import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { HaClient, plannerState, PLAN_LABELS } from '@/data/ha-client';
import { AuthError, NetworkError } from '@/core/errors';
import { oigLog } from '@/core/logger';

vi.mock('@/core/logger', () => ({
  oigLog: {
    info: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

describe('HaClient', () => {
  let client: HaClient;
  let mockHass: any;

  beforeEach(() => {
    client = new HaClient();
    vi.clearAllMocks();

    mockHass = {
      auth: {
        data: {
          access_token: 'test-token-123',
        },
      },
      states: {},
      callService: vi.fn().mockResolvedValue(undefined),
      callApi: vi.fn().mockResolvedValue({}),
      callWS: vi.fn().mockResolvedValue({}),
    };

    // Reset window mocks
    (globalThis as any).window = {
      location: { href: 'http://localhost:8123' },
      parent: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('getHass', () => {
    it('should return cached hass if available', async () => {
      (client as any).hass = mockHass;
      const result = await client.getHass();
      expect(result).toBe(mockHass);
    });

    it('should return null when window is undefined', async () => {
      (globalThis as any).window = undefined;
      const result = await client.getHass();
      expect(result).toBeNull();
    });

    it('should find hass on window object', async () => {
      (globalThis as any).window.hass = mockHass;
      const result = await client.getHass();
      expect(result).toBe(mockHass);
    });

    it('should find hass on customPanel', async () => {
      (globalThis as any).window.customPanel = { hass: mockHass };
      const result = await client.getHass();
      expect(result).toBe(mockHass);
    });

    it('should return null when hass not found', async () => {
      const result = await client.getHass();
      expect(result).toBeNull();
    });
  });

  describe('getHassSync', () => {
    it('should return cached hass synchronously', () => {
      (client as any).hass = mockHass;
      const result = client.getHassSync();
      expect(result).toBe(mockHass);
    });

    it('should return null when no cached hass', () => {
      const result = client.getHassSync();
      expect(result).toBeNull();
    });
  });

  describe('refreshHass', () => {
    it('should refresh and update cached hass', async () => {
      (client as any).hass = { old: true };
      (globalThis as any).window.hass = mockHass;

      const result = await client.refreshHass();
      expect(result).toBe(mockHass);
      expect(client.getHassSync()).toBe(mockHass);
    });

    it('should keep old hass when refresh finds nothing', async () => {
      const oldHass = { old: true };
      (client as any).hass = oldHass;

      const result = await client.refreshHass();
      expect(result).toBe(oldHass);
    });
  });

  describe('fetchWithAuth', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
      global.fetch = vi.fn();
    });

    it('should throw AuthError when hass is null', async () => {
      (client as any).hass = null;
      await expect(client.fetchWithAuth('/api/test')).rejects.toThrow(AuthError);
    });

    it('should throw AuthError when no access token', async () => {
      mockHass.auth.data.access_token = null;
      await expect(client.fetchWithAuth('/api/test')).rejects.toThrow(AuthError);
    });

    it('should reject non-localhost absolute URLs', async () => {
      await expect(
        client.fetchWithAuth('https://evil.com/api')
      ).rejects.toThrow(/rejected for non-localhost/);
    });

    it('should allow localhost URLs', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });

      await client.fetchWithAuth('http://localhost:8123/api/test');
      expect(global.fetch).toHaveBeenCalled();
    });

    it('should allow /api/ URLs', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });

      await client.fetchWithAuth('/api/oig_cloud/test');
      expect(global.fetch).toHaveBeenCalled();
    });

    it('should add Authorization header with Bearer token', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });

      await client.fetchWithAuth('/api/test');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[1].headers.get('Authorization')).toBe('Bearer test-token-123');
    });

    it('should add Content-Type header if not present', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });

      await client.fetchWithAuth('/api/test');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[1].headers.get('Content-Type')).toBe('application/json');
    });

    it('should preserve existing Content-Type header', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });

      await client.fetchWithAuth('/api/test', {
        headers: { 'Content-Type': 'text/plain' },
      });
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[1].headers.get('Content-Type')).toBe('text/plain');
    });

    it('should throw AuthError on 401 response', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
      });

      await expect(client.fetchWithAuth('/api/test')).rejects.toThrow(AuthError);
    });

    it('should throw NetworkError on other HTTP errors', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      await expect(client.fetchWithAuth('/api/test')).rejects.toThrow(NetworkError);
    });

    it('should retry on NetworkError and succeed', async () => {
      global.fetch = vi
        .fn()
        .mockRejectedValueOnce(new NetworkError('Connection failed'))
        .mockResolvedValueOnce({
          ok: true,
          json: vi.fn().mockResolvedValue({ success: true }),
        });

      const result = await client.fetchWithAuth('/api/test');
      expect(global.fetch).toHaveBeenCalledTimes(2);
      expect(result.ok).toBe(true);
    });

    it('should throw after max retries exceeded', async () => {
      global.fetch = vi.fn().mockRejectedValue(new NetworkError('Connection failed'));

      await expect(client.fetchWithAuth('/api/test')).rejects.toThrow(NetworkError);
      expect(global.fetch).toHaveBeenCalledTimes(4); // initial + 3 retries
    });
  });

  describe('callService', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
    });

    it('should return true on successful service call', async () => {
      const result = await client.callService('oig_cloud', 'set_mode', { mode: 'home' });
      expect(result).toBe(true);
      expect(mockHass.callService).toHaveBeenCalledWith('oig_cloud', 'set_mode', { mode: 'home' });
    });

    it('should return false when hass is null', async () => {
      (client as any).hass = null;
      const result = await client.callService('oig_cloud', 'set_mode', {});
      expect(result).toBe(false);
    });

    it('should return false when callService throws', async () => {
      mockHass.callService.mockRejectedValue(new Error('Service failed'));
      const result = await client.callService('oig_cloud', 'set_mode', {});
      expect(result).toBe(false);
    });

    it('should return false when callService is undefined', async () => {
      mockHass.callService = undefined;
      const result = await client.callService('oig_cloud', 'set_mode', {});
      expect(result).toBe(false);
    });
  });

  describe('callApi', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
    });

    it('should call hass.callApi with correct parameters', async () => {
      mockHass.callApi.mockResolvedValue({ data: 'test' });
      const result = await client.callApi('GET', '/api/config');
      expect(mockHass.callApi).toHaveBeenCalledWith('GET', '/api/config', undefined);
      expect(result).toEqual({ data: 'test' });
    });

    it('should throw AuthError when hass is null', async () => {
      (client as any).hass = null;
      await expect(client.callApi('GET', '/api/config')).rejects.toThrow(AuthError);
    });
  });

  describe('callWS', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
    });

    it('should call hass.callWS with message', async () => {
      mockHass.callWS.mockResolvedValue({ result: 'success' });
      const result = await client.callWS({ type: 'config/core/get' });
      expect(mockHass.callWS).toHaveBeenCalledWith({ type: 'config/core/get' });
      expect(result).toEqual({ result: 'success' });
    });

    it('should throw AuthError when callWS is undefined', async () => {
      mockHass.callWS = undefined;
      await expect(client.callWS({})).rejects.toThrow(AuthError);
    });
  });

  describe('fetchOIGAPI', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ data: 'test' }),
      });
    });

    it('should construct correct URL for endpoint without leading slash', async () => {
      await client.fetchOIGAPI('test/endpoint');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/api/oig_cloud/test/endpoint');
    });

    it('should construct correct URL for endpoint with leading slash', async () => {
      await client.fetchOIGAPI('/test/endpoint');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/api/oig_cloud/test/endpoint');
    });

    it('should return parsed JSON on success', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ success: true, data: [1, 2, 3] }),
      });

      const result = await client.fetchOIGAPI('/test');
      expect(result).toEqual({ success: true, data: [1, 2, 3] });
    });

    it('should return null on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      const result = await client.fetchOIGAPI('/test');
      expect(result).toBeNull();
    });
  });

  describe('convenience loaders', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({}),
      });
    });

    it('loadBatteryTimeline should call correct endpoint', async () => {
      await client.loadBatteryTimeline('INV123', 'active');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/battery_forecast/INV123/timeline');
      expect(callArgs[0]).toContain('type=active');
    });

    it('loadUnifiedCostTile should call correct endpoint', async () => {
      await client.loadUnifiedCostTile('INV123');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/battery_forecast/INV123/unified_cost_tile');
    });

    it('loadSpotPrices should call correct endpoint', async () => {
      await client.loadSpotPrices('INV123');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/spot_prices/INV123/intervals');
    });

    it('loadAnalytics should call correct endpoint', async () => {
      await client.loadAnalytics('INV123');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/analytics/INV123');
    });

    it('loadPlannerSettings should call correct endpoint', async () => {
      await client.loadPlannerSettings('INV123');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/battery_forecast/INV123/planner_settings');
    });

    it('savePlannerSettings should POST with body', async () => {
      const settings = { mode: 'home', threshold: 50 };
      await client.savePlannerSettings('INV123', settings);
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[1].method).toBe('POST');
      expect(callArgs[1].body).toBe(JSON.stringify(settings));
    });

    it('loadDetailTabs should call correct endpoint with params', async () => {
      await client.loadDetailTabs('INV123', 'cost', 'hybrid');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/battery_forecast/INV123/detail_tabs');
      expect(callArgs[0]).toContain('tab=cost');
      expect(callArgs[0]).toContain('plan=hybrid');
    });

    it('loadModules should call correct endpoint', async () => {
      await client.loadModules('entry_123');
      const callArgs = (global.fetch as any).mock.calls[0];
      expect(callArgs[0]).toContain('/entry_123/modules');
    });
  });

  describe('openEntityDialog', () => {
    it('should dispatch hass-more-info event', () => {
      const mockHa = document.createElement('div');
      const dispatchSpy = vi.spyOn(mockHa, 'dispatchEvent');

      (globalThis as any).window = {
        parent: {
          document: {
            querySelector: vi.fn().mockReturnValue(mockHa),
          },
        },
      };

      const result = client.openEntityDialog('sensor.test');
      expect(result).toBe(true);
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'hass-more-info',
          detail: { entityId: 'sensor.test' },
        })
      );
    });

    it('should fallback to document.querySelector when parent fails', () => {
      const mockHa = document.createElement('div');
      const dispatchSpy = vi.spyOn(mockHa, 'dispatchEvent');

      (globalThis as any).window = {
        parent: {
          document: {
            querySelector: vi.fn().mockReturnValue(null),
          },
        },
      };
      vi.spyOn(document, 'querySelector').mockReturnValue(mockHa);

      const result = client.openEntityDialog('sensor.test');
      expect(result).toBe(true);
      expect(dispatchSpy).toHaveBeenCalled();
    });

    it('should return false when home-assistant element not found', () => {
      (globalThis as any).window = {
        parent: {
          document: {
            querySelector: vi.fn().mockReturnValue(null),
          },
        },
      };
      vi.spyOn(document, 'querySelector').mockReturnValue(null);

      const result = client.openEntityDialog('sensor.test');
      expect(result).toBe(false);
    });

    it('should return false on error', () => {
      (globalThis as any).window = {
        parent: {
          document: {
            querySelector: vi.fn().mockImplementation(() => {
              throw new Error('Access denied');
            }),
          },
        },
      };

      const result = client.openEntityDialog('sensor.test');
      expect(result).toBe(false);
    });
  });

  describe('showNotification', () => {
    beforeEach(async () => {
      (client as any).hass = mockHass;
    });

    it('should call persistent_notification service', async () => {
      await client.showNotification('Test Title', 'Test Message', 'info');
      expect(mockHass.callService).toHaveBeenCalledWith(
        'persistent_notification',
        'create',
        expect.objectContaining({
          title: 'Test Title',
          message: 'Test Message',
          notification_id: expect.stringMatching(/^oig_dashboard_/),
        })
      );
    });

    it('should default to success type', async () => {
      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
      mockHass.callService.mockResolvedValue(false);

      await client.showNotification('Test', 'Message');
      expect(mockHass.callService).toHaveBeenCalled();
    });

    it('should log to console when service call fails', async () => {
      mockHass.callService.mockRejectedValue(new Error('Service failed'));
      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

      await client.showNotification('Test', 'Message', 'error');
      expect(consoleSpy).toHaveBeenCalledWith('[ERROR] Test: Message');
    });
  });

  describe('getToken', () => {
    it('should return access token', () => {
      (client as any).hass = mockHass;
      const token = client.getToken();
      expect(token).toBe('test-token-123');
    });

    it('should return null when no hass', () => {
      (client as any).hass = null;
      const token = client.getToken();
      expect(token).toBeNull();
    });

    it('should return null when auth data is missing', () => {
      (client as any).hass = { auth: null };
      const token = client.getToken();
      expect(token).toBeNull();
    });
  });
});

describe('plannerState', () => {
  beforeEach(() => {
    plannerState.invalidate();
  });

  describe('fetchSettings', () => {
    it('should return cached settings within TTL', async () => {
      const mockClient = {
        loadPlannerSettings: vi.fn().mockResolvedValue({ mode: 'home' }),
      } as any;

      await plannerState.fetchSettings(mockClient, 'INV123');
      const result = await plannerState.fetchSettings(mockClient, 'INV123');

      expect(mockClient.loadPlannerSettings).toHaveBeenCalledTimes(1);
      expect(result).toEqual({ mode: 'home' });
    });

    it('should fetch new settings when force is true', async () => {
      const mockClient = {
        loadPlannerSettings: vi.fn().mockResolvedValue({ mode: 'home' }),
      } as any;

      await plannerState.fetchSettings(mockClient, 'INV123');
      await plannerState.fetchSettings(mockClient, 'INV123', true);

      expect(mockClient.loadPlannerSettings).toHaveBeenCalledTimes(2);
    });

    it('should deduplicate concurrent requests', async () => {
      let resolveFn: (value: any) => void;
      const mockClient = {
        loadPlannerSettings: vi.fn().mockImplementation(
          () => new Promise((resolve) => {
            resolveFn = resolve;
          })
        ),
      } as any;

      const promise1 = plannerState.fetchSettings(mockClient, 'INV123');
      const promise2 = plannerState.fetchSettings(mockClient, 'INV123');

      resolveFn!({ mode: 'home' });

      const [result1, result2] = await Promise.all([promise1, promise2]);
      expect(result1).toBe(result2);
      expect(mockClient.loadPlannerSettings).toHaveBeenCalledTimes(1);
    });

    it('should return null on error', async () => {
      const mockClient = {
        loadPlannerSettings: vi.fn().mockRejectedValue(new Error('Failed')),
      } as any;

      const result = await plannerState.fetchSettings(mockClient, 'INV123');
      expect(result).toBeNull();
    });
  });

  describe('getDefaultPlan', () => {
    it('should return hybrid', () => {
      expect(plannerState.getDefaultPlan()).toBe('hybrid');
    });
  });

  describe('getCachedSettings', () => {
    it('should return cached settings', async () => {
      const mockClient = {
        loadPlannerSettings: vi.fn().mockResolvedValue({ mode: 'home' }),
      } as any;

      await plannerState.fetchSettings(mockClient, 'INV123');
      expect(plannerState.getCachedSettings()).toEqual({ mode: 'home' });
    });

    it('should return null when no cache', () => {
      expect(plannerState.getCachedSettings()).toBeNull();
    });
  });

  describe('getLabels', () => {
    it('should return labels for hybrid plan', () => {
      const labels = plannerState.getLabels('hybrid');
      expect(labels).toEqual({ short: 'Plán', long: 'Plánování' });
    });

    it('should return hybrid labels for unknown plan', () => {
      const labels = plannerState.getLabels('unknown');
      expect(labels).toEqual({ short: 'Plán', long: 'Plánování' });
    });
  });

  describe('invalidate', () => {
    it('should clear cache', async () => {
      const mockClient = {
        loadPlannerSettings: vi.fn().mockResolvedValue({ mode: 'home' }),
      } as any;

      await plannerState.fetchSettings(mockClient, 'INV123');
      plannerState.invalidate();
      expect(plannerState.getCachedSettings()).toBeNull();
    });
  });
});

describe('PLAN_LABELS', () => {
  it('should have hybrid plan labels', () => {
    expect(PLAN_LABELS.hybrid).toEqual({ short: 'Plán', long: 'Plánování' });
  });
});
