class OigBatteryForecastCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.chart = null;
    }

    setConfig(config) {
        if (!config.entity) {
            throw new Error('You need to define an entity');
        }
        this.config = config;
    }

    set hass(hass) {
        this._hass = hass;
        this.updateChart();
    }

    connectedCallback() {
        this.render();
        this.loadChartsLibrary();
    }

    async loadChartsLibrary() {
        try {
            // Načtení chart loaderu pokud není dostupný
            if (!window.ApexChartsLoader) {
                await this.loadScript('/oig_cloud_static/chart-loader.js');
            }

            // Zobrazení loading stavu
            this.showLoading('Načítání grafu...');

            // Načtení Apex Charts pomocí CDN loaderu
            await window.ApexChartsLoader.load();

            // Inicializace grafu
            this.initChart();

        } catch (error) {
            console.error('Chyba při načítání Apex Charts:', error);
            this.showError('Graf není dostupný - problém s načítáním z CDN');
        }
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${src}"]`)) {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            script.onload = resolve;
            script.onerror = () => reject(new Error(`Failed to load ${src}`));
            document.head.appendChild(script);
        });
    }

    showLoading(message) {
        const chartContainer = this.shadowRoot.querySelector('#chart');
        if (chartContainer) {
            chartContainer.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: center; height: 400px;
                           color: var(--primary-text-color); text-align: center; flex-direction: column;">
                    <ha-icon icon="mdi:loading" class="spinning" style="font-size: 48px; margin-bottom: 16px;"></ha-icon>
                    <div>${message}</div>
                </div>
                <style>
                    .spinning {
                        animation: spin 1s linear infinite;
                    }
                    @keyframes spin {
                        from { transform: rotate(0deg); }
                        to { transform: rotate(360deg); }
                    }
                </style>
            `;
        }
    }

    showError(message) {
        const chartContainer = this.shadowRoot.querySelector('#chart');
        if (chartContainer) {
            chartContainer.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: center; height: 400px;
                           color: var(--error-color, #f44336); text-align: center; flex-direction: column;">
                    <ha-icon icon="mdi:alert-circle" style="font-size: 48px; margin-bottom: 16px;"></ha-icon>
                    <div style="font-weight: 500; margin-bottom: 8px;">Graf není k dispozici</div>
                    <div style="font-size: 0.9em; opacity: 0.8;">${message}</div>
                    <button style="margin-top: 16px; padding: 8px 16px; border: 1px solid var(--error-color);
                                  background: transparent; color: var(--error-color); border-radius: 4px; cursor: pointer;"
                            onclick="this.getRootNode().host.loadChartsLibrary()">
                        Zkusit znovu
                    </button>
                </div>
            `;
        }
    }

    render() {
        this.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                    padding: 16px;
                }
                .card-header {
                    display: flex;
                    align-items: center;
                    margin-bottom: 16px;
                }
                .card-title {
                    font-size: 1.2em;
                    font-weight: 500;
                    margin: 0;
                }
                .card-icon {
                    margin-right: 8px;
                    color: var(--primary-color);
                }
                #chart {
                    width: 100%;
                    height: 400px;
                }
                .legend {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 16px;
                    margin-top: 12px;
                    font-size: 0.9em;
                }
                .legend-item {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }
                .legend-color {
                    width: 12px;
                    height: 12px;
                    border-radius: 2px;
                }
                .stats {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 12px;
                    margin-top: 16px;
                }
                .stat-item {
                    background: var(--card-background-color, #fff);
                    border: 1px solid var(--divider-color, #e0e0e0);
                    border-radius: 4px;
                    padding: 8px;
                    text-align: center;
                }
                .stat-value {
                    font-size: 1.1em;
                }
                .stat-label {
                    font-size: 0.8em;
                    color: var(--secondary-text-color);
                    margin-top: 2px;
                }
            </style>
            <div class="card-header">
                <ha-icon class="card-icon" icon="mdi:battery-charging"></ha-icon>
                <h2 class="card-title">Predikce kapacity baterie</h2>
            </div>
            <div id="chart"></div>
            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #008FFB;"></div>
                    <span>Skutečná kapacita</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #00E396;"></div>
                    <span>Predikovaná kapacita</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #FEB019;"></div>
                    <span>Solární výroba</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #FF4560;"></div>
                    <span>Spotřeba domu</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #775DD0;"></div>
                    <span>Nabíjení ze sítě</span>
                </div>
            </div>
            <div class="stats" id="stats"></div>
        `;
    }

    initChart() {
        if (!window.ApexCharts || !this.shadowRoot.querySelector('#chart')) return;

        const options = {
            chart: {
                type: 'line',
                height: 400,
                animations: {
                    enabled: true,
                    easing: 'easeinout',
                    speed: 800
                },
                toolbar: {
                    show: true,
                    tools: {
                        download: true,
                        selection: false,
                        zoom: true,
                        zoomin: true,
                        zoomout: true,
                        pan: false,
                        reset: true,
                    }
                }
            },
            series: [],
            xaxis: {
                type: 'datetime',
                labels: {
                    format: 'HH:mm'
                },
                title: {
                    text: 'Čas'
                }
            },
            yaxis: [
                {
                    title: {
                        text: 'Kapacita baterie (kWh)'
                    },
                    min: 0
                },
                {
                    opposite: true,
                    title: {
                        text: 'Výkon (kW)'
                    }
                }
            ],
            stroke: {
                width: [3, 3, 2, 2, 2],
                curve: 'smooth'
            },
            colors: ['#008FFB', '#00E396', '#FEB019', '#FF4560', '#775DD0'],
            legend: {
                show: false // Používáme vlastní legendu
            },
            tooltip: {
                shared: true,
                intersect: false,
                x: {
                    format: 'dd.MM HH:mm'
                }
            },
            grid: {
                borderColor: '#e7e7e7',
                row: {
                    colors: ['#f3f3f3', 'transparent'],
                    opacity: 0.5
                }
            },
            annotations: {
                xaxis: [{
                    x: new Date().getTime(),
                    borderColor: '#999',
                    label: {
                        text: 'Nyní',
                        style: {
                            color: '#fff',
                            background: '#999'
                        }
                    }
                }]
            }
        };

        this.chart = new ApexCharts(this.shadowRoot.querySelector('#chart'), options);
        this.chart.render();
        this.updateChart();
    }

    updateChart() {
        if (!this.chart || !this._hass) return;

        const entityId = this.config.entity;
        const entity = this._hass.states[entityId];
        if (!entity) return;

        const attrs = entity.attributes;
        // Příprava dat pro graf
        const series = this.prepareSeries(attrs);
        const stats = this.prepareStats(attrs);

        // Aktualizace grafu
        this.chart.updateSeries(series);

        // Aktualizace statistik
        this.updateStats(stats);
    }

    prepareSeries(attrs) {
        const series = [];
        const now = new Date();

        // Kombinace skutečných a predikovaných dat pro baterii
        const batteryData = this.combineBatteryData(attrs);
        if (batteryData.length > 0) {
            series.push({
                name: 'Kapacita baterie',
                data: batteryData,
                yAxisIndex: 0
            });
        }
        // Solární výroba
        const solarData = this.combineSolarData(attrs);
        if (solarData.length > 0) {
            series.push({
                name: 'Solární výroba',
                data: solarData,
                yAxisIndex: 1
            });
        }
        // Spotřeba domu
        const consumptionData = this.combineConsumptionData(attrs);
        if (consumptionData.length > 0) {
            series.push({
                name: 'Spotřeba domu',
                data: consumptionData,
                yAxisIndex: 1
            });
        }
        // Nabíjení ze sítě (jako bodové značky)
        const chargingData = this.prepareChargingData(attrs);
        if (chargingData.length > 0) {
            series.push({
                name: 'Nabíjení ze sítě',
                data: chargingData,
                type: 'scatter',
                yAxisIndex: 0
            });
        }

        return series;
    }

    combineBatteryData(attrs) {
        const data = [];

        // Včerejšek
        const yesterdayActual = attrs.battery_yesterday_actual || {};
        Object.entries(yesterdayActual).forEach(([timestamp, value]) => {
            data.push({
                x: new Date(timestamp).getTime(),
                y: value
            });
        });

        // Dnešek - skutečná data
        const todayActual = attrs.battery_today_actual || {};
        Object.entries(todayActual).forEach(([timestamp, value]) => {
            data.push({
                x: new Date(timestamp).getTime(),
                y: value
            });
        });
        // Dnešek - predikce (od aktuální hodiny)
        const todayPredicted = attrs.battery_today_predicted || {};
        Object.entries(todayPredicted).forEach(([timestamp, value]) => {
            const time = new Date(timestamp);
            if (time >= new Date()) {
                data.push({
                    x: time.getTime(),
                    y: value
                });
            }
        });
        // Zítra - predikce
        const tomorrowPredicted = attrs.battery_tomorrow_predicted || {};
        Object.entries(tomorrowPredicted).forEach(([timestamp, value]) => {
            const time = new Date(timestamp);
            data.push({
                x: time.getTime(),
                y: value
            });
        });

        return data.sort((a, b) => a.x - b.x);
    }

    combineSolarData(attrs) {
        const data = [];
        // Skutečná výroba
        const yesterdayActual = attrs.solar_yesterday_actual || {};
        const todayActual = attrs.solar_today_actual || {};

        Object.entries({...yesterdayActual, ...todayActual}).forEach(([timestamp, value]) => {
            data.push({
                x: new Date(timestamp).getTime(),
                y: value
            });
        });

        // Predikce
        const todayPredicted = attrs.solar_today_predicted || {};
        const tomorrowPredicted = attrs.solar_tomorrow_predicted || {};

        Object.entries({...todayPredicted, ...tomorrowPredicted}).forEach(([timestamp, value]) => {
            const time = new Date(timestamp);
            if (time >= new Date()) {
                data.push({
                    x: time.getTime(),
                    y: value
                });
            }
        });

        return data.sort((a, b) => a.x - b.x);
    }

    combineConsumptionData(attrs) {
        const data = [];

        // Skutečná spotřeba
        const yesterdayActual = attrs.consumption_yesterday_actual || {};
        const todayActual = attrs.consumption_today_actual || {};

        Object.entries({...yesterdayActual, ...todayActual}).forEach(([timestamp, value]) => {
            data.push({
                x: new Date(timestamp).getTime(),
                y: Math.abs(value) // Spotřeba jako pozitivní hodnota
            });
        });
        // Predikce
        const todayPredicted = attrs.consumption_today_predicted || {};
        const tomorrowPredicted = attrs.consumption_tomorrow_predicted || {};

        Object.entries({...todayPredicted, ...tomorrowPredicted}).forEach(([timestamp, value]) => {
            const time = new Date(timestamp);
            if (time >= new Date()) {
                data.push({
                    x: time.getTime(),
                    y: Math.abs(value) // Spotřeba jako pozitivní hodnota
                });
            }
        });

        return data.sort((a, b) => a.x - b.x);
    }

    prepareChargingData(attrs) {
        const data = [];
        const chargingToday = attrs.charging_hours_today || [];
        const chargingTomorrow = attrs.charging_hours_tomorrow || [];
        const maxCapacity = attrs.battery_config?.max_capacity_kwh || 10;

        [...chargingToday, ...chargingTomorrow].forEach(timestamp => {
            data.push({
                x: new Date(timestamp).getTime(),
                y: maxCapacity * 0.9 // Zobrazit nabíjení nahoře v grafu
            });
        });

        return data.sort((a, b) => a.x - b.x);
    }

    prepareStats(attrs) {
        const config = attrs.battery_config || {};
        const chargingToday = attrs.charging_hours_today || [];
        const chargingTomorrow = attrs.charging_hours_tomorrow || [];

        return {
            maxCapacity: `${config.max_capacity_kwh || 0} kWh`,
            minCapacity: `${config.min_capacity_percent || 20}%`,
            chargeRate: `${config.charge_rate_kw || 2.8} kW`,
            chargingHoursToday: chargingToday.length,
            chargingHoursTomorrow: chargingTomorrow.length,
            lastUpdate: attrs.last_update ? new Date(attrs.last_update).toLocaleString('cs-CZ') : 'N/A'
        };
    }

    updateStats(stats) {
        const statsContainer = this.shadowRoot.querySelector('#stats');
        if (!statsContainer) return;

        statsContainer.innerHTML = `
            <div class="stat-item">
                <div class="stat-value">${stats.maxCapacity}</div>
                <div class="stat-label">Max. kapacita</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${stats.minCapacity}</div>
                <div class="stat-label">Min. kapacita</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${stats.chargeRate}</div>
                <div class="stat-label">Nabíjecí výkon</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${stats.chargingHoursToday}</div>
                <div class="stat-label">Nabíjení dnes</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${stats.chargingHoursTomorrow}</div>
                <div class="stat-label">Nabíjení zítra</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${stats.lastUpdate}</div>
                <div class="stat-label">Poslední aktualizace</div>
            </div>
        `;
    }

    getCardSize() {
        return 6; // Velikost karty v grid systému
    }
}

// Registrace custom elementu
customElements.define('oig-battery-forecast-card', OigBatteryForecastCard);

// Registrace pro Lovelace
window.customCards = window.customCards || [];
window.customCards.push({
    type: 'oig-battery-forecast-card',
    name: 'OIG Battery Forecast Card',
    description: 'Karta pro zobrazení predikce kapacity baterie s Apex Charts',
});

console.info(
    '%c  OIG-BATTERY-FORECAST-CARD  \n%c  Version 1.0.0             ',
    'color: orange; font-weight: bold; background: black',
    'color: white; font-weight: bold; background: dimgray'
);
