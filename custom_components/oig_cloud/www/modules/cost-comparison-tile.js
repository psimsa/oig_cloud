class CostComparisonTile {
    constructor(container, payload, options = {}) {
        this.container = container;
        this.data = payload || {};
        this.summary = this.data.comparison || {};
        this.onOpenHybrid = options.onOpenHybrid;
        this.boundContainerClick = null;
        this.render();
    }

    update(payload) {
        this.data = payload || {};
        this.summary = this.data.comparison || {};
        this.render();
    }

    render() {
        if (!this.summary || !this.summary.plans) {
            this.container.innerHTML = `
                <div class="cost-card-placeholder">
                    <span class="cost-card-title">💰 Nákladový přehled</span>
                    <span class="cost-card-loading">Čekám na data…</span>
                </div>
            `;
            return;
        }

        const plans = this.summary.plans;
        const activePlan = plans['standard'] || {};

        this.container.classList.add('cost-card', 'cost-card-square', 'cost-card-compact');
        this.container.innerHTML = `
            ${this.renderHero(activePlan)}
            ${this.renderHistoryRows()}
        `;

        this.attachEvents();
    }

    renderHero(activePlan) {
        const total = this.formatCost(activePlan.total_cost);
        const actual = this.formatCost(activePlan.actual_cost);
        const future = this.formatCost(activePlan.future_plan_cost);
        const activePlanKeyForEvents = activePlan.plan_key || 'hybrid';
        const activeLabel = this.getPlanLabel(activePlanKeyForEvents);

        return `
            <div class="cost-hero-lite">
                <div class="cost-hero-main" data-plan="${activePlanKeyForEvents}">
                    <div class="cost-hero-label">Dnes · ${activeLabel}</div>
                    <div class="cost-hero-main-value">${total}</div>
                    <div class="cost-hero-breakdown">
                        <span>Utraceno ${actual}</span>
                        <span>Plán ${future}</span>
                    </div>
                </div>
            </div>
        `;
    }

    renderHistoryRows() {
        const yesterdaySource =
            this.summary.yesterday ||
            this.data?.hybrid?.yesterday ||
            null;
        const yesterdayActual = this.asNumber(yesterdaySource?.actual_total_cost);
        const yesterdayPlan = this.asNumber(yesterdaySource?.plan_total_cost);
        const yesterdayCost =
            yesterdayActual ??
            yesterdayPlan ??
            null;
        const yesterdayNote =
            yesterdayActual !== null
                ? 'skutečnost'
                : yesterdayPlan !== null
                    ? 'plán'
                    : '';
        const yesterdayPlanNote =
            yesterdayActual !== null && yesterdayPlan !== null && Math.round(yesterdayPlan) !== Math.round(yesterdayActual)
                ? `plán ${this.formatCost(yesterdayPlan)}`
                : '';
        const tomorrowCost = (this.summary.tomorrow || {})['standard'] ?? null;
        const tomorrowLabel = this.getPlanLabel('hybrid');
        const blocks = [
            this.renderHistoryCard('Včera', this.formatCost(yesterdayCost), yesterdayNote, yesterdayPlanNote),
            this.renderHistoryCard('Zítra', this.formatCost(tomorrowCost), tomorrowLabel)
        ];
        return `<div class="cost-history-grid">${blocks.join('')}</div>`;
    }

    renderHistoryCard(label, value, note, secondaryNote = '') {
        return `
            <div class="cost-history-card">
                <span class="cost-history-label">${label}</span>
                <span class="cost-history-value">${value}</span>
                ${note ? `<span class="cost-history-note">${note}</span>` : ''}
                ${secondaryNote ? `<span class="cost-history-note subtle">${secondaryNote}</span>` : ''}
            </div>
        `;
    }

    attachEvents() {
        const heroMain = this.container.querySelector('.cost-hero-main[data-plan]');

        const handleOpen = () => {
            if (typeof this.onOpenHybrid === 'function') {
                this.onOpenHybrid();
            }
        };

        if (heroMain) {
            heroMain.addEventListener('click', (e) => {
                e.stopPropagation();
                handleOpen();
            });
        }

        if (!this.boundContainerClick) {
            this.boundContainerClick = () => {
                handleOpen();
            };
            this.container.addEventListener('click', this.boundContainerClick);
        }
    }

    getPlanLabel(planKey) {
        const fallback = 'Standardní';  // Always hybrid
        const labels = window.PLAN_LABELS && window.PLAN_LABELS[planKey];
        if (!labels) {
            return fallback;
        }
        return labels.short || fallback;
    }

    formatCost(value) {
        if (value === undefined || value === null || Number.isNaN(value)) {
            return '--';
        }
        return `${Math.round(value)} Kč`;
    }

    asNumber(value) {
        if (value === undefined || value === null) {
            return null;
        }
        const parsed = Number(value);
        return Number.isNaN(parsed) ? null : parsed;
    }
}

window.CostComparisonTile = CostComparisonTile;
