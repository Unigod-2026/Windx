/* ==========================================================================
   风球 GEO 监控 · 应用逻辑
   ========================================================================== */

const App = {
    currentTab: 'overview',
    currentQuestion: null,

    /* ---------- 页面切换：登录 -> 应用 ---------- */
    go(page) {
        document.getElementById('page-login').classList.remove('active');
        document.getElementById('page-app').classList.add('active');
        this.initCharts();
        this.toast('登录成功，欢迎使用风球 GEO 监控平台');
    },

    /* ---------- Tab 切换 ---------- */
    switchTab(tab) {
        this.currentTab = tab;
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.tab === tab);
        });
        document.querySelectorAll('.tab-pane').forEach(el => {
            el.classList.remove('active');
        });
        const pane = document.getElementById('tab-' + tab);
        if (pane) pane.classList.add('active');

        const crumbMap = {
            overview: '首屏概览', question: '问题提及分析', competitor: '竞品分析',
            source: '信源偏好', citation: '引用源分析', answer: 'AI 回答详情',
            qmanage: '问题管理', cmanage: '竞品管理', settings: '设置'
        };
        document.getElementById('header-crumb-tab').textContent = crumbMap[tab] || tab;

        // 懒加载对应内容
        if (tab === 'question') this.renderQuestionList();
        if (tab === 'competitor') this.renderCompetitor();
        if (tab === 'source') this.renderSources();
        if (tab === 'citation') this.renderCitations();
        if (tab === 'answer') this.renderAnswers();

        // 延迟渲染图表
        setTimeout(() => this.renderTabCharts(tab), 50);
    },

    /* ---------- 初始化图表 ---------- */
    initCharts() {
        this.renderOverviewCharts();
        this.renderSparklines();
    },

    renderTabCharts(tab) {
        if (tab === 'overview') this.renderOverviewCharts();
        if (tab === 'competitor') this.renderCompetitorCharts();
        if (tab === 'source') this.renderSourceCharts();
    },

    /* ---------- 概览页图表 ---------- */
    renderOverviewCharts() {
        const trendEl = document.getElementById('chart-trend-main');
        if (trendEl) {
            Charts.lineChart(trendEl, {
                labels: TREND_DATA.labels,
                series: TREND_DATA.models.slice(0, 7),
                height: 340,
            });
        }

        const top1El = document.getElementById('chart-top1-ranking');
        if (top1El) {
            Charts.barRanking(top1El, {
                items: MODELS.map(m => {
                    const q = QUESTIONS[0];
                    const md = q.models[m.name];
                    return {
                        label: m.name,
                        value: md ? Math.round(md.sentiment * 100 * 0.5) : Math.round(Math.random() * 40 + 15),
                        color: m.color,
                    };
                }),
                height: 300,
            });
        }
    },

    /* ---------- Sparkline 迷你图 ---------- */
    renderSparklines() {
        const sparkData = [
            { id: 'kpi-spark-1', data: [820, 860, 790, 910, 950, 1020, 1080, 1120, 1180, 1246], color: 'rgba(255,255,255,0.8)' },
            { id: 'kpi-spark-2', data: [30, 32, 31, 33, 34, 35, 34, 36, 35, 36], color: '#1a55e8' },
            { id: 'kpi-spark-3', data: [62, 63, 64, 65, 66, 65, 67, 66, 68, 68], color: '#52c41a' },
            { id: 'kpi-spark-4', data: [2800, 2950, 3050, 3100, 3150, 3250, 3300, 3350, 3380, 3420], color: '#722ed1' },
            { id: 'kpi-spark-5', data: [18000, 19000, 19500, 20500, 21000, 21800, 22500, 22900, 23400, 23940], color: '#ff6b1a' },
        ];
        sparkData.forEach(s => {
            const el = document.getElementById(s.id);
            if (el) Charts.sparkline(el, s.data, s.color);
        });
    },

    /* ---------- 问题列表渲染 ---------- */
    renderQuestionList() {
        const list = document.getElementById('question-list');
        if (!list) return;
        list.innerHTML = QUESTIONS.map((q, i) => `
            <div class="question-list-item ${i === 0 ? 'active' : ''}" onclick="App.selectQuestion('${q.id}')">
                <div class="question-title">${q.title}</div>
                <div class="question-meta">
                    <span class="question-tag">${q.tag}</span>
                    <span>${q.totalMentions} 次提及</span>
                    <span>${q.coverage}/7 模型覆盖</span>
                </div>
                <div class="question-metrics">
                    <div class="question-metric">提及率 <strong>${q.mentionRate}%</strong></div>
                    <div class="question-metric">Top1 <strong>${q.top1Rate}%</strong></div>
                    <div class="question-metric">Top3 <strong>${q.top3Rate}%</strong></div>
                </div>
            </div>
        `).join('');
        this.selectQuestion(QUESTIONS[0].id);
    },

    /* ---------- 选中问题 -> 渲染详情 ---------- */
    selectQuestion(qid) {
        const q = QUESTIONS.find(x => x.id === qid);
        if (!q) return;
        this.currentQuestion = q;

        document.querySelectorAll('.question-list-item').forEach(el => {
            el.classList.toggle('active', el.querySelector('.question-title').textContent === q.title);
        });

        const detail = document.getElementById('question-detail');
        if (!detail) return;

        const modelRows = MODELS.map(m => {
            const d = q.models[m.name];
            if (!d) return '';
            const rankClass = d.rank <= 1 ? 'rank-1' : d.rank <= 2 ? 'rank-2' : d.rank <= 3 ? 'rank-3' : 'rank-other';
            const sentimentColor = d.sentiment >= 0.7 ? 'var(--color-success)' : d.sentiment >= 0.5 ? 'var(--color-warning)' : 'var(--color-danger)';
            return `
                <tr>
                    <td>
                        <span style="display:inline-flex;align-items:center;gap:8px;">
                            <span style="width:10px;height:10px;border-radius:50%;background:${m.color};"></span>
                            ${m.name}
                        </span>
                    </td>
                    <td><span class="rank-pill ${rankClass}">No.${d.rank}</span></td>
                    <td><strong>${d.mention}</strong></td>
                    <td style="color:${sentimentColor};font-weight:600;">${(d.sentiment * 100).toFixed(0)}%</td>
                    <td>${d.recommend ? '<span class="status status-on">推荐</span>' : '<span class="status status-pause">未推荐</span>'}</td>
                    <td><button class="btn btn-text" onclick="App.viewAnswer('${m.name}')">查看原文</button></td>
                </tr>
            `;
        }).join('');

        const answerSnippets = MODELS.slice(0, 3).map(m => {
            const ans = q.answers[m.name];
            if (!ans) return '';
            const d = q.models[m.name];
            return `
                <div class="answer-snippet">
                    <div class="answer-snippet-header">
                        <span class="answer-snippet-model">
                            <span class="model-dot" style="background:${m.color};"></span>
                            ${m.name}
                        </span>
                        <span class="answer-snippet-rank">排名 No.${d.rank}</span>
                    </div>
                    <div class="answer-snippet-content">${ans.substring(0, 200)}... <a class="link" onclick="App.viewAnswer('${m.name}')">查看完整原文 →</a></div>
                </div>
            `;
        }).join('');

        const concernTags = q.concernHits.map(c => `<span class="table-tag tag-orange">${c}</span>`).join(' ');

        detail.innerHTML = `
            <div class="detail-header">
                <h2>${q.title}</h2>
                <div class="detail-meta">
                    <span class="table-tag tag-blue">${q.tag}</span>
                    <span>创建于 2026-07-12</span>
                    <span>最近采集：10 分钟前</span>
                    <span>关心内容命中率：${concernTags}</span>
                </div>
            </div>

            <div class="metric-row">
                <div class="metric-card">
                    <div class="metric-label">提及率</div>
                    <div class="metric-value">${q.mentionRate}%</div>
                    <div class="metric-change up">↑ ${q.change}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Top1 率</div>
                    <div class="metric-value">${q.top1Rate}%</div>
                    <div class="metric-change up">↑ +4.2%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Top3 率</div>
                    <div class="metric-value">${q.top3Rate}%</div>
                    <div class="metric-change up">↑ +2.1%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">平均排名</div>
                    <div class="metric-value">No.${q.rankAvg}</div>
                    <div class="metric-change up">↑ 上升 0.3</div>
                </div>
            </div>

            <div class="detail-section">
                <h3>模型对比 <span class="badge">7 个模型</span></h3>
                <table class="compare-table">
                    <thead>
                        <tr>
                            <th>大模型</th>
                            <th>排名位置</th>
                            <th>提及次数</th>
                            <th>情感倾向</th>
                            <th>推荐状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>${modelRows}</tbody>
                </table>
            </div>

            <div class="detail-section">
                <h3>AI 回答原文摘录 <span class="badge">命中率标记</span></h3>
                ${answerSnippets}
            </div>

            <div class="detail-section">
                <h3>时间维度对比 <span class="badge">环比 / 同比</span></h3>
                <div class="compare-trend">
                    <div class="compare-trend-card">
                        <div class="compare-trend-title">本周 vs 上周</div>
                        <div class="compare-trend-value">${q.mentionRate}% → ${q.mentionRate}%</div>
                        <div class="metric-change up">↑ ${q.change}</div>
                    </div>
                    <div class="compare-trend-card">
                        <div class="compare-trend-title">本月 vs 上月</div>
                        <div class="compare-trend-value">${(q.mentionRate - 3.2).toFixed(1)}% → ${q.mentionRate}%</div>
                        <div class="metric-change up">↑ +3.2%</div>
                    </div>
                </div>
            </div>

            <div class="detail-section">
                <h3>下钻分析 <span class="badge">多级标签体系</span></h3>
                <div style="display:flex;gap:12px;flex-wrap:wrap;">
                    <div style="padding:12px 16px;background:var(--bg-page);border-radius:8px;cursor:pointer;" onclick="App.toast('进入二级下钻：${q.tag} 分类详情')">
                        <strong style="font-size:13px;">一级：${q.tag}</strong>
                        <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;">42 个关联问题 →</div>
                    </div>
                    <div style="padding:12px 16px;background:var(--bg-page);border-radius:8px;cursor:pointer;" onclick="App.toast('进入三级下钻')">
                        <strong style="font-size:13px;">二级：${q.concernHits[0] || '通用'}</strong>
                        <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;">18 个关联问题 →</div>
                    </div>
                    <div style="padding:12px 16px;background:var(--bg-page);border-radius:8px;cursor:pointer;" onclick="App.toast('进入四级下钻')">
                        <strong style="font-size:13px;">三级：具体问题实例</strong>
                        <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;">6 个实例 →</div>
                    </div>
                </div>
            </div>
        `;
    },

    /* ---------- 竞品分析渲染 ---------- */
    renderCompetitor() {
        const tbody = document.getElementById('competitor-tbody');
        if (!tbody) return;
        tbody.innerHTML = COMPETITORS.map(c => `
            <tr>
                <td>
                    <span style="display:inline-flex;align-items:center;gap:8px;">
                        <span style="width:10px;height:10px;border-radius:50%;background:${c.color};"></span>
                        <strong>${c.name}</strong>
                    </span>
                </td>
                <td><strong>${c.top3Rate}%</strong></td>
                <td>${c.recommendRate}%</td>
                <td style="color:${c.sentiment >= 0.7 ? 'var(--color-success)' : c.sentiment >= 0.5 ? 'var(--color-warning)' : 'var(--color-danger)'};font-weight:600;">
                    ${(c.sentiment * 100).toFixed(0)}%
                </td>
                <td class="${c.trend === 'up' ? 'rate-high' : 'rate-low'}">
                    ${c.trend === 'up' ? '↑' : '↓'} ${c.change}
                </td>
            </tr>
        `).join('');
    },

    renderCompetitorCharts() {
        const trendEl = document.getElementById('chart-competitor-trend');
        if (trendEl) {
            Charts.lineChart(trendEl, {
                labels: COMPETITOR_TREND.labels,
                series: COMPETITOR_TREND.competitors,
                height: 320,
            });
        }
    },

    /* ---------- 信源偏好渲染 ---------- */
    renderSources() {
        const pieEl = document.getElementById('chart-source-pie');
        if (pieEl) {
            Charts.donutChart(pieEl, {
                items: SOURCE_CATEGORIES.map(s => ({
                    label: s.name,
                    value: s.count,
                    color: s.color,
                })),
                height: 280,
            });
        }

        const compareEl = document.getElementById('chart-source-compare');
        if (compareEl) {
            Charts.groupedBar(compareEl, {
                labels: ['官网', '新闻', '社交', '百科', '海外', '论坛', '自媒体'],
                groups: [
                    { name: '自身', color: '#1a55e8', data: [142, 286, 324, 96, 68, 234, 126] },
                    { name: '竞品均值', color: '#ff6b1a', data: [98, 210, 268, 82, 152, 186, 98] },
                ],
                height: 280,
            });
        }

        const trendEl = document.getElementById('chart-source-trend');
        if (trendEl) {
            Charts.areaTrend(trendEl, {
                labels: SOURCE_TREND.labels,
                added: SOURCE_TREND.added,
                lost: SOURCE_TREND.lost,
                height: 260,
            });
        }

        const grid = document.getElementById('model-source-grid');
        if (grid) {
            grid.innerHTML = MODEL_SOURCES.map(ms => `
                <div class="model-source-card">
                    <div class="model-source-name">
                        <span class="model-dot" style="background:${ms.color};"></span>
                        ${ms.model}
                        <span style="margin-left:auto;font-size:12px;color:var(--text-tertiary);">${ms.totalSources} 个信源</span>
                    </div>
                    <div class="model-source-list">
                        ${ms.topSources.map(s => `
                            <div class="model-source-item">
                                <span class="source-name">${s.name}</span>
                                <span class="source-count">${s.count} 次</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        }
    },

    renderSourceCharts() {
        // 图表在 renderSources 中已渲染
        this.renderSources();
    },

    /* ---------- 引用源渲染 ---------- */
    renderCitations() {
        const tbody = document.getElementById('citation-tbody');
        if (!tbody) return;
        tbody.innerHTML = CITATIONS.map(c => {
            const drClass = c.dr >= 80 ? 'dr-high' : c.dr >= 50 ? 'dr-mid' : 'dr-low';
            const drLabel = c.dr >= 80 ? '高' : c.dr >= 50 ? '中' : '低';
            return `
                <tr>
                    <td>
                        <div style="max-width:320px;">
                            <strong style="font-size:13px;display:block;margin-bottom:2px;">${c.title}</strong>
                            <span style="font-size:12px;color:var(--text-tertiary);">${c.url}</span>
                        </div>
                    </td>
                    <td><span class="table-tag tag-${c.typeColor}">${c.type}</span></td>
                    <td>
                        <div class="domain-bar">
                            <span class="dr-tag ${drClass}">DR ${c.dr}</span>
                            <div class="domain-bar-fill">
                                <div class="domain-bar-fill-inner" style="width:${c.dr}%;"></div>
                            </div>
                        </div>
                    </td>
                    <td>${c.traffic}</td>
                    <td><strong>${c.citations}</strong></td>
                    <td><span class="table-tag tag-blue">${c.rankPos}</span></td>
                    <td><button class="btn btn-text">详情</button></td>
                </tr>
            `;
        }).join('');
    },

    /* ---------- AI 回答详情渲染 ---------- */
    renderAnswers() {
        const grid = document.getElementById('answer-grid');
        if (!grid) return;
        const q = QUESTIONS[0];
        grid.innerHTML = MODELS.map(m => {
            const ans = q.answers[m.name] || '暂未采集到该模型的回答，正在持续监控中...';
            const d = q.models[m.name];
            const rankClass = d && d.rank <= 1 ? 'rank-1' : d && d.rank <= 2 ? 'rank-2' : d && d.rank <= 3 ? 'rank-3' : 'rank-other';
            return `
                <div class="answer-card">
                    <div class="answer-card-header">
                        <span class="model-info">
                            <span class="model-dot" style="background:${m.color};"></span>
                            <strong>${m.name}</strong>
                            ${d ? `<span class="rank-pill ${rankClass}" style="margin-left:8px;">No.${d.rank}</span>` : ''}
                        </span>
                        <span style="font-size:12px;color:var(--text-tertiary);">${d ? d.mention + ' 次提及' : '未提及'}</span>
                    </div>
                    <div class="answer-card-body">
                        ${ans.replace(/\*\*(.+?)\*\*/g, '<mark>$1</mark>')}
                    </div>
                    <div class="answer-card-footer">
                        <span>采集时间：2026-08-05 08:30</span>
                        <span>情感倾向：${d ? (d.sentiment * 100).toFixed(0) + '%' : 'N/A'}</span>
                    </div>
                </div>
            `;
        }).join('');
    },

    /* ---------- 查看原文 ---------- */
    viewAnswer(modelName) {
        this.switchTab('answer');
        setTimeout(() => {
            const filters = document.querySelectorAll('#tab-answer .answer-filters select');
            if (filters[1]) {
                const select = filters[1];
                for (let opt of select.options) {
                    if (opt.text === modelName) { select.selectedIndex = opt.index; break; }
                }
            }
        }, 100);
    },

    /* ---------- 快捷操作 ---------- */
    quickAction(type) {
        const actions = {
            'question': '新建监控问题',
            'keyword': '新建关键词',
            'project': '新建项目',
            'export-raw': '正在导出项目原始数据...',
            'export-weekly': '正在生成本周周报...',
            'competitor': '新增竞品',
            'source-dict': '导入官方媒体字典',
        };
        const msg = actions[type] || '执行操作';
        if (type === 'export-raw' || type === 'export-weekly') {
            this.toast(msg);
            setTimeout(() => this.toast('导出完成！文件已保存到下载目录'), 1500);
        } else {
            this.toast(msg + ' - 弹窗将在此打开（原型演示）');
        }
    },

    /* ---------- 全局搜索 ---------- */
    openSearch() {
        document.getElementById('global-search-modal').classList.add('active');
    },
    closeSearch(e) {
        if (e.target.id === 'global-search-modal' || e.type === 'keydown') {
            document.getElementById('global-search-modal').classList.remove('active');
        }
    },

    /* ---------- 通知 ---------- */
    toggleNotify() {
        document.getElementById('notify-dropdown').classList.toggle('active');
    },

    /* ---------- 项目切换 ---------- */
    openProjectSwitch() {
        this.toast('项目切换器（原型演示）');
    },

    /* ---------- 侧边栏折叠 ---------- */
    toggleSidebar() {
        const sidebar = document.querySelector('.app-sidebar');
        sidebar.classList.toggle('collapsed');
        if (sidebar.classList.contains('collapsed')) {
            sidebar.style.width = '64px';
            document.querySelector('.page-app').style.gridTemplateColumns = '64px 1fr';
        } else {
            sidebar.style.width = '';
            document.querySelector('.page-app').style.gridTemplateColumns = '';
        }
    },

    /* ---------- 用户菜单 ---------- */
    toggleUserMenu() {
        this.toast('用户菜单（原型演示）');
    },

    /* ---------- Toast 提示 ---------- */
    toast(msg) {
        const el = document.getElementById('toast');
        if (!el) return;
        el.textContent = msg;
        el.classList.add('show');
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
    },

    /* ---------- 时间选择器 ---------- */
    setTimeRange(range) {
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.range === range);
        });
        this.toast(`已切换至 ${range} 天数据范围`);
        this.initCharts();
    },
};

/* ---------- 键盘快捷键 ---------- */
document.addEventListener('keydown', (e) => {
    // Ctrl+K 打开搜索
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        App.openSearch();
        return;
    }
    // ESC 关闭搜索
    if (e.key === 'Escape') {
        App.closeSearch({ target: { id: 'global-search-modal' }, type: 'keydown' });
        document.getElementById('notify-dropdown')?.classList.remove('active');
        return;
    }
    // 单键快捷（非输入框聚焦时）
    if (document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'SELECT' && document.activeElement.tagName !== 'TEXTAREA') {
        if (!e.ctrlKey && !e.metaKey) {
            switch(e.key.toLowerCase()) {
                case 'q': App.quickAction('question'); break;
                case 'k': if (!e.ctrlKey) App.openSearch(); break;
                case 'p': App.quickAction('project'); break;
                case 'e': App.quickAction('export-raw'); break;
                case 'w': App.quickAction('export-weekly'); break;
            }
        }
    }
});

/* ---------- 二级 Tab 点击 ---------- */
document.addEventListener('click', (e) => {
    const tab = e.target.closest('.secondary-tab');
    if (tab && !tab.classList.contains('active')) {
        const siblings = tab.parentElement.querySelectorAll('.secondary-tab');
        siblings.forEach(s => s.classList.remove('active'));
        tab.classList.add('active');
    }
    // 时间选择器
    if (e.target.classList.contains('time-btn') && !e.target.classList.contains('active')) {
        const siblings = e.target.parentElement.querySelectorAll('.time-btn');
        siblings.forEach(s => s.classList.remove('active'));
        e.target.classList.add('active');
        App.toast(`已切换至 ${e.target.textContent.trim()} 数据范围`);
        App.initCharts();
    }
});

/* ---------- 窗口大小变化重绘图表 ---------- */
let resizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        if (document.getElementById('page-app').classList.contains('active')) {
            App.initCharts();
        }
    }, 300);
});
