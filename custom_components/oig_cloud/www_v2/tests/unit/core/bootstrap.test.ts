import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { bootstrap, OIG_RUNTIME } from '@/core/bootstrap';
import { oigLog } from '@/core/logger';
import * as errors from '@/core/errors';

// Mock dependencies
vi.mock('@/core/logger', () => ({
  oigLog: {
    info: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/core/errors', () => ({
  setupErrorHandling: vi.fn(),
}));

describe('bootstrap', () => {
  let originalNavigator: Navigator;
  let originalInnerWidth: number;
  let mockElement: HTMLElement;

  beforeEach(() => {
    // Reset OIG_RUNTIME
    OIG_RUNTIME.isHaApp = false;
    OIG_RUNTIME.isMobile = false;
    OIG_RUNTIME.reduceMotion = false;

    // Store original values
    originalNavigator = globalThis.navigator;
    originalInnerWidth = globalThis.innerWidth;

    // Create mock document element
    mockElement = document.createElement('div');
    vi.spyOn(document, 'createElement').mockReturnValue(mockElement);
    vi.spyOn(document, 'documentElement', 'get').mockReturnValue(mockElement);

    // Clear mocks
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // Restore original values
    Object.defineProperty(globalThis, 'navigator', {
      value: originalNavigator,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(globalThis, 'innerWidth', {
      value: originalInnerWidth,
      writable: true,
      configurable: true,
    });
  });

  describe('detectHaApp', () => {
    it('should detect Home Assistant app from user agent', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Home Assistant/1.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(true);
    });

    it('should detect HomeAssistant (no space) in user agent', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 HomeAssistant/2024.1' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(true);
    });

    it('should detect HAcompanion in user agent', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'HAcompanion/2024.1.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(true);
    });

    it('should not detect HA app for regular browser', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(false);
    });

    it('should handle missing navigator gracefully', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: undefined,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(false);
    });

    it('should handle navigator access errors gracefully', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        get: () => {
          throw new Error('Navigator access denied');
        },
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isHaApp).toBe(false);
    });
  });

  describe('detectMobile', () => {
    it('should detect Android device', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Android 14' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1024,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(true);
    });

    it('should detect iPhone device', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 iPhone OS 17' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1024,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(true);
    });

    it('should detect iPad device', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 iPad OS 17' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1024,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(true);
    });

    it('should detect mobile from small viewport', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 768,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(true);
    });

    it('should detect mobile from very small viewport', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 375,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(true);
    });

    it('should not detect mobile for desktop browser', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0 Windows' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1920,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(false);
    });

    it('should handle missing navigator gracefully', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: undefined,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.isMobile).toBe(false);
    });
  });

  describe('reduceMotion detection', () => {
    it('should enable reduceMotion when isHaApp is true', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Home Assistant/1.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.reduceMotion).toBe(true);
    });

    it('should enable reduceMotion when isMobile is true', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Android 14' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1024,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.reduceMotion).toBe(true);
    });

    it('should enable reduceMotion when prefers-reduced-motion is set', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1920,
        writable: true,
        configurable: true,
      });

      // Mock matchMedia to return true for reduced motion
      const originalMatchMedia = globalThis.matchMedia;
      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: query === '(prefers-reduced-motion: reduce)',
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.reduceMotion).toBe(true);

      // Restore matchMedia
      Object.defineProperty(globalThis, 'matchMedia', {
        value: originalMatchMedia,
        writable: true,
        configurable: true,
      });
    });

    it('should not enable reduceMotion for desktop without preference', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0 Windows' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1920,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(OIG_RUNTIME.reduceMotion).toBe(false);
    });
  });

  describe('CSS class application', () => {
    it('should add oig-ha-app class when in HA app', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Home Assistant/1.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(mockElement.classList.contains('oig-ha-app')).toBe(true);
    });

    it('should add oig-mobile class on mobile device', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Android 14' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1024,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(mockElement.classList.contains('oig-mobile')).toBe(true);
    });

    it('should add oig-reduce-motion class when reduceMotion is true', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Home Assistant/1.0' },
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(mockElement.classList.contains('oig-reduce-motion')).toBe(true);
    });

    it('should not add classes when conditions are false', async () => {
      Object.defineProperty(globalThis, 'navigator', {
        value: { userAgent: 'Mozilla/5.0 Chrome/120.0 Windows' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(globalThis, 'innerWidth', {
        value: 1920,
        writable: true,
        configurable: true,
      });

      await bootstrap();
      expect(mockElement.classList.contains('oig-ha-app')).toBe(false);
      expect(mockElement.classList.contains('oig-mobile')).toBe(false);
      expect(mockElement.classList.contains('oig-reduce-motion')).toBe(false);
    });
  });

describe('bootstrap return value', () => {
  it('should return an HTMLElement', async () => {
    const result = await bootstrap();
    expect(result).toBeInstanceOf(HTMLElement);
  });
});

  describe('error handling setup', () => {
    it('should call setupErrorHandling during bootstrap', async () => {
      await bootstrap();
      expect(errors.setupErrorHandling).toHaveBeenCalledTimes(1);
    });
  });

  describe('logging', () => {
    it('should log bootstrap start and completion', async () => {
      await bootstrap();
      expect(oigLog.info).toHaveBeenCalledWith('Bootstrap starting');
      expect(oigLog.info).toHaveBeenCalledWith(
        'Bootstrap complete',
        expect.objectContaining({
          version: expect.any(String),
          storagePrefix: 'oig_v2_',
          isHaApp: expect.any(Boolean),
          isMobile: expect.any(Boolean),
          reduceMotion: expect.any(Boolean),
        })
      );
    });
  });
});
