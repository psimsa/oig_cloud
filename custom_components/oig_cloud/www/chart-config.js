/**
 * Konfigurace pro načítání Apex Charts
 */
window.OIG_CHART_CONFIG = {
    // Strategie načítání: 'local', 'cdn', 'auto'
    loadStrategy: 'auto',

    // Verze Apex Charts (pro CDN)
    apexChartsVersion: '3.44.0',

    // CDN zdroje (primární a fallback)
    cdnSources: [
        'https://cdn.jsdelivr.net/npm/apexcharts@3.44.0/dist/apexcharts.min.js',
        'https://unpkg.com/apexcharts@3.44.0/dist/apexcharts.min.js',
        'https://cdnjs.cloudflare.com/ajax/libs/apexcharts/3.44.0/apexcharts.min.js'
    ],

    // Lokální cesta
    localPath: '/oig_cloud_static/apex-charts.min.js',

    // Timeout pro načítání (ms)
    loadTimeout: 10000,

    // Debug mode
    debug: false
};

/**
 * Univerzální loader pro Apex Charts s multiple fallbacks
 */
class ApexChartsLoader {
    static async load() {
        if (window.ApexCharts) {
            if (window.OIG_CHART_CONFIG.debug) {
                console.log('Apex Charts už je načten');
            }
            return Promise.resolve();
        }

        const config = window.OIG_CHART_CONFIG;

        switch (config.loadStrategy) {
            case 'local':
                return this.loadLocal();
            case 'cdn':
                return this.loadCDN();
            case 'auto':
            default:
                return this.loadAuto();
        }
    }

    static loadLocal() {
        return this.loadScript(window.OIG_CHART_CONFIG.localPath);
    }

    static async loadCDN() {
        const sources = window.OIG_CHART_CONFIG.cdnSources;

        for (const source of sources) {
            try {
                await this.loadScript(source);
                return;
            } catch (error) {
                console.warn(`Nepodařilo se načíst z ${source}:`, error);
            }
        }

        throw new Error('Nepodařilo se načíst Apex Charts z žádného CDN zdroje');
    }

    static async loadAuto() {
        try {
            // Nejdříve zkusíme lokální verzi
            await this.loadLocal();
            if (window.OIG_CHART_CONFIG.debug) {
                console.log('Apex Charts načten lokálně');
            }
        } catch (error) {
            console.warn('Lokální verze Apex Charts nedostupná, zkouším CDN');
            await this.loadCDN();
            if (window.OIG_CHART_CONFIG.debug) {
                console.log('Apex Charts načten z CDN');
            }
        }
    }

    static loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;

            const timeout = setTimeout(() => {
                reject(new Error(`Timeout při načítání ${src}`));
            }, window.OIG_CHART_CONFIG.loadTimeout);

            script.onload = () => {
                clearTimeout(timeout);
                if (window.ApexCharts) {
                    resolve();
                } else {
                    reject(new Error('ApexCharts objekt není dostupný po načtení skriptu'));
                }
            };

            script.onerror = () => {
                clearTimeout(timeout);
                reject(new Error(`Chyba při načítání ${src}`));
            };

            document.head.appendChild(script);
        });
    }
}

// Export pro použití v jiných souborech
window.ApexChartsLoader = ApexChartsLoader;
