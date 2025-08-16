/**
 * Zjednodušený loader pro Apex Charts - pouze CDN s fallbacks
 */
window.OIG_CHART_CONFIG = {
    // Verze Apex Charts
    version: '3.44.0',

    // CDN zdroje (primární a fallback)
    cdnSources: [
        'https://cdn.jsdelivr.net/npm/apexcharts@3.44.0/dist/apexcharts.min.js',
        'https://unpkg.com/apexcharts@3.44.0/dist/apexcharts.min.js',
        'https://cdnjs.cloudflare.com/ajax/libs/apexcharts/3.44.0/apexcharts.min.js'
    ],

    // Timeout pro načítání (ms)
    loadTimeout: 15000,

    // Debug mode
    debug: false
};

/**
 * CDN loader pro Apex Charts s multiple fallbacks
 */
class ApexChartsLoader {
    static async load() {
        if (window.ApexCharts) {
            if (window.OIG_CHART_CONFIG.debug) {
                console.log('✅ Apex Charts už je načten');
            }
            return Promise.resolve();
        }

        const config = window.OIG_CHART_CONFIG;
        const sources = config.cdnSources;

        for (let i = 0; i < sources.length; i++) {
            const source = sources[i];
            try {
                if (config.debug) {
                    console.log(`🔄 Zkouším načíst Apex Charts z: ${source}`);
                }

                await this.loadScript(source);

                if (config.debug) {
                    console.log(`✅ Apex Charts úspěšně načten z: ${source}`);
                }
                return;

            } catch (error) {
                console.warn(`❌ Nepodařilo se načíst z ${source}:`, error.message);

                // Pokud není poslední zdroj, zkusíme další
                if (i < sources.length - 1) {
                    console.log(`🔄 Zkouším další CDN zdroj...`);
                }
            }
        }

        throw new Error('❌ Nepodařilo se načíst Apex Charts z žádného CDN zdroje');
    }

    static loadScript(src) {
        return new Promise((resolve, reject) => {
            // Kontrola, jestli script už není načtený
            if (document.querySelector(`script[src="${src}"]`)) {
                if (window.ApexCharts) {
                    resolve();
                } else {
                    reject(new Error('Script existuje, ale ApexCharts objekt není dostupný'));
                }
                return;
            }

            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            script.crossOrigin = 'anonymous';

            const timeout = setTimeout(() => {
                script.remove();
                reject(new Error(`Timeout při načítání ${src}`));
            }, window.OIG_CHART_CONFIG.loadTimeout);

            script.onload = () => {
                clearTimeout(timeout);
                if (window.ApexCharts) {
                    resolve();
                } else {
                    script.remove();
                    reject(new Error('ApexCharts objekt není dostupný po načtení skriptu'));
                }
            };

            script.onerror = () => {
                clearTimeout(timeout);
                script.remove();
                reject(new Error(`Chyba při načítání ${src}`));
            };

            document.head.appendChild(script);
        });
    }

    static getVersion() {
        if (window.ApexCharts && window.ApexCharts.version) {
            return window.ApexCharts.version;
        }
        return 'unknown';
    }

    static isLoaded() {
        return !!window.ApexCharts;
    }
}

// Export pro použití v jiných souborech
window.ApexChartsLoader = ApexChartsLoader;

// Auto-load pokud je konfigurováno
if (window.OIG_CHART_CONFIG.autoLoad) {
    document.addEventListener('DOMContentLoaded', () => {
        ApexChartsLoader.load().catch(console.error);
    });
}

console.info(
    '%c OIG Charts Loader \n%c CDN-only version 1.0',
    'color: orange; font-weight: bold; background: black',
    'color: white; font-weight: bold; background: dimgray'
);
