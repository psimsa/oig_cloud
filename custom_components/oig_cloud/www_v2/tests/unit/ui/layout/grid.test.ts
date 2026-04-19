import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { OigGrid, resetLayout } from '@/ui/layout/grid';

describe('resetLayout() module export', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('removes the oig_v2_layout_mobile key from localStorage', () => {
    localStorage.setItem('oig_v2_layout_mobile', 'order-data');
    resetLayout('mobile');
    expect(localStorage.getItem('oig_v2_layout_mobile')).toBeNull();
  });

  it('removes the oig_v2_layout_desktop key from localStorage', () => {
    localStorage.setItem('oig_v2_layout_desktop', 'order-data');
    resetLayout('desktop');
    expect(localStorage.getItem('oig_v2_layout_desktop')).toBeNull();
  });

  it('does not affect other breakpoint keys', () => {
    localStorage.setItem('oig_v2_layout_mobile', 'mobile');
    localStorage.setItem('oig_v2_layout_desktop', 'desktop');
    resetLayout('mobile');
    expect(localStorage.getItem('oig_v2_layout_desktop')).toBe('desktop');
  });

  it('silently no-ops when the key does not exist', () => {
    expect(() => resetLayout('tablet')).not.toThrow();
  });
});

describe('OigGrid — property defaults', () => {
  let el: OigGrid;

  beforeEach(() => {
    el = new OigGrid();
  });

  it('editable defaults to false', () => {
    expect(el.editable).toBe(false);
  });

  it('breakpoint private state defaults to desktop', () => {
    expect(Reflect.get(el, 'breakpoint')).toBe('desktop');
  });
});

describe('OigGrid — resetLayout() instance method', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('removes oig_v2_layout_ key for the current breakpoint', () => {
    const el = new OigGrid();
    Reflect.set(el, 'breakpoint', 'mobile');
    localStorage.setItem('oig_v2_layout_mobile', 'some-order');
    el.resetLayout();
    expect(localStorage.getItem('oig_v2_layout_mobile')).toBeNull();
  });

  it('uses current breakpoint value as the storage key suffix', () => {
    const el = new OigGrid();
    Reflect.set(el, 'breakpoint', 'tablet');
    localStorage.setItem('oig_v2_layout_tablet', 'tablet-order');
    el.resetLayout();
    expect(localStorage.getItem('oig_v2_layout_tablet')).toBeNull();
  });

  it('does not remove keys for other breakpoints', () => {
    const el = new OigGrid();
    Reflect.set(el, 'breakpoint', 'desktop');
    localStorage.setItem('oig_v2_layout_desktop', 'desktop-order');
    localStorage.setItem('oig_v2_layout_mobile', 'mobile-order');
    el.resetLayout();
    expect(localStorage.getItem('oig_v2_layout_mobile')).toBe('mobile-order');
  });
});

describe('OigGrid — resize listener lifecycle', () => {
  let el: HTMLElement;

  afterEach(() => {
    el?.remove();
    vi.restoreAllMocks();
  });

  it('adds a resize event listener when connected to DOM', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    el = document.createElement('oig-grid');
    document.body.appendChild(el);
    const resizeCalls = addSpy.mock.calls.filter(([evt]) => evt === 'resize');
    expect(resizeCalls.length).toBeGreaterThan(0);
  });

  it('removes the resize event listener when disconnected from DOM', () => {
    el = document.createElement('oig-grid');
    document.body.appendChild(el);
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    el.remove();
    const resizeCalls = removeSpy.mock.calls.filter(([evt]) => evt === 'resize');
    expect(resizeCalls.length).toBeGreaterThan(0);
  });
});
