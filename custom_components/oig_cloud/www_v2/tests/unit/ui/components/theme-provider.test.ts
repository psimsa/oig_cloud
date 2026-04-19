import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ThemeProvider, getThemeInfo, setTheme } from '@/ui/components/theme-provider';
import { oigLog } from '@/core/logger';

vi.mock('@/core/logger', () => ({
  oigLog: {
    info: vi.fn(),
    debug: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

function callMethod(el: ThemeProvider, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No callable "${name}" on ThemeProvider`);
  return Reflect.apply(fn, el, args);
}

describe('ThemeProvider — default state', () => {
  let el: ThemeProvider;

  beforeEach(() => {
    el = new ThemeProvider();
  });

  it('mode defaults to "auto"', () => {
    expect(el.mode).toBe('auto');
  });

  it('getThemeInfo() returns an object with mode, isDark, breakpoint, width', () => {
    const info = el.getThemeInfo();
    expect(info).toHaveProperty('mode');
    expect(info).toHaveProperty('isDark');
    expect(info).toHaveProperty('breakpoint');
    expect(info).toHaveProperty('width');
  });

  it('getThemeInfo() mode matches the default', () => {
    expect(el.getThemeInfo().mode).toBe('auto');
  });

  it('getThemeInfo() isDark is false by default (matchMedia returns false)', () => {
    expect(el.getThemeInfo().isDark).toBe(false);
  });

  it('getThemeInfo() breakpoint defaults to "desktop"', () => {
    expect(el.getThemeInfo().breakpoint).toBe('desktop');
  });
});

describe('ThemeProvider — loadTheme()', () => {
  let el: ThemeProvider;

  beforeEach(() => {
    el = new ThemeProvider();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sets mode to "light" when localStorage contains "light"', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('light');
    callMethod(el, 'loadTheme');
    expect(el.mode).toBe('light');
  });

  it('sets mode to "dark" when localStorage contains "dark"', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('dark');
    callMethod(el, 'loadTheme');
    expect(el.mode).toBe('dark');
  });

  it('sets mode to "auto" when localStorage contains "auto"', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('auto');
    callMethod(el, 'loadTheme');
    expect(el.mode).toBe('auto');
  });

  it('does not change mode when localStorage contains an invalid value', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('system');
    callMethod(el, 'loadTheme');
    expect(el.mode).toBe('auto');
  });

  it('does not change mode when localStorage returns null', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
    callMethod(el, 'loadTheme');
    expect(el.mode).toBe('auto');
  });

  it('reads from the "oig_v2_theme" storage key', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('light');
    callMethod(el, 'loadTheme');
    expect(spy).toHaveBeenCalledWith('oig_v2_theme');
  });
});

describe('ThemeProvider — setTheme()', () => {
  let el: ThemeProvider;

  beforeEach(() => {
    el = new ThemeProvider();
    vi.spyOn(Storage.prototype, 'setItem');
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('persists the new mode to localStorage under "oig_v2_theme"', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    el.setTheme('dark');
    expect(spy).toHaveBeenCalledWith('oig_v2_theme', 'dark');
  });

  it('persists "light" to localStorage', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    el.setTheme('light');
    expect(spy).toHaveBeenCalledWith('oig_v2_theme', 'light');
  });

  it('sets isDark to true when mode is "dark"', () => {
    el.setTheme('dark');
    expect(el.getThemeInfo().isDark).toBe(true);
  });

  it('sets isDark to false when mode is "light"', () => {
    el.setTheme('light');
    expect(el.getThemeInfo().isDark).toBe(false);
  });

  it('sets isDark based on matchMedia when mode is "auto" — dark system', () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        media: '',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
    el.setTheme('auto');
    expect(el.getThemeInfo().isDark).toBe(true);
  });

  it('sets isDark based on matchMedia when mode is "auto" — light system', () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        media: '',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
    el.setTheme('auto');
    expect(el.getThemeInfo().isDark).toBe(false);
  });

  it('dispatches a "theme-changed" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('theme-changed', handler);
    el.setTheme('dark');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('"theme-changed" event detail contains mode and isDark', () => {
    let detail: Record<string, unknown> | undefined;
    el.addEventListener('theme-changed', (e: Event) => {
      detail = (e as CustomEvent).detail as Record<string, unknown>;
    });
    el.setTheme('dark');
    expect(detail).toMatchObject({ mode: 'dark', isDark: true });
  });

  it('"theme-changed" event detail isDark is false for "light" mode', () => {
    let detail: Record<string, unknown> | undefined;
    el.addEventListener('theme-changed', (e: Event) => {
      detail = (e as CustomEvent).detail as Record<string, unknown>;
    });
    el.setTheme('light');
    expect(detail).toMatchObject({ mode: 'light', isDark: false });
  });

  it('logs the theme change via oigLog.info', () => {
    el.setTheme('light');
    expect(oigLog.info).toHaveBeenCalledWith(
      'Theme changed',
      expect.objectContaining({ mode: 'light' })
    );
  });

  it('updates mode property to the new value', () => {
    el.setTheme('light');
    expect(el.mode).toBe('light');
    el.setTheme('dark');
    expect(el.mode).toBe('dark');
  });
});

describe('ThemeProvider — onMediaChange()', () => {
  let el: ThemeProvider;

  beforeEach(() => {
    el = new ThemeProvider();
    vi.spyOn(Storage.prototype, 'setItem');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('updates isDark to true when mode is "auto" and event.matches is true', () => {
    el.mode = 'auto';
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(el.getThemeInfo().isDark).toBe(true);
  });

  it('updates isDark to false when mode is "auto" and event.matches is false', () => {
    el.mode = 'auto';
    callMethod(el, 'onMediaChange', { matches: false } as MediaQueryListEvent);
    expect(el.getThemeInfo().isDark).toBe(false);
  });

  it('dispatches "theme-changed" when mode is "auto"', () => {
    el.mode = 'auto';
    const handler = vi.fn();
    el.addEventListener('theme-changed', handler);
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('"theme-changed" detail contains isDark matching event.matches', () => {
    el.mode = 'auto';
    let detail: Record<string, unknown> | undefined;
    el.addEventListener('theme-changed', (e: Event) => {
      detail = (e as CustomEvent).detail as Record<string, unknown>;
    });
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(detail).toMatchObject({ isDark: true });
  });

  it('does not dispatch "theme-changed" when mode is "light"', () => {
    el.mode = 'light';
    const handler = vi.fn();
    el.addEventListener('theme-changed', handler);
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(handler).not.toHaveBeenCalled();
  });

  it('does not change isDark when mode is "dark"', () => {
    el.mode = 'dark';
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(el.getThemeInfo().isDark).toBe(false);
  });

  it('does not dispatch "theme-changed" when mode is "dark"', () => {
    el.mode = 'dark';
    const handler = vi.fn();
    el.addEventListener('theme-changed', handler);
    callMethod(el, 'onMediaChange', { matches: true } as MediaQueryListEvent);
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('getThemeInfo exported helper', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns { isDark: false, breakpoint: "desktop" } when no provider in DOM', () => {
    vi.spyOn(document, 'querySelector').mockReturnValue(null);
    const info = getThemeInfo();
    expect(info).toEqual({ isDark: false, breakpoint: 'desktop' });
  });

  it('delegates to the provider when one is present in the DOM', () => {
    const mockProvider = new ThemeProvider();
    vi.spyOn(Storage.prototype, 'setItem');
    mockProvider.setTheme('dark');
    vi.spyOn(document, 'querySelector').mockReturnValue(
      mockProvider as unknown as Element
    );
    const info = getThemeInfo();
    expect(info.isDark).toBe(true);
    expect(info.breakpoint).toBe('desktop');
  });

  it('returned object has exactly isDark and breakpoint keys', () => {
    vi.spyOn(document, 'querySelector').mockReturnValue(null);
    const info = getThemeInfo();
    expect(Object.keys(info).sort()).toEqual(['breakpoint', 'isDark']);
  });
});

describe('setTheme exported helper', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does nothing (no throw) when no provider is in the DOM', () => {
    vi.spyOn(document, 'querySelector').mockReturnValue(null);
    expect(() => setTheme('dark')).not.toThrow();
  });

  it('calls setTheme() on the provider when one is present', () => {
    const mockProvider = new ThemeProvider();
    const spy = vi.spyOn(mockProvider, 'setTheme').mockImplementation(() => {});
    vi.spyOn(document, 'querySelector').mockReturnValue(
      mockProvider as unknown as Element
    );
    setTheme('light');
    expect(spy).toHaveBeenCalledWith('light');
  });

  it('passes the exact mode to the provider', () => {
    const mockProvider = new ThemeProvider();
    const spy = vi.spyOn(mockProvider, 'setTheme').mockImplementation(() => {});
    vi.spyOn(document, 'querySelector').mockReturnValue(
      mockProvider as unknown as Element
    );
    setTheme('auto');
    expect(spy).toHaveBeenCalledWith('auto');
  });
});
