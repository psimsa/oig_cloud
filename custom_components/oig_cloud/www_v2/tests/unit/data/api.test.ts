import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiClient, apiClient } from '@/data/api';
import { ApiError, NetworkError } from '@/core/errors';

describe('ApiClient', () => {
  let client: ApiClient;

  beforeEach(() => {
    client = new ApiClient('/api/oig_cloud');
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-15T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('basic HTTP methods', () => {
    it('should make GET requests', async () => {
      const mockData = { id: 1, name: 'test' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      const result = await client.get('/test');

      expect(result).toEqual(mockData);
      expect(fetch).toHaveBeenCalledWith(
        '/api/oig_cloud/test',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
    });

    it('should make POST requests with body', async () => {
      const mockData = { success: true };
      const requestBody = { key: 'value' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      const result = await client.post('/test', requestBody);

      expect(result).toEqual(mockData);
      expect(fetch).toHaveBeenCalledWith(
        '/api/oig_cloud/test',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(requestBody),
        })
      );
    });

    it('should include Authorization header when token provided', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({}),
      } as Response);

      await client.get('/test', { token: 'test-token-123' });

      expect(fetch).toHaveBeenCalledWith(
        '/api/oig_cloud/test',
        expect.objectContaining({
          headers: expect.objectContaining({
            'Authorization': 'Bearer test-token-123',
            'Content-Type': 'application/json',
          }),
        })
      );
    });
  });

  describe('caching behavior', () => {
    it('should cache GET responses and return cached data on subsequent calls', async () => {
      const mockData = { data: 'cached' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      const result1 = await client.get('/cached');
      const result2 = await client.get('/cached');

      expect(result1).toEqual(mockData);
      expect(result2).toEqual(mockData);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('should respect custom TTL', async () => {
      const mockData = { data: 'test' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      await client.get('/ttl-test', { ttl: 5000 });
      
      // Advance time but stay within TTL
      vi.advanceTimersByTime(4000);
      await client.get('/ttl-test');
      expect(fetch).toHaveBeenCalledTimes(1);

      // Advance past TTL
      vi.advanceTimersByTime(2000);
      await client.get('/ttl-test');
      expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('should not cache when cache option is false', async () => {
      const mockData = { data: 'test' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      await client.get('/no-cache', { cache: false });
      await client.get('/no-cache', { cache: false });

      expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('should not cache POST requests', async () => {
      const mockData = { success: true };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockData),
      } as Response);

      await client.post('/create', { data: 1 });
      await client.post('/create', { data: 2 });

      expect(fetch).toHaveBeenCalledTimes(2);
    });
  });

  describe('request deduplication', () => {
    it('should deduplicate concurrent identical requests', async () => {
      let resolveFetch: (value: Response) => void;
      const fetchPromise = new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      });
      global.fetch = vi.fn().mockReturnValue(fetchPromise);

      const promise1 = client.get('/dedup');
      const promise2 = client.get('/dedup');
      const promise3 = client.get('/dedup');

      expect(fetch).toHaveBeenCalledTimes(1);

      resolveFetch!({
        ok: true,
        json: () => Promise.resolve({ data: 'result' }),
      } as Response);

      const [result1, result2, result3] = await Promise.all([promise1, promise2, promise3]);

      expect(result1).toEqual({ data: 'result' });
      expect(result2).toEqual({ data: 'result' });
      expect(result3).toEqual({ data: 'result' });
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('should allow new request after first completes', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      await client.get('/sequential');
      await client.get('/sequential');

      expect(fetch).toHaveBeenCalledTimes(1); // Second call hits cache
    });
  });

  describe('error handling', () => {
    it('should throw ApiError on HTTP error responses', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      } as Response);

      await expect(client.get('/not-found')).rejects.toThrow(ApiError);
      await expect(client.get('/not-found')).rejects.toThrow('API request failed: Not Found');
    });

    it('should include status code in ApiError', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      } as Response);

      try {
        await client.get('/error');
        expect.fail('Should have thrown');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(500);
        expect((error as ApiError).statusText).toBe('Internal Server Error');
      }
    });

    it('should throw NetworkError on fetch failure', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network failure'));

      await expect(client.get('/network-error')).rejects.toThrow(NetworkError);
      await expect(client.get('/network-error')).rejects.toThrow('Network error: Network failure');
    });

    it('should propagate AbortError without wrapping', async () => {
      const abortError = new Error('Aborted');
      abortError.name = 'AbortError';
      global.fetch = vi.fn().mockRejectedValue(abortError);

      await expect(client.get('/aborted')).rejects.toThrow('Aborted');
    });

    it('should handle JSON parsing errors', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.reject(new Error('Invalid JSON')),
      } as Response);

      await expect(client.get('/invalid-json')).rejects.toThrow();
    });
  });

  describe('cache management', () => {
    it('should clear all cache entries', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      await client.get('/cache1');
      await client.get('/cache2');

      client.clearCache();

      await client.get('/cache1');
      expect(fetch).toHaveBeenCalledTimes(3); // 2 initial + 1 after clear
    });

    it('should clear cache entries matching pattern', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      await client.get('/users');
      await client.get('/posts');

      client.clearCache('/users');

      await client.get('/users');
      await client.get('/posts');
      expect(fetch).toHaveBeenCalledTimes(3);
    });

    it('should abort pending requests', async () => {
      const fetchPromise = new Promise<Response>(() => {}); // Never resolves
      global.fetch = vi.fn().mockReturnValue(fetchPromise);

      client.get('/pending');
      client.abortPending();

      // After abort, new request should work
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'new' }),
      } as Response);

      const result = await client.get('/pending');
      expect(result).toEqual({ data: 'new' });
    });
  });

  describe('singleton instance', () => {
    it('should export a singleton apiClient', () => {
      expect(apiClient).toBeInstanceOf(ApiClient);
    });

    it('should use default base URL', async () => {
      const defaultClient = new ApiClient();
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({}),
      } as Response);

      await defaultClient.get('/test');

      expect(fetch).toHaveBeenCalledWith(
        '/api/oig_cloud/test',
        expect.any(Object)
      );
    });
  });

  describe('signal support', () => {
    it('should pass AbortSignal to fetch', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      const controller = new AbortController();
      await client.get('/signal-test', { signal: controller.signal });

      expect(fetch).toHaveBeenCalledWith(
        '/api/oig_cloud/signal-test',
        expect.objectContaining({
          signal: controller.signal,
        })
      );
    });
  });
});
