class OigCloudDashboard {
    constructor() {
        this.entryId = this.getUrlParam('entry_id');
        this.inverterSn = this.getUrlParam('inverter_sn');
        this.charts = {};
        this.updateInterval = null;
        this.wsConnection = null;
    }

    getUrlParam(name) {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(name);
    }

    async init() {
        console.log('Initializing OIG Cloud Dashboard...');
        console.log('Entry ID:', this.entryId);
        console.log('Inverter SN:', this.inverterSn);

        if (!this.entryId || !this.inverterSn) {
            throw new Error('Missing entry_id or inverter_sn parameters');
        }

        // Načíst data a vytvořit grafy
        await this.loadAndRenderCharts();

        // Nastavit automatické obnovování každé 2 minuty
        this.updateInterval = setInterval(() => {
            this.loadAndRenderCharts();
        }, 120000);
    }

    async loadAndRenderCharts() {
        try {
            // Načíst data ze senzorů
            const batteryForecastData = await this.getSensorData(`sensor.oig_${this.inverterSn}_battery_forecast`);
            const solarForecastData = await this.getSensorData(`sensor.oig_${this.inverterSn}_solar_forecast`);

            // Vytvořit grafy
            if (batteryForecastData) {
                this.renderBatteryChart(batteryForecastData);
            }

            if (solarForecastData) {
                this.renderSolarChart(solarForecastData);
            }

            // Zkusit načíst spotové ceny
            try {
                const spotPricesData = await this.getSensorData(`sensor.oig_${this.inverterSn}_spot_prices_current`);
                if (spotPricesData) {
                    this.renderSpotPricesChart(spotPricesData);
                }
            } catch (e) {
                document.getElementById('prices-chart').innerHTML = '<div style="text-align:center;padding:40px;">Spotové ceny nejsou dostupné</div>';
            }

        } catch (error) {
            console.error('Error loading chart data:', error);
        }
    }

    async getSensorData(entityId) {
        try {
            // OPRAVA: Zkusit nejdříve přímý přístup k HA API
            return await this.getDirectSensorData(entityId);
        } catch (error) {
            console.error(`Error fetching ${entityId}:`, error);
            return null;
        }
    }

    async getDirectSensorData(entityId) {
        try {
            // Zkusit použít Home Assistant connection API pokud je dostupný
            if (window.hassConnection) {
                const states = await window.hassConnection.sendMessagePromise({
                    type: 'get_states'
                });
                return states.find(state => state.entity_id === entityId);
            }

            // Fallback na fetch API s tokenem z localStorage
            const token = this.getHAToken();
            if (token) {
                const response = await fetch(`/api/states/${entityId}`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    }
                });

                if (response.ok) {
                    return await response.json();
                }
            }

            throw new Error('Unable to fetch sensor data');
        } catch (error) {
            throw error;
        }
    }

    getHAToken() {
        // Zkusit získat token z různých míst
        try {
            // Zkusit z localStorage
            const tokens = localStorage.getItem('hassTokens');
            if (tokens) {
                const parsed = JSON.parse(tokens);
                return parsed.access_token;
            }

            // Zkusit z sessionStorage
            const sessionTokens = sessionStorage.getItem('hassTokens');
            if (sessionTokens) {
                const parsed = JSON.parse(sessionTokens);
                return parsed.access_token;
            }

            return null;
        } catch (e) {
            return null;
        }
    }

    updateChartThemes(theme) {
        // NOVÉ: Aktualizovat témata všech grafů
        const isDark = theme === 'dark';

        const commonThemeOptions = {
            chart: {
                background: isDark ? '#1e1e1e' : '#ffffff',
                foreColor: isDark ? '#e1e1e1' : '#212121'
            },
            grid: {
                borderColor: isDark ? '#444' : '#e0e0e0'
            },
            xaxis: {
                labels: {
                    style: {
                        colors: isDark ? '#e1e1e1' : '#212121'
                    }
                }
            },
            yaxis: {
                labels: {
                    style: {
                        colors: isDark ? '#e1e1e1' : '#212121'
                    }
                }
            },
            legend: {
                labels: {
                    colors: isDark ? '#e1e1e1' : '#212121'
                }
            }
        };

        // Aktualizovat všechny existující grafy
        Object.values(this.charts).forEach(chart => {
            if (chart && chart.updateOptions) {
                chart.updateOptions(commonThemeOptions);
            }
        });
    }

    renderBatteryChart(sensorData) {
        if (!sensorData || !sensorData.attributes) return;

        const attrs = sensorData.attributes;
        const timelineData = attrs.timeline_data || [];

        if (!timelineData.length) {
            document.getElementById('battery-chart').innerHTML = '<div style="text-align:center;padding:40px;">Žádná data pro zobrazení</div>';
            return;
        }

        // Připravit data pro graf
        const solarData = [];
        const batteryData = [];
        const spotPrices = [];
        const chargingPeriods = [];

        timelineData.forEach(point => {
            const timestamp = new Date(point.timestamp).getTime();

            // Solární výroba (W)
            solarData.push([timestamp, point.solar_production_w]);

            // Kapacita baterie (kWh)
            batteryData.push([timestamp, point.battery_capacity_kwh]);

            // Spotové ceny (pokud jsou dostupné)
            if (point.spot_price_czk !== null) {
                spotPrices.push([timestamp, point.spot_price_czk]);
            }

            // Období nabíjení
            if (point.is_charging) {
                chargingPeriods.push([timestamp, point.battery_capacity_kwh]);
            }
        });

        // OPRAVA: Přidat podporu pro témata
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

        const options = {
            series: [
                {
                    name: 'FVE Výroba',
                    type: 'line',
                    yAxisIndex: 1,
                    data: solarData,
                    color: '#00E396'
                },
                {
                    name: 'Kapacita baterie',
                    type: 'area',
                    yAxisIndex: 0,
                    data: batteryData,
                    color: '#FF8C00',
                    fillColor: {
                        type: 'solid',
                        color: '#FF8C00',
                        opacity: 0.3
                    }
                },
                {
                    name: 'Nabíjení',
                    type: 'area',
                    yAxisIndex: 0,
                    data: chargingPeriods,
                    color: '#00E396',
                    fillColor: {
                        type: 'solid',
                        color: '#00E396',
                        opacity: 0.5
                    }
                }
            ],
            chart: {
                type: 'line',
                height: 400,
                animations: { enabled: false },
                background: isDark ? '#1e1e1e' : '#ffffff',
                foreColor: isDark ? '#e1e1e1' : '#212121'
            },
            grid: {
                borderColor: isDark ? '#444' : '#e0e0e0'
            },
            xaxis: {
                type: 'datetime',
                labels: {
                    format: 'HH:mm dd.MM',
                    style: {
                        colors: isDark ? '#e1e1e1' : '#212121'
                    }
                }
            },
            yaxis: [
                {
                    title: {
                        text: 'Kapacita (kWh)',
                        style: {
                            color: isDark ? '#e1e1e1' : '#212121'
                        }
                    },
                    labels: {
                        style: {
                            colors: isDark ? '#e1e1e1' : '#212121'
                        }
                    },
                    min: 0,
                    max: attrs.max_capacity_kwh || 15
                },
                {
                    opposite: true,
                    title: {
                        text: 'Výroba (W)',
                        style: {
                            color: isDark ? '#e1e1e1' : '#212121'
                        }
                    },
                    labels: {
                        style: {
                            colors: isDark ? '#e1e1e1' : '#212121'
                        }
                    },
                    min: 0,
                    max: 3000
                }
            ],
            legend: {
                labels: {
                    colors: isDark ? '#e1e1e1' : '#212121'
                }
            },
            annotations: {
                points: spotPrices.map(([timestamp, price]) => ({
                    x: timestamp,
                    y: price * 2, // Upravit pozici podle potřeby
                    marker: {
                        size: 0
                    },
                    label: {
                        text: price.toFixed(1),
                        style: {
                            background: '#FF0000',
                            color: '#FFF',
                            fontSize: '10px'
                        }
                    }
                }))
            },
            title: {
                text: `Aktuálně: ${attrs.current_battery_kwh || 0} kWh`,
                align: 'center'
            }
        };

        if (this.charts.battery) {
            this.charts.battery.destroy();
        }

        this.charts.battery = new ApexCharts(document.querySelector("#battery-chart"), options);
        this.charts.battery.render();
    }

    renderSolarChart(sensorData) {
        if (!sensorData || !sensorData.attributes) return;

        const attrs = sensorData.attributes;
        const todayData = attrs.today_hourly_total_kw || {};
        const tomorrowData = attrs.tomorrow_hourly_total_kw || {};

        // Převést data do formátu pro graf
        const todayChartData = [];
        const tomorrowChartData = [];

        Object.entries(todayData).forEach(([time, value]) => {
            const datetime = new Date();
            const [hour] = time.split(':');
            datetime.setHours(parseInt(hour), 0, 0, 0);
            todayChartData.push([datetime.getTime(), value]);
        });

        Object.entries(tomorrowData).forEach(([time, value]) => {
            const datetime = new Date();
            datetime.setDate(datetime.getDate() + 1);
            const [hour] = time.split(':');
            datetime.setHours(parseInt(hour), 0, 0, 0);
            tomorrowChartData.push([datetime.getTime(), value]);
        });

        const options = {
            series: [
                { name: 'Dnes', data: todayChartData },
                { name: 'Zítra', data: tomorrowChartData }
            ],
            chart: {
                type: 'area',
                height: 350,
                animations: { enabled: false }
            },
            xaxis: {
                type: 'datetime',
                labels: { format: 'HH:mm' }
            },
            yaxis: {
                title: { text: 'Výkon (kW)' },
                min: 0
            },
            colors: ['#FF9800', '#FFC107']
        };

        if (this.charts.solar) {
            this.charts.solar.destroy();
        }

        this.charts.solar = new ApexCharts(document.querySelector("#solar-chart"), options);
        this.charts.solar.render();
    }

    renderSpotPricesChart(sensorData) {
        if (!sensorData || !sensorData.attributes) return;

        const attrs = sensorData.attributes;
        const prices = attrs.prices_czk_kwh || {};

        const chartData = [];
        Object.entries(prices).forEach(([time, price]) => {
            const datetime = new Date(time);
            chartData.push([datetime.getTime(), price]);
        });

        const options = {
            series: [{
                name: 'Cena (CZK/kWh)',
                data: chartData
            }],
            chart: {
                type: 'column',
                height: 350,
                animations: { enabled: false }
            },
            xaxis: {
                type: 'datetime',
                labels: { format: 'HH:mm' }
            },
            yaxis: {
                title: { text: 'Cena (CZK/kWh)' }
            },
            colors: ['#2196F3']
        };

        if (this.charts.prices) {
            this.charts.prices.destroy();
        }

        this.charts.prices = new ApexCharts(document.querySelector("#prices-chart"), options);
        this.charts.prices.render();
    }

    destroy() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
        }

        Object.values(this.charts).forEach(chart => {
            if (chart) chart.destroy();
        });
    }
}

// OPRAVA: Přidat handler pro komunikaci s parent window (pokud bude potřeba)
if (window.parent && window.parent !== window) {
    window.addEventListener('message', (event) => {
        // Handler pro zprávy od parent window
        if (event.data && event.data.type === 'ha_state_update') {
            // Aktualizovat data v dashboard při změně stavu
            console.log('Received state update from parent:', event.data);
        }
    });
}

// Export pro globální použití
window.OigCloudDashboard = OigCloudDashboard;

// Spuštění dashboard při načtení stránky
document.addEventListener('DOMContentLoaded', () => {
    window.oigDashboard = new OigCloudDashboard();
});

// Cleanup při zavření stránky
window.addEventListener('beforeunload', () => {
    if (window.oigDashboard) {
        window.oigDashboard.destroy();
    }
});