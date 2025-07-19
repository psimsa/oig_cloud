// Bridge pro komunikaci mezi iframe a parent window
class HABridge {
    constructor() {
        this.setupMessageHandlers();
    }

    setupMessageHandlers() {
        window.addEventListener('message', async (event) => {
            if (event.data && event.data.type === 'get_sensor_data') {
                const entityId = event.data.entityId;

                try {
                    // Zkusit získat data z Home Assistant
                    const response = await this.getEntityState(entityId);

                    // Odeslat odpověď zpět do iframe
                    event.source.postMessage({
                        type: 'sensor_data_response',
                        entityId: entityId,
                        data: response
                    }, event.origin);

                } catch (error) {
                    console.error('Error getting sensor data:', error);

                    // Odeslat error odpověď
                    event.source.postMessage({
                        type: 'sensor_data_response',
                        entityId: entityId,
                        data: null,
                        error: error.message
                    }, event.origin);
                }
            }
        });
    }

    async getEntityState(entityId) {
        // Zkusit získat ze současného Home Assistant objektu
        if (window.hassConnection && window.hassConnection.sendMessagePromise) {
            return await window.hassConnection.sendMessagePromise({
                type: 'get_states',
                entity_id: entityId
            });
        }

        // Fallback na fetch s dlouhodobým tokenem
        const token = localStorage.getItem('hassTokens') || sessionStorage.getItem('hassTokens');
        if (token) {
            const response = await fetch(`/api/states/${entityId}`, {
                headers: {
                    'Authorization': `Bearer ${JSON.parse(token).access_token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                return await response.json();
            }
        }

        throw new Error('Unable to authenticate with Home Assistant');
    }
}

// Inicializovat bridge pouze pokud nejsme v iframe
if (window === window.parent) {
    window.haBridge = new HABridge();
}
