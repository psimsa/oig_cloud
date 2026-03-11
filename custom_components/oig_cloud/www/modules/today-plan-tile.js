/**
 * Today Plan Tile Component
 *
 * Dlaždice "Dnes - Plnění plánu" s mini grafem variance chart
 * Zobrazuje průběžné plnění plánu a EOD predikci
 *
 * Phase 2.9 - Implementace dle PLAN_VS_ACTUAL_UX_REDESIGN.md
 *
 * @version 1.0.0
 * @author OIG Cloud Team
 * @status IMPLEMENTOVÁNO - NEZASAZENO (čeká na review)
 */
/* global Chart */

class TodayPlanTile {
    /**
     * @param {HTMLElement} container - Container element pro dlaždici
     * @param {Object} data - Data z API (today_tile_summary)
     * @param {Function} onClickHandler - Handler pro kliknutí na dlaždici
     */
    constructor(container, data, onClickHandler = null) {
        this.container = container;
        this.data = data;
        this.onClickHandler = onClickHandler;
        this.chart = null;

        this.render();
    }

    /**
     * Hlavní render metoda - vykreslí dlaždici ve stat-card stylu
     */
    render() {
        if (!this.data) {
            this.renderEmpty();
            return;
        }

        const {
            planned_so_far,
            actual_so_far,
            delta,
            delta_pct,
            eod_prediction
        } = this.data;
        const deltaIcon = delta < 0 ? '↓' : (delta > 0 ? '↑' : '→');

        // Barva podle výsledku (zelená = lepší, červená = horší)
        const tileColor = delta < 0 ? '#4CAF50' : '#2196F3'; // Zelená nebo modrá
        const bgGradient = delta < 0
            ? 'linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.05) 100%)'
            : 'linear-gradient(135deg, rgba(33, 150, 243, 0.15) 0%, rgba(33, 150, 243, 0.05) 100%)';
        const borderColor = delta < 0 ? 'rgba(76, 175, 80, 0.3)' : 'rgba(33, 150, 243, 0.3)';

        // Vytvořit HTML ve stat-card stylu
        this.container.style.background = bgGradient;
        this.container.style.border = `1px solid ${borderColor}`;

        this.container.innerHTML = `
            <div class="stat-label" style="color: ${tileColor}; font-weight: 600;">
                📆 Dnes - Plnění plánu
            </div>
            <div class="stat-value" style="font-size: 1.8em; margin: 10px 0;">
                ${actual_so_far.toFixed(1)} Kč
            </div>
            <div style="font-size: 0.85em; color: var(--text-secondary); margin-bottom: 8px; min-height: 20px;">
                ${deltaIcon} ${Math.abs(delta).toFixed(1)} Kč (${delta_pct > 0 ? '+' : ''}${delta_pct.toFixed(1)}%)
                <br>
                <span style="font-size: 0.9em; opacity: 0.8;">Plán: ${planned_so_far.toFixed(1)} Kč • EOD: ${eod_prediction.toFixed(1)} Kč</span>
            </div>
            <canvas id="today-mini-chart" style="height: 40px; max-height: 40px; margin-top: auto; display: block;"></canvas>
        `;

        // Vykreslit mini chart
        this.renderMiniChart();

        // Přidat click handler
        if (this.onClickHandler) {
            this.container.style.cursor = 'pointer';
            this.container.onclick = this.onClickHandler;
        }
    }

    /**
     * Vykreslí prázdnou dlaždici pokud nejsou data
     */
    renderEmpty() {
        this.container.innerHTML = `
            <div class="stat-label" style="color: var(--text-tertiary); font-weight: 600;">
                📆 Dnes - Plnění plánu
            </div>
            <div class="stat-value" style="font-size: 1.2em; margin: 20px 0; color: var(--text-tertiary);">
                ⏳ Načítání...
            </div>
            <div style="font-size: 0.85em; color: var(--text-secondary); text-align: center;">
                Data budou k dispozici po prvním 15min intervalu.
            </div>
        `;
    }

    /**
     * Vykreslí mini variance chart s Chart.js
     */
    renderMiniChart() {
        const canvas = document.getElementById('today-mini-chart');
        if (!canvas) {
            console.warn('⚠️ Canvas #today-mini-chart not found');
            return;
        }

        const chartData = this.data.mini_chart_data || [];
        if (chartData.length === 0) {
            this.renderEmptyChart(canvas);
            return;
        }

        const ctx = canvas.getContext('2d');

        const { labels, data, colors, nowIndex } = this.buildMiniChartData(chartData);

        // Zničit existující chart pokud je
        if (this.chart) {
            this.chart.destroy();
        }

        // Vytvořit nový chart
        this.chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors,
                    borderWidth: 0,
                    barPercentage: 0.9,
                    categoryPercentage: 0.95
                }]
            },
            options: this.buildMiniChartOptions(chartData, nowIndex)
        });
    }

    buildMiniChartData(chartData) {
        const labels = chartData.map(d => d.time.substring(11, 16));
        const data = chartData.map(d => d.delta);

        const colors = chartData.map(d => {
            if (!d.is_historical) {
                return 'rgba(200, 200, 200, 0.5)';
            }

            if (d.delta === null) {
                return 'rgba(200, 200, 200, 0.7)';
            }

            return d.delta < 0
                ? 'rgba(76, 175, 80, 0.8)'
                : 'rgba(244, 67, 54, 0.8)';
        });

        return {
            labels,
            data,
            colors,
            nowIndex: chartData.findIndex(d => d.is_current)
        };
    }

    buildMiniChartOptions(chartData, nowIndex) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: true,
                    callbacks: {
                        title: (context) => {
                            const index = context[0].dataIndex;
                            const item = chartData[index];
                            return item.time.substring(11, 16);
                        },
                        label: (context) => {
                            const index = context.dataIndex;
                            const item = chartData[index];

                            if (!item.is_historical) {
                                return 'Plán (ještě nenastalo)';
                            }

                            if (item.delta === null) {
                                return 'Chybí actual data';
                            }

                            const value = context.parsed.y;
                            const sign = value < 0 ? '' : '+';
                            return `Odchylka: ${sign}${value.toFixed(2)} Kč`;
                        }
                    }
                },
                annotation: nowIndex >= 0 ? {
                    annotations: {
                        nowLine: {
                            type: 'line',
                            xMin: nowIndex - 0.5,
                            xMax: nowIndex - 0.5,
                            borderColor: 'rgb(255, 99, 132)',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            label: {
                                content: 'NOW',
                                enabled: true,
                                position: 'top',
                                backgroundColor: 'rgb(255, 99, 132)',
                                color: 'white',
                                font: {
                                    size: 10,
                                    weight: 'bold'
                                }
                            }
                        }
                    }
                } : undefined
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        display: false
                    },
                    ticks: {
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                        font: {
                            size: 9
                        }
                    }
                },
                y: {
                    display: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        callback: (value) => {
                            const sign = value < 0 ? '' : '+';
                            return `${sign}${value.toFixed(1)}`;
                        },
                        font: {
                            size: 9
                        }
                    }
                }
            }
        };
    }

    /**
     * Vykreslí prázdný chart jako placeholder
     */
    renderEmptyChart(canvas) {
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f5f5f5';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#999';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Žádná data pro graf', canvas.width / 2, canvas.height / 2);
    }

    /**
     * Aktualizovat data a překreslit
     * @param {Object} newData - Nová data z API
     */
    update(newData) {
        this.data = newData;
        this.render();
    }

    /**
     * Zničit komponentu a uvolnit resources
     */
    destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        if (this.container) {
            this.container.innerHTML = '';
        }
    }
}

// Export pro použití v dashboard
window.TodayPlanTile = TodayPlanTile;

export default TodayPlanTile;
