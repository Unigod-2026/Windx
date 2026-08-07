/* ==========================================================================
   风球 GEO 监控 · SVG 图表引擎
   纯手写 SVG，无外部依赖
   ========================================================================== */

const Charts = {

    /* ---------- 折线图（多系列） ---------- */
    lineChart(container, opts) {
        const { labels, series, height = 320, showArea = true, smooth = true } = opts;
        const w = container.clientWidth || 800;
        const h = height;
        const padL = 50, padR = 24, padT = 20, padB = 36;
        const cw = w - padL - padR;
        const ch = h - padT - padB;

        const allData = series.flatMap(s => s.data);
        const yMax = Math.max(...allData) * 1.15;
        const yMin = 0;

        const xStep = cw / Math.max(labels.length - 1, 1);
        const yScale = v => padT + ch - ((v - yMin) / (yMax - yMin)) * ch;
        const xScale = i => padL + i * xStep;

        // Y轴刻度
        const yTicks = 5;
        let yAxis = '';
        for (let i = 0; i <= yTicks; i++) {
            const val = yMin + (yMax - yMin) * i / yTicks;
            const y = yScale(val);
            yAxis += `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="#f0f0f0" stroke-width="1"/>`;
            yAxis += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8c8c8c">${Math.round(val)}</text>`;
        }

        // X轴标签
        let xAxis = '';
        const labelStep = Math.ceil(labels.length / 8);
        labels.forEach((label, i) => {
            if (i % labelStep === 0 || i === labels.length - 1) {
                xAxis += `<text x="${xScale(i)}" y="${h - 12}" text-anchor="middle" font-size="11" fill="#8c8c8c">${label}</text>`;
            }
        });

        // 系列路径
        let paths = '';
        series.forEach(s => {
            let pathD = '';
            let areaD = '';
            const points = [];
            s.data.forEach((val, i) => {
                const x = xScale(i);
                const y = yScale(val);
                points.push([x, y]);
                if (i === 0) {
                    pathD += `M ${x} ${y}`;
                } else if (smooth) {
                    const prev = points[i - 1];
                    const cpX1 = prev[0] + (x - prev[0]) * 0.5;
                    const cpY1 = prev[1];
                    const cpX2 = prev[0] + (x - prev[0]) * 0.5;
                    const cpY2 = y;
                    pathD += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${x} ${y}`;
                } else {
                    pathD += ` L ${x} ${y}`;
                }
            });

            if (showArea) {
                const lastX = xScale(s.data.length - 1);
                areaD = pathD + ` L ${lastX} ${padT + ch} L ${padL} ${padT + ch} Z`;
                paths += `<path d="${areaD}" fill="${s.color}" opacity="0.06"/>`;
            }
            paths += `<path d="${pathD}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;

            // 数据点
            s.data.forEach((val, i) => {
                const x = xScale(i);
                const y = yScale(val);
                paths += `<circle cx="${x}" cy="${y}" r="3" fill="white" stroke="${s.color}" stroke-width="2" class="chart-dot" data-label="${s.name}" data-value="${val}"/>`;
            });
        });

        // tooltip
        let tooltip = '';
        labels.forEach((label, i) => {
            const x = xScale(i);
            tooltip += `<line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + ch}" stroke="transparent" stroke-width="${xStep}" class="tooltip-line" data-index="${i}"/>`;
        });

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="overflow:visible">
            ${yAxis}
            ${xAxis}
            ${paths}
            ${tooltip}
        </svg>`;
    },

    /* ---------- 水平条形排行图 ---------- */
    barRanking(container, opts) {
        const { items, height = 280 } = opts;
        const w = container.clientWidth || 400;
        const h = height;
        const padL = 80, padR = 50, padT = 12, padB = 12;
        const cw = w - padL - padR;
        const ch = h - padT - padB;
        const barH = ch / items.length * 0.6;
        const gap = ch / items.length * 0.4;

        let bars = '';
        items.forEach((item, i) => {
            const y = padT + i * (barH + gap) + gap / 2;
            const barW = (item.value / 100) * cw;
            bars += `<text x="${padL - 8}" y="${y + barH/2 + 4}" text-anchor="end" font-size="12" fill="#4f4f4f">${item.label}</text>`;
            bars += `<rect x="${padL}" y="${y}" width="${cw}" height="${barH}" rx="4" fill="#f5f6f8"/>`;
            bars += `<rect x="${padL}" y="${y}" width="${barW}" height="${barH}" rx="4" fill="${item.color}"/>`;
            bars += `<text x="${padL + barW + 8}" y="${y + barH/2 + 4}" font-size="12" font-weight="600" fill="${item.color}">${item.value}%</text>`;
        });

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">${bars}</svg>`;
    },

    /* ---------- 饼图（环形） ---------- */
    donutChart(container, opts) {
        const { items, height = 260 } = opts;
        const w = container.clientWidth || 400;
        const h = height;
        const cx = w / 2, cy = h / 2;
        const r = Math.min(w, h) / 2 - 30;
        const innerR = r * 0.6;

        const total = items.reduce((s, i) => s + i.value, 0);
        let startAngle = -Math.PI / 2;
        let arcs = '';
        let labels = '';

        items.forEach((item, i) => {
            const angle = (item.value / total) * Math.PI * 2;
            const endAngle = startAngle + angle;
            const x1 = cx + r * Math.cos(startAngle);
            const y1 = cy + r * Math.sin(startAngle);
            const x2 = cx + r * Math.cos(endAngle);
            const y2 = cy + r * Math.sin(endAngle);
            const x3 = cx + innerR * Math.cos(endAngle);
            const y3 = cy + innerR * Math.sin(endAngle);
            const x4 = cx + innerR * Math.cos(startAngle);
            const y4 = cy + innerR * Math.sin(startAngle);
            const largeArc = angle > Math.PI ? 1 : 0;

            arcs += `<path d="M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4} Z" fill="${item.color}" class="donut-slice" data-label="${item.label}" data-value="${item.value}"/>`;

            // 标签
            const midAngle = (startAngle + endAngle) / 2;
            const labelR = r + 16;
            const lx = cx + labelR * Math.cos(midAngle);
            const ly = cy + labelR * Math.sin(midAngle);
            if (item.value / total > 0.04) {
                labels += `<text x="${lx}" y="${ly + 4}" text-anchor="${lx > cx ? 'start' : 'end'}" font-size="11" fill="#4f4f4f">${item.label} ${((item.value/total)*100).toFixed(1)}%</text>`;
            }

            startAngle = endAngle;
        });

        const centerText = `<text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="13" fill="#8c8c8c">总计</text><text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="24" font-weight="700" fill="#181818">${total}</text>`;

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">${arcs}${labels}${centerText}</svg>`;
    },

    /* ---------- 分组柱状图（自身 vs 竞品） ---------- */
    groupedBar(container, opts) {
        const { labels, groups, height = 260 } = opts;
        const w = container.clientWidth || 500;
        const h = height;
        const padL = 50, padR = 20, padT = 16, padB = 36;
        const cw = w - padL - padR;
        const ch = h - padT - padB;
        const groupW = cw / labels.length;
        const barW = groupW * 0.3;
        const gap = groupW * 0.05;

        const yMax = Math.max(...groups.flatMap(g => g.data)) * 1.2;
        const yScale = v => padT + ch - (v / yMax) * ch;

        let yAxis = '';
        for (let i = 0; i <= 4; i++) {
            const val = yMax * i / 4;
            const y = yScale(val);
            yAxis += `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="#f0f0f0" stroke-width="1"/>`;
            yAxis += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8c8c8c">${Math.round(val)}</text>`;
        }

        let bars = '';
        let xAxis = '';
        labels.forEach((label, i) => {
            const groupCenter = padL + i * groupW + groupW / 2;
            xAxis += `<text x="${groupCenter}" y="${h - 12}" text-anchor="middle" font-size="11" fill="#8c8c8c">${label}</text>`;
            groups.forEach((g, gi) => {
                const val = g.data[i];
                const barX = groupCenter - (groups.length * barW + (groups.length - 1) * gap) / 2 + gi * (barW + gap);
                const barY = yScale(val);
                const barH = padT + ch - barY;
                bars += `<rect x="${barX}" y="${barY}" width="${barW}" height="${barH}" rx="3" fill="${g.color}"/>`;
            });
        });

        // 图例
        let legend = '';
        groups.forEach((g, i) => {
            const lx = padL + i * 100;
            legend += `<rect x="${lx}" y="${h - 2}" width="12" height="8" rx="2" fill="${g.color}"/>`;
            legend += `<text x="${lx + 16}" y="${h + 5}" font-size="11" fill="#4f4f4f">${g.name}</text>`;
        });

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h + 16}" width="100%" height="${h + 16}">${yAxis}${bars}${xAxis}</svg>`;
    },

    /* ---------- 迷你折线（Sparkline） ---------- */
    sparkline(container, data, color = '#1a55e8') {
        const w = 140, h = 50;
        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;
        const xStep = w / (data.length - 1);
        const yScale = v => h - ((v - min) / range) * (h - 8) - 4;

        let path = `M 0 ${yScale(data[0])}`;
        data.forEach((v, i) => {
            if (i > 0) {
                const prev = data[i - 1];
                const x = i * xStep;
                const y = yScale(v);
                const px = (i - 1) * xStep;
                const py = yScale(prev);
                const cpX = px + (x - px) * 0.5;
                path += ` C ${cpX} ${py}, ${cpX} ${y}, ${x} ${y}`;
            }
        });

        const areaPath = path + ` L ${w} ${h} L 0 ${h} Z`;

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
            <path d="${areaPath}" fill="${color}" opacity="0.1"/>
            <path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
    },

    /* ---------- 面积趋势图（新增/流失） ---------- */
    areaTrend(container, opts) {
        const { labels, added, lost, height = 260 } = opts;
        const w = container.clientWidth || 500;
        const h = height;
        const padL = 40, padR = 20, padT = 16, padB = 36;
        const cw = w - padL - padR;
        const ch = h - padT - padB;

        const yMax = Math.max(...added, ...lost) * 1.3;
        const xStep = cw / (labels.length - 1);
        const yScale = v => padT + ch - (v / yMax) * ch;
        const xScale = i => padL + i * xStep;

        let yAxis = '';
        for (let i = 0; i <= 4; i++) {
            const val = yMax * i / 4;
            const y = padT + ch - (val / yMax) * ch;
            yAxis += `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="#f0f0f0" stroke-width="1"/>`;
            yAxis += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8c8c8c">${Math.round(val)}</text>`;
        }

        let xAxis = '';
        const labelStep = Math.ceil(labels.length / 8);
        labels.forEach((label, i) => {
            if (i % labelStep === 0 || i === labels.length - 1) {
                xAxis += `<text x="${xScale(i)}" y="${h - 12}" text-anchor="middle" font-size="11" fill="#8c8c8c">${label}</text>`;
            }
        });

        // Added area
        let addedPath = `M ${xScale(0)} ${yScale(added[0])}`;
        added.forEach((v, i) => { if (i > 0) addedPath += ` L ${xScale(i)} ${yScale(v)}`; });
        const addedArea = addedPath + ` L ${xScale(added.length - 1)} ${padT + ch} L ${xScale(0)} ${padT + ch} Z`;

        // Lost area
        let lostPath = `M ${xScale(0)} ${yScale(lost[0])}`;
        lost.forEach((v, i) => { if (i > 0) lostPath += ` L ${xScale(i)} ${yScale(v)}`; });
        const lostArea = lostPath + ` L ${xScale(lost.length - 1)} ${padT + ch} L ${xScale(0)} ${padT + ch} Z`;

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
            ${yAxis}
            ${xAxis}
            <path d="${addedArea}" fill="#52c41a" opacity="0.15"/>
            <path d="${addedPath}" fill="none" stroke="#52c41a" stroke-width="2" stroke-linejoin="round"/>
            <path d="${lostArea}" fill="#ff4d4f" opacity="0.1"/>
            <path d="${lostPath}" fill="none" stroke="#ff4d4f" stroke-width="2" stroke-linejoin="round" stroke-dasharray="4,3"/>
            <rect x="${padL}" y="${h - 2}" width="12" height="8" rx="2" fill="#52c41a"/>
            <text x="${padL + 16}" y="${h + 5}" font-size="11" fill="#4f4f4f">新增信源</text>
            <rect x="${padL + 90}" y="${h - 2}" width="12" height="8" rx="2" fill="#ff4d4f"/>
            <text x="${padL + 106}" y="${h + 5}" font-size="11" fill="#4f4f4f">流失信源</text>
        </svg>`;
    },

    /* ---------- 雷达图（竞品对比） ---------- */
    radar(container, opts) {
        const { axes, series, height = 280 } = opts;
        const w = container.clientWidth || 400;
        const h = height;
        const cx = w / 2, cy = h / 2 - 10;
        const r = Math.min(w, h) / 2 - 50;
        const n = axes.length;

        let grid = '';
        for (let level = 1; level <= 4; level++) {
            const lr = r * level / 4;
            let points = '';
            for (let i = 0; i < n; i++) {
                const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
                points += `${cx + lr * Math.cos(angle)},${cy + lr * Math.sin(angle)} `;
            }
            grid += `<polygon points="${points}" fill="none" stroke="#f0f0f0" stroke-width="1"/>`;
        }

        let axisLines = '';
        let axisLabels = '';
        axes.forEach((axis, i) => {
            const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
            const ex = cx + r * Math.cos(angle);
            const ey = cy + r * Math.sin(angle);
            axisLines += `<line x1="${cx}" y1="${cy}" x2="${ex}" y2="${ey}" stroke="#f0f0f0" stroke-width="1"/>`;
            const lx = cx + (r + 20) * Math.cos(angle);
            const ly = cy + (r + 20) * Math.sin(angle);
            axisLabels += `<text x="${lx}" y="${ly + 4}" text-anchor="middle" font-size="11" fill="#4f4f4f">${axis}</text>`;
        });

        let polygons = '';
        series.forEach(s => {
            let points = '';
            s.values.forEach((val, i) => {
                const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
                const vr = r * val / 100;
                points += `${cx + vr * Math.cos(angle)},${cy + vr * Math.sin(angle)} `;
            });
            polygons += `<polygon points="${points}" fill="${s.color}" fill-opacity="0.12" stroke="${s.color}" stroke-width="2"/>`;
        });

        container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
            ${grid}${axisLines}${axisLabels}${polygons}
        </svg>`;
    }
};
