/* eslint-disable */
// === GRID CHARGING PLAN FUNCTIONS ===

function getDayLabel(day) {
    if (day === 'tomorrow') return 'zítra';
    if (day === 'today') return 'dnes';
    return '';
}

function getBlockEnergyKwh(block) {
    if (!block) return 0;
    // HYBRID API uses grid_import_kwh, legacy uses grid_charge_kwh
    const energy = Number(block.grid_import_kwh || block.grid_charge_kwh);
    if (Number.isFinite(energy) && energy > 0) {
        return energy;
    }
    const start = Number(block.battery_start_kwh);
    const end = Number(block.battery_end_kwh);
    if (Number.isFinite(start) && Number.isFinite(end)) {
        const delta = end - start;
        return delta > 0 ? delta : 0;
    }
    return 0;
}

function sortChargingBlocks(blocks = []) {
    return [...blocks].sort((a, b) => {
        const dayScore = (a?.day === 'tomorrow' ? 1 : 0) - (b?.day === 'tomorrow' ? 1 : 0);
        if (dayScore !== 0) return dayScore;
        return (a?.time_from || '').localeCompare(b?.time_from || '');
    });
}

function formatPlanWindow(blocks) {
    if (!Array.isArray(blocks) || blocks.length === 0) return null;
    const sorted = sortChargingBlocks(blocks);
    const first = sorted[0];
    const last = sorted[sorted.length - 1];

    const startLabel = getDayLabel(first?.day);
    const endLabel = getDayLabel(last?.day);

    if (startLabel === endLabel) {
        const prefix = startLabel ? `${startLabel} ` : '';
        if (!first?.time_from || !last?.time_to) {
            return prefix.trim() || null;
        }
        return `${prefix}${first.time_from} – ${last.time_to}`;
    }

    const startText = first ? `${startLabel ? `${startLabel} ` : ''}${first.time_from || '--'}` : '--';
    const endText = last ? `${endLabel ? `${endLabel} ` : ''}${last.time_to || '--'}` : '--';
    return `${startText} → ${endText}`;
}

function formatBlockLabel(block) {
    if (!block) return '--';
    const label = getDayLabel(block.day);
    const prefix = label ? `${label} ` : '';
    const from = block.time_from || '--';
    const to = block.time_to || '--';
    return `${prefix}${from} - ${to}`;
}

function updateChargingRow(rowId, valueId, block, shouldShow) {
    const rowEl = document.getElementById(rowId);
    const valueEl = document.getElementById(valueId);
    if (!rowEl || !valueEl) return;

    if (block && shouldShow) {
        rowEl.style.display = 'flex';
        valueEl.textContent = formatBlockLabel(block);
    } else {
        rowEl.style.display = 'none';
        valueEl.textContent = '--';
    }
}

// Update target warning indicator - kontrola dosažitelnosti cílové kapacity
async function updateTargetWarningIndicator() {
    const forecastData = await getSensorString(getSensorId('battery_forecast'));
    const warningRow = document.getElementById('target-warning-row');
    const warningIndicator = document.getElementById('target-warning-indicator');

    if (!forecastData || !forecastData.attributes || !warningRow || !warningIndicator) {
        return;
    }

    const attrs = forecastData.attributes;
    const targetAchieved = attrs.target_achieved;
    const minAchieved = attrs.min_achieved;
    const finalCapacityKwh = attrs.final_capacity_kwh;
    const targetCapacityKwh = attrs.target_capacity_kwh;
    const minCapacityKwh = attrs.min_capacity_kwh;
    const shortageKwh = attrs.shortage_kwh || 0;

    // Pokud nejsou dostupná data, skrýt
    if (targetAchieved === undefined) {
        warningRow.style.display = 'none';
        return;
    }

    // Pokud je vše OK (target dosažen), skrýt warning
    if (targetAchieved) {
        warningRow.style.display = 'none';
        return;
    }

    // Target NENÍ dosažen - zobrazit warning
    warningRow.style.display = 'flex';

    const maxCapacityKwh = attrs.max_capacity_kwh || 12.29;
    const finalPercentage = ((finalCapacityKwh / maxCapacityKwh) * 100).toFixed(0);
    const targetPercentage = ((targetCapacityKwh / maxCapacityKwh) * 100).toFixed(0);

    // Rozhodnout barvu a text podle závažnosti
    let color, text, tooltipText;

    if (!minAchieved) {
        // KRITICKÉ: Nedosáhne ani minimum
        color = '#f44336'; // červená
        text = `⚠️ Dosáhne ${finalPercentage}%`;
        tooltipText = `
            <div style="padding: 8px; text-align: left;">
                <strong style="color: ${color};">⚠️ KRITICKÉ VAROVÁNÍ</strong><br><br>
                <strong>Nedosáhne minimální kapacity!</strong><br>
                <span style="opacity: 0.8;">
                    Cílová kapacita: ${targetPercentage}% (${targetCapacityKwh.toFixed(1)} kWh)<br>
                    Minimální kapacita: ${((minCapacityKwh / maxCapacityKwh) * 100).toFixed(0)}% (${minCapacityKwh.toFixed(1)} kWh)<br>
                    <strong>Dosažitelná: ${finalPercentage}% (${finalCapacityKwh.toFixed(1)} kWh)</strong><br>
                    Chybí: ${shortageKwh.toFixed(1)} kWh
                </span>
                <hr style="margin: 6px 0; border: none; border-top: 1px solid rgba(255,255,255,0.2);">
                <span style="font-size: 0.9em; opacity: 0.9;">
                    💡 Není dostatek levných hodin pro nabíjení.<br>
                    Zvyšte max. cenu nebo snižte cílovou kapacitu.
                </span>
            </div>
        `;
    } else {
        // VAROVÁNÍ: Nedosáhne target, ale dosáhne minimum
        color = '#ff9800'; // oranžová
        text = `⚠️ Dosáhne ${finalPercentage}%`;
        tooltipText = `
            <div style="padding: 8px; text-align: left;">
                <strong style="color: ${color};">⚠️ VAROVÁNÍ</strong><br><br>
                <strong>Nedosáhne cílové kapacity</strong><br>
                <span style="opacity: 0.8;">
                    Cílová kapacita: ${targetPercentage}% (${targetCapacityKwh.toFixed(1)} kWh)<br>
                    <strong>Dosažitelná: ${finalPercentage}% (${finalCapacityKwh.toFixed(1)} kWh)</strong><br>
                    Chybí: ${shortageKwh.toFixed(1)} kWh
                </span>
                <hr style="margin: 6px 0; border: none; border-top: 1px solid rgba(255,255,255,0.2);">
                <span style="font-size: 0.9em; opacity: 0.9;">
                    💡 Není dostatek levných hodin pro dosažení targetu.<br>
                    Minimální kapacita bude zajištěna.
                </span>
            </div>
        `;
    }

    // Nastavit text a barvu
    warningIndicator.textContent = text;
    warningIndicator.style.color = color;
    warningIndicator.setAttribute('data-tooltip-html', tooltipText);

    // Přidat blikání (použít existující animaci)
    warningIndicator.style.animation = 'pulse-warning 2s ease-in-out infinite';
}

function parseHmToMinutes(hm) {
    if (!hm || typeof hm !== 'string') return null;
    const m = hm.trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    const h = Number(m[1]);
    const min = Number(m[2]);
    if (!Number.isFinite(h) || !Number.isFinite(min)) return null;
    return h * 60 + min;
}

function formatDurationMinutes(totalMinutes) {
    if (!Number.isFinite(totalMinutes) || totalMinutes <= 0) return '0 h';
    const hours = Math.floor(totalMinutes / 60);
    const minutes = Math.round(totalMinutes % 60);
    if (hours <= 0) return `${minutes} min`;
    if (minutes <= 0) return `${hours} h`;
    return `${hours} h ${minutes} min`;
}

function getLocalDateKey(dateObj) {
    if (!(dateObj instanceof Date) || Number.isNaN(dateObj.getTime())) return null;
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function buildChargingBlocksFromTimeline(rawTimeline) {
    const timeline = Array.isArray(rawTimeline?.timeline) ? rawTimeline.timeline : rawTimeline;
    if (!Array.isArray(timeline) || timeline.length === 0) return [];

    const todayKey = getLocalDateKey(new Date());
    const sorted = [...timeline]
        .filter(p => p && typeof p.timestamp === 'string')
        .sort((a, b) => a.timestamp.localeCompare(b.timestamp));

    const blocks = [];
    let current = null;

    const flush = () => {
        if (!current) return;
        if (current.interval_count <= 0) {
            current = null;
            return;
        }
        const avg = current.grid_import_kwh > 0 ? (current.total_cost_czk / current.grid_import_kwh) : 0;
        blocks.push({
            day: current.day,
            time_from: current.time_from,
            time_to: current.time_to,
            interval_count: current.interval_count,
            grid_import_kwh: current.grid_import_kwh,
            total_cost_czk: current.total_cost_czk,
            avg_spot_price_czk: avg
        });
        current = null;
    };

    for (let i = 0; i < sorted.length; i++) {
        const point = sorted[i];
        const gridKwh = Number(point.grid_import_kwh ?? point.grid_charge_kwh ?? 0);
        if (!Number.isFinite(gridKwh) || gridKwh <= 0) {
            flush();
            continue;
        }

        const ts = point.timestamp;
        const [datePart, timePart] = ts.split('T');
        const hm = timePart ? timePart.slice(0, 5) : null;
        if (!datePart || !hm) {
            flush();
            continue;
        }

        const day = datePart === todayKey ? 'today' : 'tomorrow';
        const spot = Number(point.spot_price_czk ?? 0);
        const cost = Number.isFinite(spot) && spot > 0 ? gridKwh * spot : 0;

        if (!current) {
            current = {
                day,
                datePart,
                time_from: hm,
                time_to: hm,
                interval_count: 0,
                grid_import_kwh: 0,
                total_cost_czk: 0,
                last_ts: ts
            };
        } else {
            const sameDay = current.datePart === datePart;
            const contiguous = sameDay && current.last_ts && typeof current.last_ts === 'string'
                ? true
                : false;
            if (!sameDay || !contiguous) {
                flush();
                current = {
                    day,
                    datePart,
                    time_from: hm,
                    time_to: hm,
                    interval_count: 0,
                    grid_import_kwh: 0,
                    total_cost_czk: 0,
                    last_ts: ts
                };
            }
        }

        current.interval_count += 1;
        current.grid_import_kwh += gridKwh;
        current.total_cost_czk += cost;
        current.last_ts = ts;
        current.time_to = hm;
    }

    flush();

    // Adjust time_to: add one interval (assume 15min) for nicer display
    blocks.forEach((b) => {
        const fromMin = parseHmToMinutes(b.time_from);
        const toMin = parseHmToMinutes(b.time_to);
        if (fromMin === null || toMin === null) return;
        const intervalMinutes = 15;
        const end = toMin + intervalMinutes;
        const endH = Math.floor(end / 60) % 24;
        const endM = end % 60;
        b.time_to = `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;
    });

    return blocks;
}

function computeBlocksDurationMinutes(blocks) {
    if (!Array.isArray(blocks) || blocks.length === 0) return 0;
    let total = 0;
    blocks.forEach((b) => {
        const a = parseHmToMinutes(b.time_from);
        const z = parseHmToMinutes(b.time_to);
        if (a === null || z === null) return;
        const delta = z - a;
        if (delta > 0) total += delta;
    });
    return total;
}

async function updateGridChargingPlan() {
    const gridChargingData = await getSensorString(getSensorId('grid_charging_planned'));
    const isPlanned = gridChargingData.value === 'on';

    let rawBlocks = gridChargingData.attributes?.charging_blocks || [];
    let chargingBlocks = sortChargingBlocks(rawBlocks);
    let hasBlocks = chargingBlocks.length > 0;

    // Fallback: pokud sensor nemá charging_blocks, zkus vytvořit bloky z timeline API
    if (!hasBlocks && typeof loadBatteryTimeline === 'function') {
        try {
            const timeline = await loadBatteryTimeline(typeof INVERTER_SN === 'string' ? INVERTER_SN : undefined);
            rawBlocks = buildChargingBlocksFromTimeline(timeline);
            chargingBlocks = sortChargingBlocks(rawBlocks);
            hasBlocks = chargingBlocks.length > 0;
        } catch (e) {
            console.warn('[GridCharging] Timeline fallback failed:', e);
        }
    }

    const totalEnergy = Number(gridChargingData.attributes?.total_energy_kwh)
        || chargingBlocks.reduce((sum, b) => sum + Number(b.grid_import_kwh || b.grid_charge_kwh || 0), 0);
    const totalCost = Number(gridChargingData.attributes?.total_cost_czk)
        || chargingBlocks.reduce((sum, b) => sum + Number(b.total_cost_czk || 0), 0);
    const planWindow = formatPlanWindow(chargingBlocks);
    const durationMinutes = computeBlocksDurationMinutes(chargingBlocks);
    const runningBlock = chargingBlocks.find(block => {
        const status = (block.status || '').toLowerCase();
        return status === 'running' || status === 'active';
    });
    const upcomingBlock = runningBlock
        ? chargingBlocks[chargingBlocks.indexOf(runningBlock) + 1] || null
        : chargingBlocks[0] || null;
    const shouldShowNext = upcomingBlock && (!runningBlock || upcomingBlock !== runningBlock);

    updateChargingRow('grid-charging-current-row', 'grid-charging-current', runningBlock, !!runningBlock);
    updateChargingRow('grid-charging-next-row', 'grid-charging-next', upcomingBlock, !!shouldShowNext);

    const indicator = document.getElementById('battery-grid-charging-indicator');
    if (indicator) {
        if (isPlanned) {
            indicator.classList.add('active');
        } else {
            indicator.classList.remove('active');
        }

        if (hasBlocks) {
            const planSummary = planWindow || gridChargingData.attributes?.next_charging_time_range || '--';
            let tooltipHtml = `
                <div class="grid-charging-popup">
                    <strong>Období:</strong> ${planSummary}<br>
                    <strong>Plánované dobití:</strong> ${totalEnergy.toFixed(1)} kWh<br>
                    <strong>Celková cena:</strong> ~${totalCost.toFixed(2)} Kč
                    <hr style="margin: 8px 0; border: none; border-top: 1px solid var(--border-secondary);">
                    <table>
                        <thead>
                            <tr>
                                <th>Čas</th>
                                <th style="text-align: right;">kWh</th>
                                <th style="text-align: right;">Kč</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            chargingBlocks.forEach((block) => {
                const dayLabel = block.day === 'tomorrow' ? ' (zítra)' : '';
                const timeRange = `${block.time_from}-${block.time_to}${dayLabel}`;
                const energyValue = getBlockEnergyKwh(block);
                const costValue = Number(block.total_cost_czk) || 0;

                tooltipHtml += `
                    <tr>
                        <td>${timeRange}</td>
                        <td style="text-align: right;">${energyValue.toFixed(2)}</td>
                        <td style="text-align: right;">${costValue.toFixed(2)}</td>
                    </tr>
                `;
            });

            tooltipHtml += `
                        </tbody>
                    </table>
                </div>
            `;

            indicator.setAttribute('data-tooltip-html', tooltipHtml);
        } else {
            indicator.setAttribute('data-tooltip', 'Žádné plánované nabíjení');
        }

        initTooltips();
    }

    const section = document.getElementById('grid-charging-plan-section');
    if (section) {
        section.style.display = hasBlocks ? 'block' : 'none';
    }

    const windowElement = document.getElementById('grid-charging-window');
    const durationElement = document.getElementById('grid-charging-duration');
    const windowRow = document.getElementById('grid-charging-window-row');
    const durationRow = document.getElementById('grid-charging-duration-row');
    if (windowElement && windowRow) {
        windowRow.style.display = hasBlocks ? 'flex' : 'none';
        windowElement.textContent = hasBlocks
            ? (planWindow || gridChargingData.attributes?.next_charging_time_range || '--')
            : '--';
    }
    if (durationElement && durationRow) {
        durationRow.style.display = hasBlocks ? 'flex' : 'none';
        durationElement.textContent = hasBlocks ? formatDurationMinutes(durationMinutes) : '--';
    }

    const energyElement = document.getElementById('grid-charging-energy');
    if (energyElement) {
        energyElement.textContent = totalEnergy.toFixed(1) + ' kWh';
    }

    const costElement = document.getElementById('grid-charging-cost');
    if (costElement) {
        costElement.textContent = '~' + totalCost.toFixed(2) + ' Kč';
    }

    await updateTargetWarningIndicator();
}

async function updateBatteryBalancingCard() {
    try {
        const balancingData = await getSensorString(getSensorId('battery_balancing'));
        const forecastData = await getSensorString(getSensorId('battery_forecast'));

        if (!balancingData || !balancingData.attributes) {
            console.warn('[Balancing] No balancing data available');
            return;
        }

        const attrs = balancingData.attributes;
        const rawState = balancingData.state;
        const status =
            rawState && rawState !== 'unknown' && rawState !== 'unavailable'
                ? rawState
                : (attrs.status || 'ok'); // ok, due_soon, critical, overdue, disabled
        const daysSince = attrs.days_since_last ?? null;
        const intervalDays = attrs.cycle_days ?? 7;
        const holdingHours = attrs.holding_hours ?? 3;
        const socThreshold = attrs.soc_threshold ?? 80;
        const lastBalancing = attrs.last_balancing ? new Date(attrs.last_balancing) : null;
        const planned = attrs.planned;
        const currentStateRaw = attrs.current_state ?? 'standby'; // charging/balancing/planned/standby
        const currentState =
            currentStateRaw && currentStateRaw !== 'unknown' && currentStateRaw !== 'unavailable'
                ? currentStateRaw
                : 'standby';
        const timeRemaining = attrs.time_remaining; // HH:MM

        // Získat cost tracking data
        const costImmediate = Number.isFinite(Number(attrs.cost_immediate_czk))
            ? Number(attrs.cost_immediate_czk)
            : null;
        const costSelected = Number.isFinite(Number(attrs.cost_selected_czk))
            ? Number(attrs.cost_selected_czk)
            : null;
        const costSavings = Number.isFinite(Number(attrs.cost_savings_czk))
            ? Number(attrs.cost_savings_czk)
            : null;

        console.debug('[Balancing] Sensor data:', {
            state: status,
            daysSince,
            intervalDays,
            lastBalancing: attrs.last_balancing,
            costImmediate,
            costSelected,
            costSavings,
            planned: !!planned
        });

        // Vypočítat dny do dalšího balancingu
        let daysRemaining = null;
        if (daysSince !== null) {
            daysRemaining = Math.max(0, intervalDays - daysSince);
        }

        // Status barvy
        const statusColors = {
            ok: '#4CAF50',           // zelená
            due_soon: '#FFC107',     // žlutá
            critical: '#FF9800',     // oranžová
            overdue: '#F44336',      // červená
            disabled: '#757575'      // šedá
        };
        const statusColor = statusColors[status] || '#757575';

        // Current state texty a barvy
        const stateTexts = {
            charging: 'Příprava na 100%',
            balancing: 'Vyrovnávání článků',
            completed: 'Vybalancováno',
            planned: 'Čeká na zahájení',
            standby: 'Standby'
        };

        const stateColors = {
            charging: '#FFC107',    // žlutá
            balancing: '#FF9800',   // oranžová
            completed: '#4CAF50',   // zelená
            planned: '#2196F3',     // modrá
            standby: '#757575'      // šedá
        };

        // Update status label s detailním stavem
        const statusLabel = document.getElementById('balancing-status-label');
        if (statusLabel) {
            const stateText = stateTexts[currentState] || currentState;
            const stateColor = stateColors[currentState] || '#757575';

            if (currentState === 'charging' && timeRemaining) {
                statusLabel.textContent = `${stateText} (${timeRemaining} do balancování)`;
            } else if (currentState === 'balancing' && timeRemaining) {
                statusLabel.textContent = `${stateText} (zbývá ${timeRemaining})`;
            } else if (currentState === 'planned' && timeRemaining) {
                statusLabel.textContent = `${stateText} (start za ${timeRemaining})`;
            } else if (currentState === 'completed' && timeRemaining) {
                statusLabel.textContent = `${stateText} ${timeRemaining}`;
            } else {
                statusLabel.textContent = stateText;
            }

            statusLabel.style.color = stateColor;
        }

        // OPRAVA: Update nadpisu karty podle aktuálního stavu
        const cardTitle = document.getElementById('balancing-card-title');
        if (cardTitle) {
            if (currentState === 'balancing') {
                cardTitle.textContent = '⚡ Probíhá balancování';
                cardTitle.style.color = '#FF9800';
            } else if (currentState === 'charging') {
                cardTitle.textContent = '🔋 Příprava na balancování';
                cardTitle.style.color = '#FFC107';
            } else if (currentState === 'completed') {
                cardTitle.textContent = '✅ Balancování dokončeno';
                cardTitle.style.color = '#4CAF50';
            } else if (currentState === 'planned') {
                cardTitle.textContent = '📅 Balancování naplánováno';
                cardTitle.style.color = '#2196F3';
            } else {
                cardTitle.textContent = '🔋 Vyrovnání baterie';
                cardTitle.style.color = '#FF9800';
            }
        }

        // Update velké číslo - dny
        const daysNumber = document.getElementById('balancing-days-number');
        const daysUnit = document.getElementById('balancing-days-unit');
        if (daysNumber) {
            if (daysRemaining !== null) {
                daysNumber.textContent = daysRemaining;
                daysNumber.style.color = statusColor;

                // Správný český tvar
                if (daysUnit) {
                    if (daysRemaining === 1) {
                        daysUnit.textContent = 'den';
                    } else if (daysRemaining >= 2 && daysRemaining <= 4) {
                        daysUnit.textContent = 'dny';
                    } else {
                        daysUnit.textContent = 'dní';
                    }
                }
            } else {
                daysNumber.textContent = '?';
                daysNumber.style.color = '#757575';
                if (daysUnit) {
                    daysUnit.textContent = 'dní';
                }
            }
        }

        // Update poslední balancing (krátký formát)
        const lastDateShort = document.getElementById('balancing-last-date-short');
        if (lastDateShort && lastBalancing) {
            const dateStr = lastBalancing.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit' });
            lastDateShort.textContent = `${dateStr} (${daysSince}d)`;
        } else if (lastDateShort) {
            lastDateShort.textContent = 'Žádné';
        }

        // Update plánované balancing (krátký formát)
        const plannedShort = document.getElementById('balancing-planned-short');
        const plannedTimeShort = document.getElementById('balancing-planned-time-short');
        const costValueShort = document.getElementById('balancing-cost-value-short');

        if (planned && plannedTimeShort && costValueShort && plannedShort) {
            // Zobrazit plánovanou řádku
            plannedShort.style.display = 'flex';

            // Parsovat časy
            const startTime = new Date(planned.holding_start);
            const startStr = startTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });

            // Zobrazit info o charging intervalech
            const chargingIntervals = planned.charging_intervals || [];
            const chargingAvgPrice = planned.charging_avg_price_czk || 0;
            const endTime = new Date(planned.holding_end);
            const endStr = endTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });

            // Sestavit detailní tooltip s tabulkou (zmenšená šířka aby se vešla)
            let tooltipHTML = '<div style="text-align: left; font-size: 11px; min-width: 200px; max-width: 250px;">';
            tooltipHTML += '<strong style="display: block; margin-bottom: 8px; font-size: 12px; color: #FFA726;">🔋 Plán balancování</strong>';

            // Sekce: Příprava (nabíjení)
            if (chargingIntervals.length > 0) {
                tooltipHTML += '<div style="margin-bottom: 10px;">';
                tooltipHTML += '<div style="font-weight: 600; margin-bottom: 4px; color: rgba(255,255,255,0.9);">📊 Příprava (nabíjení na 100%)</div>';
                tooltipHTML += '<table style="width: 100%; border-collapse: collapse; margin-left: 8px;">';

                // Formátovat intervaly s datem (dnes/zítra)
                const now = new Date();
                const todayDate = now.getDate();
                const chargingTimes = chargingIntervals.map(t => {
                    const time = new Date(t);
                    const timeStr = time.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
                    const isTomorrow = time.getDate() !== todayDate;
                    return isTomorrow ? `zítra ${timeStr}` : timeStr;
                });

                // Rozdělit intervaly pod sebe pro lepší čitelnost
                tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7); vertical-align: top;">Intervaly:</td>';
                tooltipHTML += `<td style="padding: 2px 4px; text-align: right; line-height: 1.4;">${chargingTimes.join('<br>')}</td></tr>`;
                tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Průměrná cena:</td>';
                tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${chargingAvgPrice.toFixed(2)} Kč/kWh</td></tr>`;
                tooltipHTML += '</table>';
                tooltipHTML += '</div>';
            }

            // Sekce: Balancování (držení)
            tooltipHTML += '<div style="margin-bottom: 10px;">';
            tooltipHTML += '<div style="font-weight: 600; margin-bottom: 4px; color: rgba(255,255,255,0.9);">⚡ Balancování (držení na 100%)</div>';
            tooltipHTML += '<table style="width: 100%; border-collapse: collapse; margin-left: 8px;">';
            tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Začátek:</td>';
            tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${startStr}</td></tr>`;
            tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Konec:</td>';
            tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${endStr}</td></tr>`;
            tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Délka:</td>';
            tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${attrs.config?.hold_hours ?? 3} hodiny</td></tr>`;
            tooltipHTML += '</table>';
            tooltipHTML += '</div>';

            // Sekce: Náklady (pokud jsou k dispozici)
            if (costSelected !== null && costSelected !== undefined) {
                tooltipHTML += '<table style="width: 100%; border-collapse: collapse; margin-top: 8px;">';
                tooltipHTML += '<thead><tr style="border-bottom: 1px solid rgba(255,255,255,0.2);">';
                tooltipHTML += '<th style="padding: 4px; text-align: left; color: rgba(255,255,255,0.9);">💰 Náklady</th>';
                tooltipHTML += '<th style="padding: 4px; text-align: right;"></th>';
                tooltipHTML += '</tr></thead>';
                tooltipHTML += '<tbody>';
                tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Vybraný plán:</td>';
                tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${costSelected !== null ? costSelected.toFixed(2) : '--'} Kč</td></tr>`;
                if (costImmediate !== null) {
                    tooltipHTML += '<tr><td style="padding: 2px 4px; color: rgba(255,255,255,0.7);">Okamžitě:</td>';
                    tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${costImmediate.toFixed(2)} Kč</td></tr>`;
                }
                if (costSavings !== null && costSavings > 0) {
                    tooltipHTML += '<tr style="color: #4CAF50;"><td style="padding: 2px 4px;">Úspora:</td>';
                    tooltipHTML += `<td style="padding: 2px 4px; text-align: right;">${costSavings.toFixed(2)} Kč</td></tr>`;
                }
                tooltipHTML += '</tbody>';
                tooltipHTML += '</table>';
            }

            tooltipHTML += '</div>';

            plannedTimeShort.textContent = `dnes ${startStr}`;
            plannedTimeShort.setAttribute('data-tooltip-html', tooltipHTML);

            // Zobrazení nákladů
            if (costSelected !== null) {
                // Použít cost tracking data z balancing senzoru
                costValueShort.textContent = `${costSelected.toFixed(1)} Kč`;
                if (costSavings !== null && costSavings > 0) {
                    costValueShort.textContent += ` (-${costSavings.toFixed(1)} Kč)`;
                    costValueShort.title = `Vybraná cena: ${costSelected.toFixed(2)} Kč\nÚspora oproti okamžitému: ${costSavings.toFixed(2)} Kč`;
                    costValueShort.style.color = '#4CAF50'; // Zelená = úspora
                } else {
                    costValueShort.title = `Odhadované náklady: ${costSelected.toFixed(2)} Kč`;
                    costValueShort.style.color = 'var(--text-primary)';
                }
            } else {
                // Fallback odhad
                console.warn('[Balancing] No balancing_cost in forecast, using estimate');
                const avgPrice = planned.avg_price_czk ?? 0;
                const holdHours = holdingHours;
                const estimatedCost = avgPrice * holdHours * 0.7;
                costValueShort.textContent = `~${estimatedCost.toFixed(1)} Kč`;
                costValueShort.title = 'Odhad (přesné náklady nejsou k dispozici)';
                costValueShort.style.color = 'var(--text-primary)';
            }
        } else if (plannedShort) {
            // Skrýt plánovanou řádku
            plannedShort.style.display = 'none';
            if (costValueShort) costValueShort.textContent = '--';
        }

        // Update timeline bar
        const timelineBar = document.getElementById('balancing-timeline-bar');
        const timelineLabel = document.getElementById('balancing-timeline-label');

        if (timelineBar && timelineLabel && daysSince !== null) {
            const progressPercent = Math.min(100, (daysSince / intervalDays) * 100);

            timelineBar.style.width = `${progressPercent}%`;
            timelineBar.style.background = `linear-gradient(90deg, ${statusColor} 0%, ${statusColor}aa 100%)`;

            timelineLabel.textContent = `${daysSince}/${intervalDays} dní`;
        }

        // Re-inicializovat tooltips aby fungovaly na dynamicky přidaných elementech
        if (typeof initTooltips === 'function') {
            initTooltips();
        }

        // NOVÉ: Aktualizovat baterie balancing indikátor
        updateBatteryBalancingIndicator(currentState, timeRemaining, costSelected);

    } catch (error) {
        console.error('[Balancing] Error updating battery balancing card:', error);
    }
}

/**
 * Aktualizuje indikátor balancování baterie v boxu baterie
 * @param {string} state - Aktuální stav: 'charging', 'balancing', 'planned', 'standby'
 * @param {string} timeRemaining - Zbývající čas ve formátu HH:MM
 * @param {number|null} costSelected - Celkové náklady balancování
 */
function updateBatteryBalancingIndicator(state, timeRemaining, costSelected) {
    const indicator = document.getElementById('battery-balancing-indicator');
    const icon = document.getElementById('balancing-icon');
    const text = document.getElementById('balancing-text');

    if (!indicator || !icon || !text) return;

    // Zobrazit indikátor jen během aktivního balancování
    if (state === 'charging' || state === 'balancing') {
        indicator.style.display = 'flex';

        // Ikona podle stavu
        if (state === 'charging') {
            icon.textContent = '⚡';
            text.textContent = 'Nabíjení...';
            indicator.className = 'battery-balancing-indicator charging';
        } else if (state === 'balancing') {
            icon.textContent = '⏸️';
            text.textContent = 'Balancuje...';
            indicator.className = 'battery-balancing-indicator holding';
        }

        // Sestavit tooltip s detaily
        let tooltipHtml = '<div style="text-align: left; min-width: 200px;">';
        tooltipHtml += '<strong>🔋 Balancování baterie</strong><br><br>';

        if (state === 'charging') {
            tooltipHtml += '<strong>Fáze:</strong> Nabíjení baterie<br>';
            tooltipHtml += '<em>Baterie se nabíjí před vyvažováním článků</em><br><br>';
        } else {
            tooltipHtml += '<strong>Fáze:</strong> Držení (balancování)<br>';
            tooltipHtml += '<em>Články baterie se vyvažují na stejnou úroveň</em><br><br>';
        }

        if (timeRemaining) {
            tooltipHtml += `⏱️ <strong>Zbývá:</strong> ${timeRemaining}<br>`;
        }

        if (costSelected !== null && costSelected !== undefined) {
            tooltipHtml += `<br><strong>💰 Náklady:</strong> ${costSelected.toFixed(2)} Kč<br>`;
        }

        tooltipHtml += '<br><small style="opacity: 0.7;">ℹ️ Balancování prodlužuje životnost baterie tím, že vyrovná napětí všech článků</small>';
        tooltipHtml += '</div>';

        indicator.setAttribute('data-tooltip-html', tooltipHtml);

    } else {
        // Skrýt indikátor pokud není aktivní balancování
        indicator.style.display = 'none';
    }

    // Reinicializovat tooltips
    if (typeof initTooltips === 'function') {
        initTooltips();
    }
}

function showGridChargingPopup() {
    getSensorString(getSensorId('grid_charging_planned')).then(gridChargingData => {
        if (!gridChargingData.attributes || !gridChargingData.attributes.charging_blocks) {
            showDialog('Plánované nabíjení ze sítě', 'Žádné bloky nejsou naplánovány.');
            return;
        }

        const blocks = sortChargingBlocks(gridChargingData.attributes.charging_blocks);
        const totalEnergy = gridChargingData.attributes.total_energy_kwh || 0;
        const totalCost = gridChargingData.attributes.total_cost_czk || 0;
        const planWindow = formatPlanWindow(blocks);

        // Build table HTML
        let tableHtml = `
            <div class="grid-charging-popup grid-charging-dialog">
                <div style="margin-bottom: 10px;">
                    <strong>Období:</strong> ${planWindow || '--'}<br>
                    <strong>Celková energie:</strong> ${totalEnergy.toFixed(2)} kWh<br>
                    <strong>Celková cena:</strong> ~${totalCost.toFixed(2)} Kč
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Čas</th>
                            <th style="text-align: right;">Energie</th>
                            <th style="text-align: right;">∅ Cena</th>
                            <th style="text-align: right;">Náklady</th>
                            <th style="text-align: center;">Baterie</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        blocks.forEach((block, index) => {
            const rowBg = index % 2 === 0 ? 'var(--bg-tertiary)' : 'transparent';
            const batteryStart = Number(block.battery_start_kwh);
            const batteryEnd = Number(block.battery_end_kwh);
            const batteryChange = Number.isFinite(batteryStart) && Number.isFinite(batteryEnd)
                ? `${batteryStart.toFixed(1)} → ${batteryEnd.toFixed(1)} kWh`
                : '--';
            const energyValue = getBlockEnergyKwh(block);
            const energyText = energyValue.toFixed(2) + ' kWh';
            const avgPriceValue = Number(block.avg_spot_price_czk) || 0;
            const avgPriceText = avgPriceValue > 0 ? avgPriceValue.toFixed(2) + ' Kč/kWh' : '—';
            const costValue = Number(block.total_cost_czk) || 0;
            const costText = costValue.toFixed(2) + ' Kč';
            const intervalCount = Number(block.interval_count) || 0;
            const intervalInfo = intervalCount > 0 ? `${intervalCount}× 15min` : ' ';
            const blockDay = getDayLabel(block.day);
            const daySuffix = blockDay ? ` (${blockDay})` : '';

            tableHtml += `
                <tr style="background: ${rowBg};">
                    <td>
                        <strong>${block.time_from} - ${block.time_to}${daySuffix}</strong><br>
                        <small style="opacity: 0.7;">${intervalInfo}</small>
                    </td>
                    <td style="text-align: right;">${energyText}</td>
                    <td style="text-align: right;">${avgPriceText}</td>
                    <td style="text-align: right;"><strong>${costText}</strong></td>
                    <td style="text-align: center; font-size: 0.85em;">
                        ${batteryChange}
                    </td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;

        showDialog('⚡ Plánované nabíjení ze sítě', tableHtml);
    });
}

// Dialog functions (stubs - to be implemented or removed)
function openGridChargingDialog() {
    console.log('[GridCharging] openGridChargingDialog - not implemented');
}

function closeGridChargingDialog() {
    console.log('[GridCharging] closeGridChargingDialog - not implemented');
}

function renderGridChargingDialog() {
    console.log('[GridCharging] renderGridChargingDialog - not implemented');
    return '';
}

function selectTimeBlock() {
    console.log('[GridCharging] selectTimeBlock - not implemented');
}

function deselectTimeBlock() {
    console.log('[GridCharging] deselectTimeBlock - not implemented');
}

function clearAllBlocks() {
    console.log('[GridCharging] clearAllBlocks - not implemented');
}

function saveGridChargingPlan() {
    console.log('[GridCharging] saveGridChargingPlan - not implemented');
}


// Export grid charging functions
window.DashboardGridCharging = {
    openGridChargingDialog,
    closeGridChargingDialog,
    renderGridChargingDialog,
    selectTimeBlock,
    deselectTimeBlock,
    clearAllBlocks,
    saveGridChargingPlan,
    init: function() {
        console.log('[DashboardGridCharging] Initialized');
    }
};

console.log('[DashboardGridCharging] Module loaded');
