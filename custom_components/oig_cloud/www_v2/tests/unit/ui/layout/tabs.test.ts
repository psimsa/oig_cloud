import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OigTabs } from '@/ui/layout/tabs';
import type { Tab } from '@/ui/layout/tabs';

const DEFAULT_TABS: Tab[] = [
  { id: 'flow', label: 'Toky', icon: '⚡' },
  { id: 'pricing', label: 'Ceny' },
  { id: 'settings', label: 'Nastavení' },
];

function callMethod(el: OigTabs, name: string, ...args: unknown[]): unknown {
  const method = Reflect.get(el, name);
  if (typeof method !== 'function') throw new Error(`No method on tabs: ${name}`);
  return Reflect.apply(method, el, args);
}

describe('OigTabs — property defaults', () => {
  it('tabs defaults to empty array', () => {
    const el = new OigTabs();
    expect(el.tabs).toEqual([]);
  });

  it('activeTab defaults to empty string', () => {
    const el = new OigTabs();
    expect(el.activeTab).toBe('');
  });
});

describe('OigTabs — isActive()', () => {
  let el: OigTabs;

  beforeEach(() => {
    el = new OigTabs();
    el.tabs = DEFAULT_TABS;
    el.activeTab = 'flow';
  });

  it('returns true for the current activeTab id', () => {
    expect(el.isActive('flow')).toBe(true);
  });

  it('returns false for a tab that is not active', () => {
    expect(el.isActive('pricing')).toBe(false);
  });

  it('returns false for an id not in the tabs list', () => {
    expect(el.isActive('unknown')).toBe(false);
  });

  it('returns false for empty string when activeTab is set', () => {
    expect(el.isActive('')).toBe(false);
  });

  it('updates correctly after activeTab is changed', () => {
    el.activeTab = 'pricing';
    expect(el.isActive('pricing')).toBe(true);
    expect(el.isActive('flow')).toBe(false);
  });
});

describe('OigTabs — onTabClick() event dispatch', () => {
  let el: OigTabs;

  beforeEach(() => {
    el = new OigTabs();
    el.tabs = DEFAULT_TABS;
    el.activeTab = 'flow';
  });

  it('dispatches tab-change event when clicking a different tab', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'pricing');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('tab-change detail contains the clicked tabId', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'settings');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ tabId: 'settings' });
  });

  it('does not dispatch tab-change when clicking the already-active tab', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'flow');
    expect(handler).not.toHaveBeenCalled();
  });

  it('updates activeTab property on successful tab click', () => {
    callMethod(el, 'onTabClick', 'pricing');
    expect(el.activeTab).toBe('pricing');
  });

  it('does not update activeTab when clicking current tab', () => {
    callMethod(el, 'onTabClick', 'flow');
    expect(el.activeTab).toBe('flow');
  });

  it('tab-change event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'pricing');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});
