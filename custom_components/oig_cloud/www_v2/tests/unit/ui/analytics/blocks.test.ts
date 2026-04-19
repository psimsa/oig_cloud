import { describe, it, expect } from 'vitest';
import {
  OigAnalyticsBlock,
  OigBatteryEfficiency,
  OigBatteryHealth,
  OigBatteryBalancing,
  OigCostComparison,
} from '@/ui/features/analytics/blocks';
import type {
  BatteryEfficiencyData,
  BatteryHealthData,
  BatteryBalancingData,
  CostComparisonData,
} from '@/ui/features/analytics/types';

type TR = { values: unknown[] };

function renderValues(el: { render(): unknown }): unknown[] {
  return (el.render() as unknown as TR).values;
}

function callPrivate(el: object, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No method '${name}'`);
  return Reflect.apply(fn, el, args);
}

const EFFICIENCY: BatteryEfficiencyData = {
  efficiency: 92.5,
  charged: 5000,
  discharged: 4600,
  losses: 400,
  lossesPct: 8,
  trend: 2.5,
  period: 'current_month',
  currentMonthDays: 15,
  lastMonth: null,
  currentMonth: null,
};

const HEALTH: BatteryHealthData = {
  soh: 97.3,
  capacity: 9800,
  nominalCapacity: 10000,
  minCapacity: 9200,
  measurementCount: 42,
  lastAnalysis: '2026-04-17T10:00:00',
  qualityScore: 0.95,
  sohMethod: 'regression',
  sohMethodDescription: 'Linear regression',
  measurementHistory: [],
  degradation3m: 0.1,
  degradation6m: 0.2,
  degradation12m: 0.4,
  degradationPerYear: 0.4,
  estimatedEolDate: '2035-01-01',
  yearsTo80Pct: 9.5,
  trendConfidence: 0.9,
  status: 'excellent',
  statusLabel: 'Výborný',
};

const BALANCING: BatteryBalancingData = {
  status: 'OK',
  lastBalancing: '2026-03-01',
  cost: 150.5,
  nextScheduled: '2026-06-01',
  daysRemaining: 45,
  progressPercent: 50,
  intervalDays: 90,
  estimatedNextCost: 160,
};

const COST: CostComparisonData = {
  activePlan: 'spot',
  actualSpent: 280,
  planTotalCost: 300,
  futurePlanCost: 20,
  tomorrowCost: 15,
  yesterdayPlannedCost: 25,
  yesterdayActualCost: 22,
  yesterdayDelta: -3,
  yesterdayAccuracy: 88,
};

describe('OigAnalyticsBlock — property defaults', () => {
  it('title defaults to empty string', () => {
    expect(new OigAnalyticsBlock().title).toBe('');
  });

  it('icon defaults to 📊', () => {
    expect(new OigAnalyticsBlock().icon).toBe('📊');
  });
});

describe('OigAnalyticsBlock — render()', () => {
  it('values[0] is the icon', () => {
    const el = new OigAnalyticsBlock();
    el.icon = '⚡';
    expect(renderValues(el)[0]).toBe('⚡');
  });

  it('values[1] is the title', () => {
    const el = new OigAnalyticsBlock();
    el.title = 'My Block';
    expect(renderValues(el)[1]).toBe('My Block');
  });

  it('reflects updated title and icon', () => {
    const el = new OigAnalyticsBlock();
    el.icon = '🔋';
    el.title = 'Battery';
    const v = renderValues(el);
    expect(v[0]).toBe('🔋');
    expect(v[1]).toBe('Battery');
  });
});

describe('OigBatteryEfficiency — property defaults', () => {
  it('data defaults to null', () => {
    expect(new OigBatteryEfficiency().data).toBeNull();
  });
});

describe('OigBatteryEfficiency — render() with null data', () => {
  it('returns a loading template (no dynamic bindings)', () => {
    const el = new OigBatteryEfficiency();
    const v = renderValues(el);
    expect(v.length).toBe(0);
  });
});

describe('OigBatteryEfficiency — render() with data: efficiency and period', () => {
  it('values[0] contains formatted efficiency', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY };
    expect(renderValues(el)[0]).toBe('92.5 %');
  });

  it('values[1] is period label for current_month', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, period: 'current_month', currentMonthDays: 15 };
    expect(renderValues(el)[1]).toBe('Aktuální měsíc (15 dní)');
  });

  it('values[1] is period label for last_month', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, period: 'last_month' };
    expect(renderValues(el)[1]).toBe('Minulý měsíc');
  });
});

describe('OigBatteryEfficiency — render() trend comparison', () => {
  it('values[2] is a TemplateResult when trend !== 0', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: 2.5 };
    expect(renderValues(el)[2]).not.toBeNull();
  });

  it('values[2] is null when trend === 0', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: 0 };
    expect(renderValues(el)[2]).toBeNull();
  });

  it('comparison template uses positive class when trend >= 0', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: 1.0 };
    const comparison = (renderValues(el)[2] as TR);
    expect(comparison.values[0]).toBe('positive');
  });

  it('comparison template uses negative class when trend < 0', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: -1.5 };
    const comparison = (renderValues(el)[2] as TR);
    expect(comparison.values[0]).toBe('negative');
  });

  it('comparison template sign is "+" for positive trend', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: 3.0 };
    const comparison = (renderValues(el)[2] as TR);
    expect(comparison.values[1]).toBe('+');
  });

  it('comparison template sign is "" for negative trend', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, trend: -2.0 };
    const comparison = (renderValues(el)[2] as TR);
    expect(comparison.values[1]).toBe('');
  });
});

describe('OigBatteryEfficiency — render() stats grid', () => {
  it('values[3] is formatted charged energy', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, charged: 5000 };
    expect(renderValues(el)[3]).toBe('5.00 kWh');
  });

  it('values[4] is formatted discharged energy', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, discharged: 4600 };
    expect(renderValues(el)[4]).toBe('4.60 kWh');
  });

  it('values[5] is formatted losses energy', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, losses: 400 };
    expect(renderValues(el)[5]).toBe('400 Wh');
  });

  it('values[6] is TemplateResult when lossesPct is truthy', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, lossesPct: 8 };
    expect(renderValues(el)[6]).not.toBeNull();
  });

  it('values[6] is null when lossesPct is 0 (falsy)', () => {
    const el = new OigBatteryEfficiency();
    el.data = { ...EFFICIENCY, lossesPct: 0 };
    expect(renderValues(el)[6]).toBeNull();
  });
});

describe('OigBatteryHealth — property defaults', () => {
  it('data defaults to null', () => {
    expect(new OigBatteryHealth().data).toBeNull();
  });
});

describe('OigBatteryHealth — render() with null data', () => {
  it('returns a loading template (no dynamic bindings)', () => {
    const el = new OigBatteryHealth();
    expect(renderValues(el).length).toBe(0);
  });
});

describe('OigBatteryHealth — renderSparkline() private method', () => {
  it('returns null when measurementHistory is empty', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, measurementHistory: [] };
    expect(callPrivate(el, 'renderSparkline')).toBeNull();
  });

  it('returns null when measurementHistory has only 1 item', () => {
    const el = new OigBatteryHealth();
    el.data = {
      ...HEALTH,
      measurementHistory: [
        { timestamp: '2026-01-01', soh_percent: 97, capacity_kwh: 9.8, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
      ],
    };
    expect(callPrivate(el, 'renderSparkline')).toBeNull();
  });

  it('returns a TemplateResult when history has ≥ 2 items', () => {
    const el = new OigBatteryHealth();
    el.data = {
      ...HEALTH,
      measurementHistory: [
        { timestamp: '2026-01-01', soh_percent: 97, capacity_kwh: 9.8, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
        { timestamp: '2026-02-01', soh_percent: 96.5, capacity_kwh: 9.75, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
      ],
    };
    expect(callPrivate(el, 'renderSparkline')).not.toBeNull();
  });

  it('sparkline template encodes correct width/height', () => {
    const el = new OigBatteryHealth();
    el.data = {
      ...HEALTH,
      measurementHistory: [
        { timestamp: '2026-01-01', soh_percent: 97, capacity_kwh: 9.8, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
        { timestamp: '2026-02-01', soh_percent: 96, capacity_kwh: 9.7, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
      ],
    };
    const sparkline = callPrivate(el, 'renderSparkline') as TR;
    expect(sparkline.values[0]).toBe(200);
    expect(sparkline.values[1]).toBe(40);
  });

  it('sparkline points string is non-empty for 2+ history items', () => {
    const el = new OigBatteryHealth();
    el.data = {
      ...HEALTH,
      measurementHistory: [
        { timestamp: '2026-01-01', soh_percent: 97, capacity_kwh: 9.8, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
        { timestamp: '2026-02-01', soh_percent: 96, capacity_kwh: 9.7, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
      ],
    };
    const sparkline = callPrivate(el, 'renderSparkline') as TR;
    expect(typeof sparkline.values[2]).toBe('string');
    expect((sparkline.values[2] as string).length).toBeGreaterThan(0);
  });

  it('sparkline points start at x=0 for first item', () => {
    const el = new OigBatteryHealth();
    el.data = {
      ...HEALTH,
      measurementHistory: [
        { timestamp: '2026-01-01', soh_percent: 97, capacity_kwh: 9.8, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
        { timestamp: '2026-02-01', soh_percent: 96, capacity_kwh: 9.7, delta_soc: 0.5, charge_wh: 500, duration_hours: 2 },
      ],
    };
    const sparkline = callPrivate(el, 'renderSparkline') as TR;
    const points = sparkline.values[2] as string;
    expect(points.startsWith('0,')).toBe(true);
  });
});

describe('OigBatteryHealth — render() with data: status badge', () => {
  it('values[0] is the status class', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, status: 'good' };
    expect(renderValues(el)[0]).toBe('good');
  });

  it('values[1] is the statusLabel', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, statusLabel: 'Dobrý' };
    expect(renderValues(el)[1]).toBe('Dobrý');
  });
});

describe('OigBatteryHealth — render() with data: metrics', () => {
  it('values[3] is formatted SoH', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, soh: 97.3 };
    expect(renderValues(el)[3]).toBe('97.3 %');
  });

  it('values[4] is formatted capacity', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, capacity: 9800 };
    expect(renderValues(el)[4]).toBe('9.80 kWh');
  });

  it('values[5] is formatted min capacity', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, minCapacity: 9200 };
    expect(renderValues(el)[5]).toBe('9.20 kWh');
  });

  it('values[6] is formatted nominal capacity', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, nominalCapacity: 10000 };
    expect(renderValues(el)[6]).toBe('10.00 kWh');
  });

  it('values[7] is measurement count', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, measurementCount: 42 };
    expect(renderValues(el)[7]).toBe(42);
  });
});

describe('OigBatteryHealth — render() qualityScore conditional', () => {
  it('values[8] is TemplateResult when qualityScore != null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, qualityScore: 0.95 };
    expect(renderValues(el)[8]).not.toBeNull();
  });

  it('values[8] is null when qualityScore is null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, qualityScore: null };
    expect(renderValues(el)[8]).toBeNull();
  });
});

describe('OigBatteryHealth — render() degradation section', () => {
  it('values[9] is TemplateResult when degradation3m is set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: 0.1, degradation6m: null, degradation12m: null };
    expect(renderValues(el)[9]).not.toBeNull();
  });

  it('values[9] is TemplateResult when degradation6m is set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: null, degradation6m: 0.2, degradation12m: null };
    expect(renderValues(el)[9]).not.toBeNull();
  });

  it('values[9] is TemplateResult when degradation12m is set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: null, degradation6m: null, degradation12m: 0.4 };
    expect(renderValues(el)[9]).not.toBeNull();
  });

  it('values[9] is null when all degradation values are null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: null, degradation6m: null, degradation12m: null };
    expect(renderValues(el)[9]).toBeNull();
  });

  it('degradation section shows degradation3m metric when set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: 0.1 };
    const section = renderValues(el)[9] as TR;
    expect(section.values[0]).not.toBeNull();
  });

  it('degradation section hides 3m metric when null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: null, degradation6m: 0.2, degradation12m: null };
    const section = renderValues(el)[9] as TR;
    expect(section.values[0]).toBeNull();
  });

  it('degradation3m metric uses "negative" class when value > 0', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: 0.5 };
    const section = renderValues(el)[9] as TR;
    const metric3m = section.values[0] as TR;
    expect(metric3m.values[0]).toBe('negative');
  });

  it('degradation3m metric uses "" class when value <= 0', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradation3m: 0 };
    const section = renderValues(el)[9] as TR;
    const metric3m = section.values[0] as TR;
    expect(metric3m.values[0]).toBe('');
  });
});

describe('OigBatteryHealth — render() predictions section', () => {
  it('values[10] is TemplateResult when degradationPerYear is set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradationPerYear: 0.4, estimatedEolDate: null };
    expect(renderValues(el)[10]).not.toBeNull();
  });

  it('values[10] is TemplateResult when estimatedEolDate is set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradationPerYear: null, estimatedEolDate: '2035-01-01' };
    expect(renderValues(el)[10]).not.toBeNull();
  });

  it('values[10] is null when both degradationPerYear and estimatedEolDate are null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradationPerYear: null, estimatedEolDate: null };
    expect(renderValues(el)[10]).toBeNull();
  });

  it('prediction section shows degradationPerYear item when set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradationPerYear: 0.4 };
    const section = renderValues(el)[10] as TR;
    expect(section.values[0]).not.toBeNull();
  });

  it('prediction section hides degradationPerYear when null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, degradationPerYear: null, estimatedEolDate: '2035-01-01' };
    const section = renderValues(el)[10] as TR;
    expect(section.values[0]).toBeNull();
  });

  it('prediction section shows yearsTo80Pct when set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, yearsTo80Pct: 9.5 };
    const section = renderValues(el)[10] as TR;
    expect(section.values[1]).not.toBeNull();
  });

  it('prediction section hides yearsTo80Pct when null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, yearsTo80Pct: null };
    const section = renderValues(el)[10] as TR;
    expect(section.values[1]).toBeNull();
  });

  it('prediction section shows estimatedEolDate when set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, estimatedEolDate: '2035-01-01' };
    const section = renderValues(el)[10] as TR;
    expect(section.values[2]).not.toBeNull();
  });

  it('prediction section hides estimatedEolDate when null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, estimatedEolDate: null, degradationPerYear: 0.4 };
    const section = renderValues(el)[10] as TR;
    expect(section.values[2]).toBeNull();
  });

  it('prediction section shows trendConfidence when set', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, trendConfidence: 0.9 };
    const section = renderValues(el)[10] as TR;
    expect(section.values[3]).not.toBeNull();
  });

  it('prediction section hides trendConfidence when null', () => {
    const el = new OigBatteryHealth();
    el.data = { ...HEALTH, trendConfidence: null };
    const section = renderValues(el)[10] as TR;
    expect(section.values[3]).toBeNull();
  });
});

describe('OigBatteryBalancing — property defaults', () => {
  it('data defaults to null', () => {
    expect(new OigBatteryBalancing().data).toBeNull();
  });
});

describe('OigBatteryBalancing — render() with null data', () => {
  it('returns a loading template (no dynamic bindings)', () => {
    const el = new OigBatteryBalancing();
    expect(renderValues(el).length).toBe(0);
  });
});

describe('OigBatteryBalancing — getProgressClass() private method', () => {
  it('returns "ok" when percent is null', () => {
    const el = new OigBatteryBalancing();
    expect(callPrivate(el, 'getProgressClass', null)).toBe('ok');
  });

  it('returns "overdue" when percent >= 95', () => {
    const el = new OigBatteryBalancing();
    expect(callPrivate(el, 'getProgressClass', 95)).toBe('overdue');
    expect(callPrivate(el, 'getProgressClass', 100)).toBe('overdue');
  });

  it('returns "due-soon" when percent >= 80 and < 95', () => {
    const el = new OigBatteryBalancing();
    expect(callPrivate(el, 'getProgressClass', 80)).toBe('due-soon');
    expect(callPrivate(el, 'getProgressClass', 94)).toBe('due-soon');
  });

  it('returns "ok" when percent < 80', () => {
    const el = new OigBatteryBalancing();
    expect(callPrivate(el, 'getProgressClass', 0)).toBe('ok');
    expect(callPrivate(el, 'getProgressClass', 79)).toBe('ok');
  });
});

describe('OigBatteryBalancing — render() with data: metrics', () => {
  it('values[0] is data.status', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, status: 'Probíhá' };
    expect(renderValues(el)[0]).toBe('Probíhá');
  });

  it('values[1] is data.lastBalancing', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, lastBalancing: '2026-03-01' };
    expect(renderValues(el)[1]).toBe('2026-03-01');
  });

  it('values[2] is formatted cost', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, cost: 150.5 };
    expect(renderValues(el)[2]).toBe('150.50 CZK');
  });
});

describe('OigBatteryBalancing — render() conditionals', () => {
  it('values[3] is TemplateResult when nextScheduled is set', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, nextScheduled: '2026-06-01' };
    expect(renderValues(el)[3]).not.toBeNull();
  });

  it('values[3] is null when nextScheduled is null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, nextScheduled: null };
    expect(renderValues(el)[3]).toBeNull();
  });

  it('values[4] is TemplateResult when progressPercent is not null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: 50 };
    expect(renderValues(el)[4]).not.toBeNull();
  });

  it('values[4] is null when progressPercent is null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: null };
    expect(renderValues(el)[4]).toBeNull();
  });

  it('values[5] is TemplateResult when intervalDays is not null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, intervalDays: 90 };
    expect(renderValues(el)[5]).not.toBeNull();
  });

  it('values[5] is null when intervalDays is null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, intervalDays: null };
    expect(renderValues(el)[5]).toBeNull();
  });

  it('values[6] is TemplateResult when estimatedNextCost is not null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, estimatedNextCost: 160 };
    expect(renderValues(el)[6]).not.toBeNull();
  });

  it('values[6] is null when estimatedNextCost is null', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, estimatedNextCost: null };
    expect(renderValues(el)[6]).toBeNull();
  });
});

describe('OigBatteryBalancing — progress bar class via getProgressClass', () => {
  it('progress bar inner template shows overdue class at 95%', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: 95 };
    const progress = renderValues(el)[4] as TR;
    expect(progress.values[1]).toBe('overdue');
  });

  it('progress bar inner template shows due-soon class at 80%', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: 80 };
    const progress = renderValues(el)[4] as TR;
    expect(progress.values[1]).toBe('due-soon');
  });

  it('progress bar inner template shows ok class at 50%', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: 50 };
    const progress = renderValues(el)[4] as TR;
    expect(progress.values[1]).toBe('ok');
  });

  it('progress bar width reflects progressPercent', () => {
    const el = new OigBatteryBalancing();
    el.data = { ...BALANCING, progressPercent: 65 };
    const progress = renderValues(el)[4] as TR;
    expect(String(progress.values[progress.values.length - 1])).toContain('65');
  });
});

describe('OigCostComparison — property defaults', () => {
  it('data defaults to null', () => {
    expect(new OigCostComparison().data).toBeNull();
  });
});

describe('OigCostComparison — render() with null data', () => {
  it('returns a loading template (no dynamic bindings)', () => {
    const el = new OigCostComparison();
    expect(renderValues(el).length).toBe(0);
  });
});

describe('OigCostComparison — render() with data: cost rows', () => {
  it('values[0] is formatted actual spent', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, actualSpent: 280 };
    expect(renderValues(el)[0]).toBe('280.00 CZK');
  });

  it('values[1] is formatted plan total cost', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, planTotalCost: 300 };
    expect(renderValues(el)[1]).toBe('300.00 CZK');
  });

  it('values[2] is formatted future plan cost', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, futurePlanCost: 20 };
    expect(renderValues(el)[2]).toBe('20.00 CZK');
  });
});

describe('OigCostComparison — render() tomorrowCost conditional', () => {
  it('values[3] is TemplateResult when tomorrowCost is not null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, tomorrowCost: 15 };
    expect(renderValues(el)[3]).not.toBeNull();
  });

  it('values[3] is null when tomorrowCost is null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, tomorrowCost: null };
    expect(renderValues(el)[3]).toBeNull();
  });
});

describe('OigCostComparison — render() yesterday section conditional', () => {
  it('values[4] is TemplateResult when yesterdayActualCost is not null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayActualCost: 22 };
    expect(renderValues(el)[4]).not.toBeNull();
  });

  it('values[4] is null when yesterdayActualCost is null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayActualCost: null };
    expect(renderValues(el)[4]).toBeNull();
  });

  it('yesterday section shows planned cost when available', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayPlannedCost: 25 };
    const section = renderValues(el)[4] as TR;
    expect(section.values[0]).toBe('25.00 CZK');
  });

  it('yesterday section shows "—" when plannedCost is null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayPlannedCost: null };
    const section = renderValues(el)[4] as TR;
    expect(section.values[0]).toBe('—');
  });

  it('yesterday section always shows actual cost', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayActualCost: 22 };
    const section = renderValues(el)[4] as TR;
    expect(section.values[1]).toBe('22.00 CZK');
  });

  it('yesterday section shows delta when not null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: -3 };
    const section = renderValues(el)[4] as TR;
    expect(section.values[2]).not.toBeNull();
  });

  it('yesterday section hides delta when null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: null };
    const section = renderValues(el)[4] as TR;
    expect(section.values[2]).toBeNull();
  });

  it('yesterday section shows accuracy when not null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayAccuracy: 88 };
    const section = renderValues(el)[4] as TR;
    expect(section.values[3]).not.toBeNull();
  });

  it('yesterday section hides accuracy when null', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayAccuracy: null };
    const section = renderValues(el)[4] as TR;
    expect(section.values[3]).toBeNull();
  });
});

describe('OigCostComparison — delta class logic', () => {
  it('delta uses delta-positive class when value <= 0 (savings)', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: -3 };
    const section = renderValues(el)[4] as TR;
    const deltaTemplate = section.values[2] as TR;
    expect(deltaTemplate.values[0]).toBe('delta-positive');
  });

  it('delta uses delta-negative class when value > 0 (overspend)', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: 5 };
    const section = renderValues(el)[4] as TR;
    const deltaTemplate = section.values[2] as TR;
    expect(deltaTemplate.values[0]).toBe('delta-negative');
  });

  it('delta uses delta-positive class when value is exactly 0', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: 0 };
    const section = renderValues(el)[4] as TR;
    const deltaTemplate = section.values[2] as TR;
    expect(deltaTemplate.values[0]).toBe('delta-positive');
  });

  it('delta sign is "+" when delta >= 0', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: 5 };
    const section = renderValues(el)[4] as TR;
    const deltaTemplate = section.values[2] as TR;
    expect(deltaTemplate.values[1]).toBe('+');
  });

  it('delta sign is "" when delta < 0', () => {
    const el = new OigCostComparison();
    el.data = { ...COST, yesterdayDelta: -3 };
    const section = renderValues(el)[4] as TR;
    const deltaTemplate = section.values[2] as TR;
    expect(deltaTemplate.values[1]).toBe('');
  });
});
