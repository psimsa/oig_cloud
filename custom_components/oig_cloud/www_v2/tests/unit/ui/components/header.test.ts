import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OigHeader } from '@/ui/components/header';

function callMethod(el: OigHeader, name: string, ...args: unknown[]): unknown {
  const method = Reflect.get(el, name);
  if (typeof method !== 'function') throw new Error(`No method on header: ${name}`);
  return Reflect.apply(method, el, args);
}

describe('OigHeader — property defaults', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('title defaults to "Energetické Toky"', () => {
    expect(el.title).toBe('Energetické Toky');
  });

  it('time defaults to empty string', () => {
    expect(el.time).toBe('');
  });

  it('showStatus defaults to false', () => {
    expect(el.showStatus).toBe(false);
  });

  it('alertCount defaults to 0', () => {
    expect(el.alertCount).toBe(0);
  });

  it('leftPanelCollapsed defaults to false', () => {
    expect(el.leftPanelCollapsed).toBe(false);
  });

  it('rightPanelCollapsed defaults to false', () => {
    expect(el.rightPanelCollapsed).toBe(false);
  });
});

describe('OigHeader — onStatusClick()', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('dispatches a "status-click" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('status-click', handler);
    callMethod(el, 'onStatusClick');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('status-click event is a CustomEvent', () => {
    let received: Event | null = null;
    el.addEventListener('status-click', (e) => { received = e; });
    callMethod(el, 'onStatusClick');
    expect(received).toBeInstanceOf(CustomEvent);
  });

  it('status-click event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('status-click', handler);
    callMethod(el, 'onStatusClick');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigHeader — onEditClick()', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('dispatches a "edit-click" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('edit-click', handler);
    callMethod(el, 'onEditClick');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('edit-click event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('edit-click', handler);
    callMethod(el, 'onEditClick');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigHeader — onResetClick()', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('dispatches a "reset-click" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('reset-click', handler);
    callMethod(el, 'onResetClick');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('reset-click event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('reset-click', handler);
    callMethod(el, 'onResetClick');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigHeader — onToggleLeftPanel()', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('dispatches a "toggle-left-panel" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('toggle-left-panel', handler);
    callMethod(el, 'onToggleLeftPanel');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('toggle-left-panel event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('toggle-left-panel', handler);
    callMethod(el, 'onToggleLeftPanel');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigHeader — onToggleRightPanel()', () => {
  let el: OigHeader;

  beforeEach(() => {
    el = new OigHeader();
  });

  it('dispatches a "toggle-right-panel" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('toggle-right-panel', handler);
    callMethod(el, 'onToggleRightPanel');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('toggle-right-panel event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('toggle-right-panel', handler);
    callMethod(el, 'onToggleRightPanel');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigHeader — render(): showStatus=false omits status badge', () => {
  it('values[2] is null when showStatus is false', () => {
    const el = new OigHeader();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[2]).toBeNull();
  });
});

describe('OigHeader — render(): showStatus=true, alertCount=0 (OK state)', () => {
  let statusBadge: { values: unknown[] };

  beforeEach(() => {
    const el = new OigHeader();
    el.showStatus = true;
    el.alertCount = 0;
    const outer = el.render() as unknown as { values: unknown[] };
    statusBadge = outer.values[2] as { values: unknown[] };
  });

  it('status badge slot is not null', () => {
    expect(statusBadge).not.toBeNull();
  });

  it('status badge class value is "ok"', () => {
    expect(statusBadge.values[0]).toBe('ok');
  });

  it('status text value is "OK"', () => {
    expect(statusBadge.values[3]).toBe('OK');
  });

  it('count badge slot is null when alertCount is 0', () => {
    expect(statusBadge.values[2]).toBeNull();
  });
});

describe('OigHeader — render(): showStatus=true, alertCount>0 (warning state)', () => {
  let statusBadge: { values: unknown[] };

  beforeEach(() => {
    const el = new OigHeader();
    el.showStatus = true;
    el.alertCount = 3;
    const outer = el.render() as unknown as { values: unknown[] };
    statusBadge = outer.values[2] as { values: unknown[] };
  });

  it('status badge slot is not null', () => {
    expect(statusBadge).not.toBeNull();
  });

  it('status badge class value is "warning"', () => {
    expect(statusBadge.values[0]).toBe('warning');
  });

  it('status text value is "Výstrahy"', () => {
    expect(statusBadge.values[3]).toBe('Výstrahy');
  });

  it('count badge slot is not null when alertCount > 0', () => {
    expect(statusBadge.values[2]).not.toBeNull();
  });
});

describe('OigHeader — render(): panel collapsed active-class binding', () => {
  it('left button active value is "active" when leftPanelCollapsed=true', () => {
    const el = new OigHeader();
    el.leftPanelCollapsed = true;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[3]).toBe('active');
  });

  it('left button active value is "" when leftPanelCollapsed=false', () => {
    const el = new OigHeader();
    el.leftPanelCollapsed = false;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[3]).toBe('');
  });

  it('right button active value is "active" when rightPanelCollapsed=true', () => {
    const el = new OigHeader();
    el.rightPanelCollapsed = true;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[5]).toBe('active');
  });

  it('right button active value is "" when rightPanelCollapsed=false', () => {
    const el = new OigHeader();
    el.rightPanelCollapsed = false;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[5]).toBe('');
  });
});
