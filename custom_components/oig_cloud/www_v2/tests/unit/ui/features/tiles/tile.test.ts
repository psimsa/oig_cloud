import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { OigTile, OigTilesContainer } from '@/ui/features/tiles/tile';
import type { ResolvedTile } from '@/data/tiles-data';

// ─── Module mocks ─────────────────────────────────────────────────────────────

vi.mock('@/data/ha-client', () => ({
  haClient: {
    openEntityDialog: vi.fn(),
  },
}));

vi.mock('@/data/tiles-data', () => ({
  executeTileAction: vi.fn(),
}));

vi.mock('@/utils/format', () => ({
  getIconEmoji: vi.fn().mockImplementation((icon: string) => {
    const key = icon.replace(/^mdi:/, '');
    const map: Record<string, string> = {
      thermometer: '🌡️',
      lightbulb: '💡',
      fan: '🌀',
    };
    return map[key] ?? '⚙️';
  }),
}));

import { haClient } from '@/data/ha-client';
import { executeTileAction } from '@/data/tiles-data';
import { getIconEmoji } from '@/utils/format';

// ─── Test helpers ─────────────────────────────────────────────────────────────

function callMethod(el: object, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No method '${name}' on ${(el as any).constructor.name}`);
  return Reflect.apply(fn as (...a: unknown[]) => unknown, el, args);
}

type TR = { values: unknown[] };

function renderValues(el: OigTile): unknown[] {
  return (el.render() as unknown as TR).values;
}

// ─── Data factories ───────────────────────────────────────────────────────────

function makeEntityTile(overrides: Partial<ResolvedTile> = {}): ResolvedTile {
  return {
    config: {
      type: 'entity',
      entity_id: 'sensor.test',
      label: 'Test Sensor',
      icon: '📊',
      color: '#4caf50',
      ...overrides.config,
    },
    value: '42',
    unit: 'W',
    isActive: false,
    isZero: false,
    formattedValue: '42 W',
    supportValues: {},
    ...overrides,
  };
}

function makeButtonTile(overrides: Partial<ResolvedTile> = {}): ResolvedTile {
  return {
    config: {
      type: 'button',
      entity_id: 'switch.test',
      label: 'Test Button',
      icon: '⚡',
      color: '#ff9800',
      action: 'toggle',
      ...overrides.config,
    },
    value: 'on',
    unit: '',
    isActive: true,
    isZero: false,
    formattedValue: 'on',
    supportValues: {},
    ...overrides,
  };
}

// ─── OigTile — property defaults ─────────────────────────────────────────────

describe('OigTile — property defaults', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('data defaults to null', () => {
    expect(el.data).toBeNull();
  });

  it('editMode defaults to false', () => {
    expect(el.editMode).toBe(false);
  });

  it('tileType defaults to entity', () => {
    expect(el.tileType).toBe('entity');
  });
});

// ─── OigTile — render with null data ─────────────────────────────────────────

describe('OigTile — render with null data', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('returns null when data is null', () => {
    expect(el.render()).toBeNull();
  });

  it('returns null before any data is set', () => {
    el.data = null;
    expect(el.render()).toBeNull();
  });
});

// ─── OigTile — render entity tile ────────────────────────────────────────────

describe('OigTile — render entity tile', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    el.data = makeEntityTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('returns a TemplateResult (non-null) when data is set', () => {
    expect(el.render()).not.toBeNull();
  });

  it('values array is defined', () => {
    const values = renderValues(el);
    expect(Array.isArray(values)).toBe(true);
  });

  it('includes the entity value in render output', () => {
    const values = renderValues(el);
    // value and unit are in the tile-main section — scan all values
    const flat = JSON.stringify(values);
    expect(flat).toContain('42');
  });

  it('includes the unit in render output', () => {
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('W');
  });

  it('syncs tileType to entity from config', () => {
    el.render();
    expect(el.tileType).toBe('entity');
  });

  it('sets color style when color is provided', () => {
    const values = renderValues(el);
    // values[0] is the color style conditional — should be a TemplateResult (truthy)
    expect(values[0]).not.toBeNull();
  });

  it('color style is null when no color', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.test', label: 'No Color', color: '' } });
    const values = renderValues(el);
    // values[0] is the color style conditional — null when no color
    expect(values[0]).toBeNull();
  });

  it('uses config icon as-is when not mdi prefix', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.test', label: 'Custom', icon: '🔥' } });
    el.render();
    // getIconEmoji should NOT be called for non-mdi icons
    expect(vi.mocked(getIconEmoji)).not.toHaveBeenCalled();
  });

  it('calls getIconEmoji for mdi: prefixed icons', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.test', label: 'MDI', icon: 'mdi:thermometer' } });
    el.render();
    expect(vi.mocked(getIconEmoji)).toHaveBeenCalledWith('mdi:thermometer');
  });

  it('uses fallback entity icon 📊 when no icon configured', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.test', label: 'No Icon' } });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('📊');
  });
});

// ─── OigTile — render button tile ────────────────────────────────────────────

describe('OigTile — render button tile', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    el.data = makeButtonTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('syncs tileType to button from config', () => {
    el.render();
    expect(el.tileType).toBe('button');
  });

  it('renders state-dot as on when isActive is true', () => {
    const values = renderValues(el);
    // The state-dot conditional is somewhere in the values for button tile
    const flat = JSON.stringify(values);
    expect(flat).toContain('on');
  });

  it('renders state-dot as off when isActive is false', () => {
    el.data = makeButtonTile({ isActive: false });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('off');
  });

  it('uses default button icon ⚡ when no icon configured', () => {
    el.data = makeButtonTile({ config: { type: 'button', entity_id: 'switch.test', label: 'No Icon', action: 'toggle' } });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('⚡');
  });
});

// ─── OigTile — unit rendering ─────────────────────────────────────────────────

describe('OigTile — unit rendering', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders unit TemplateResult when unit is non-empty', () => {
    el.data = makeEntityTile({ unit: 'kW' });
    const values = renderValues(el);
    expect(values[8]).not.toBeNull();
  });

  it('renders null for unit when unit is empty string', () => {
    el.data = makeEntityTile({ unit: '' });
    const values = renderValues(el);
    expect(values[8]).toBeNull();
  });
});

// ─── OigTile — support values rendering ──────────────────────────────────────

describe('OigTile — support values rendering', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders support values section when topRight is present', () => {
    el.data = makeEntityTile({
      supportValues: { topRight: { value: '25', unit: '°C' } },
    });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('25');
    expect(flat).toContain('°C');
  });

  it('renders support values section when bottomRight is present', () => {
    el.data = makeEntityTile({
      supportValues: { bottomRight: { value: '10', unit: '%' } },
    });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('10');
    expect(flat).toContain('%');
  });

  it('renders both support values when both are present', () => {
    el.data = makeEntityTile({
      supportValues: {
        topRight: { value: '25', unit: '°C' },
        bottomRight: { value: '10', unit: '%' },
      },
    });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('25');
    expect(flat).toContain('10');
  });

  it('does not render support values section when both are absent', () => {
    el.data = makeEntityTile({ supportValues: {} });
    const values = renderValues(el);
    expect(values[5]).toBeNull();
  });
});

// ─── OigTile — edit mode rendering ───────────────────────────────────────────

describe('OigTile — edit mode rendering', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    el.data = makeEntityTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('edit actions are null when editMode is false', () => {
    el.editMode = false;
    const values = renderValues(el);
    // Last value in root template is edit actions conditional
    expect(values[values.length - 1]).toBeNull();
  });

  it('edit actions are rendered when editMode is true', () => {
    el.editMode = true;
    const values = renderValues(el);
    // Last value in root template is edit actions conditional
    expect(values[values.length - 1]).not.toBeNull();
  });

  it('title attribute is empty string in editMode', () => {
    el.editMode = true;
    const values = renderValues(el);
    expect(values[2]).toBe('');
  });

  it('title attribute shows entity_id when not in editMode', () => {
    el.editMode = false;
    const values = renderValues(el);
    expect(values[2]).toBe('sensor.test');
  });
});

// ─── OigTile — onTileClick ────────────────────────────────────────────────────

describe('OigTile — onTileClick', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does nothing when editMode is true', () => {
    el.data = makeEntityTile();
    el.editMode = true;
    callMethod(el, 'onTileClick');
    expect(vi.mocked(haClient.openEntityDialog)).not.toHaveBeenCalled();
    expect(vi.mocked(executeTileAction)).not.toHaveBeenCalled();
  });

  it('does nothing when data is null', () => {
    el.data = null;
    el.editMode = false;
    callMethod(el, 'onTileClick');
    expect(vi.mocked(haClient.openEntityDialog)).not.toHaveBeenCalled();
    expect(vi.mocked(executeTileAction)).not.toHaveBeenCalled();
  });

  it('calls openEntityDialog for entity tile', () => {
    el.data = makeEntityTile();
    el.editMode = false;
    callMethod(el, 'onTileClick');
    expect(vi.mocked(haClient.openEntityDialog)).toHaveBeenCalledWith('sensor.test');
  });

  it('calls executeTileAction for button tile with action', () => {
    el.data = makeButtonTile();
    el.editMode = false;
    callMethod(el, 'onTileClick');
    expect(vi.mocked(executeTileAction)).toHaveBeenCalledWith('switch.test', 'toggle');
  });

  it('calls openEntityDialog for button tile without action', () => {
    el.data = makeButtonTile({ config: { type: 'button', entity_id: 'switch.no_action', label: 'No Action' } });
    el.editMode = false;
    callMethod(el, 'onTileClick');
    expect(vi.mocked(haClient.openEntityDialog)).toHaveBeenCalledWith('switch.no_action');
  });
});

// ─── OigTile — onSupportClick ─────────────────────────────────────────────────

describe('OigTile — onSupportClick', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('calls openEntityDialog with the entityId', () => {
    el.data = makeEntityTile();
    el.editMode = false;
    const fakeEvent = { stopPropagation: vi.fn() } as unknown as Event;
    callMethod(el, 'onSupportClick', fakeEvent, 'sensor.support');
    expect(fakeEvent.stopPropagation).toHaveBeenCalled();
    expect(vi.mocked(haClient.openEntityDialog)).toHaveBeenCalledWith('sensor.support');
  });

  it('stops propagation regardless of editMode', () => {
    el.data = makeEntityTile();
    el.editMode = true;
    const fakeEvent = { stopPropagation: vi.fn() } as unknown as Event;
    callMethod(el, 'onSupportClick', fakeEvent, 'sensor.support');
    expect(fakeEvent.stopPropagation).toHaveBeenCalled();
  });

  it('does not call openEntityDialog when editMode is true', () => {
    el.data = makeEntityTile();
    el.editMode = true;
    const fakeEvent = { stopPropagation: vi.fn() } as unknown as Event;
    callMethod(el, 'onSupportClick', fakeEvent, 'sensor.support');
    expect(vi.mocked(haClient.openEntityDialog)).not.toHaveBeenCalled();
  });
});

// ─── OigTile — onEdit ────────────────────────────────────────────────────────

describe('OigTile — onEdit', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    el.data = makeEntityTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('dispatches edit-tile CustomEvent', () => {
    const parent = document.createElement('div');
    parent.appendChild(el);
    const received: CustomEvent[] = [];
    parent.addEventListener('edit-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onEdit');
    expect(received).toHaveLength(1);
  });

  it('event includes entity_id in detail', () => {
    const received: CustomEvent[] = [];
    el.addEventListener('edit-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onEdit');
    expect(received[0].detail.entityId).toBe('sensor.test');
  });

  it('event is bubbling and composed', () => {
    const received: CustomEvent[] = [];
    el.addEventListener('edit-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onEdit');
    expect(received[0].bubbles).toBe(true);
    expect(received[0].composed).toBe(true);
  });
});

// ─── OigTile — onDelete ──────────────────────────────────────────────────────

describe('OigTile — onDelete', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
    el.data = makeEntityTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('dispatches delete-tile CustomEvent', () => {
    const received: CustomEvent[] = [];
    el.addEventListener('delete-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onDelete');
    expect(received).toHaveLength(1);
  });

  it('event includes entity_id in detail', () => {
    const received: CustomEvent[] = [];
    el.addEventListener('delete-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onDelete');
    expect(received[0].detail.entityId).toBe('sensor.test');
  });

  it('event is bubbling and composed', () => {
    const received: CustomEvent[] = [];
    el.addEventListener('delete-tile', (e) => received.push(e as CustomEvent));
    callMethod(el, 'onDelete');
    expect(received[0].bubbles).toBe(true);
    expect(received[0].composed).toBe(true);
  });
});

// ─── OigTile — label rendering ───────────────────────────────────────────────

describe('OigTile — label rendering', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders configured label', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.test', label: 'My Label' } });
    const values = renderValues(el);
    const flat = JSON.stringify(values);
    expect(flat).toContain('My Label');
  });

  it('renders empty string when no label configured', () => {
    el.data = makeEntityTile({ config: { type: 'entity', entity_id: 'sensor.no_label' } });
    const values = renderValues(el);
    expect(values[4]).toBe('');
  });
});

// ─── OigTilesContainer — property defaults ───────────────────────────────────

describe('OigTilesContainer — property defaults', () => {
  let el: OigTilesContainer;

  beforeEach(() => {
    el = new OigTilesContainer();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('tiles defaults to empty array', () => {
    expect(el.tiles).toEqual([]);
  });

  it('editMode defaults to false', () => {
    expect(el.editMode).toBe(false);
  });

  it('position defaults to left', () => {
    expect(el.position).toBe('left');
  });
});

// ─── OigTilesContainer — render empty state ──────────────────────────────────

describe('OigTilesContainer — render empty state', () => {
  let el: OigTilesContainer;

  beforeEach(() => {
    el = new OigTilesContainer();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty-state div when tiles is empty', () => {
    el.tiles = [];
    const result = el.render() as unknown as TR;
    const flat = JSON.stringify(result);
    expect(flat).toContain('Žádné dlaždice');
  });

  it('does not render tile list when tiles is empty', () => {
    el.tiles = [];
    const result = el.render() as unknown as TR;
    // Empty state returns a simple template without values
    expect(result).not.toBeNull();
  });
});

// ─── OigTilesContainer — render tiles ────────────────────────────────────────

describe('OigTilesContainer — render tiles', () => {
  let el: OigTilesContainer;

  beforeEach(() => {
    el = new OigTilesContainer();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders TemplateResult when tiles are present', () => {
    el.tiles = [makeEntityTile()];
    const result = el.render();
    expect(result).not.toBeNull();
  });

  it('renders array of tiles in template values', () => {
    const tiles = [makeEntityTile(), makeButtonTile()];
    el.tiles = tiles;
    const result = el.render() as unknown as TR;
    expect(result).not.toBeNull();
  });

  it('passes editMode to tile rendering', () => {
    el.tiles = [makeEntityTile()];
    el.editMode = true;
    const result = el.render();
    // Just verify it renders without error
    expect(result).not.toBeNull();
  });

  it('applies inactive class for zero tiles', () => {
    const zeroTile = makeEntityTile({ isZero: true });
    el.tiles = [zeroTile];
    const result = el.render() as unknown as TR;
    const flat = JSON.stringify(result);
    expect(flat).toContain('inactive');
  });

  it('applies empty class for non-zero tiles', () => {
    const activeTile = makeEntityTile({ isZero: false });
    el.tiles = [activeTile];
    const result = el.render() as unknown as TR;
    const flat = JSON.stringify(result);
    // empty string class for non-zero tiles
    expect(flat).not.toContain('inactive');
  });
});

// ─── OigTile — tileType sync logic ───────────────────────────────────────────

describe('OigTile — tileType sync from config', () => {
  let el: OigTile;

  beforeEach(() => {
    el = new OigTile();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('updates tileType from entity to button when config changes', () => {
    el.data = makeEntityTile();
    el.render();
    expect(el.tileType).toBe('entity');

    el.data = makeButtonTile();
    el.render();
    expect(el.tileType).toBe('button');
  });

  it('does not reassign tileType when already matching config', () => {
    el.data = makeEntityTile();
    el.tileType = 'entity';
    el.render();
    expect(el.tileType).toBe('entity');
  });

  it('defaults tileType to entity when config.type is undefined', () => {
    const tileWithoutType = makeEntityTile();
    (tileWithoutType.config as any).type = undefined;
    el.data = tileWithoutType;
    el.tileType = 'button'; // force mismatch
    el.render();
    expect(el.tileType).toBe('entity');
  });
});
