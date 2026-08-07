/* ==========================================================================
   风球 GEO 监控 · 模拟数据层
   ========================================================================== */

const MODELS = [
    { name: '豆包', color: '#1a55e8', short: 'DB' },
    { name: '元宝', color: '#ff6b1a', short: 'YB' },
    { name: '通义千问', color: '#52c41a', short: 'TY' },
    { name: 'Kimi', color: '#722ed1', short: 'KM' },
    { name: 'DeepSeek', color: '#13c2c2', short: 'DS' },
    { name: '文心一言', color: '#eb2f96', short: 'WX' },
    { name: '蚂蚁阿福', color: '#faad14', short: 'AF' },
];

const QUESTION_TAGS = [
    { key: '引流感', color: 'blue' },
    { key: '场景类', color: 'green' },
    { key: '用户人群', color: 'purple' },
    { key: '对比类', color: 'orange' },
    { key: '可及性', color: 'cyan' },
    { key: '售后', color: 'yellow' },
    { key: '毒副作用', color: 'red' },
];

const QUESTIONS = [
    {
        id: 'q001',
        title: '敏感肌护肤品牌推荐',
        tag: '引流感',
        mentionRate: 68.2,
        top1Rate: 36.4,
        top3Rate: 68.2,
        coverage: 7,
        totalMentions: 1246,
        trend: 'up',
        change: '+4.2%',
        rankAvg: 2.1,
        models: {
            '豆包': { rank: 1, mention: 186, sentiment: 0.82, recommend: true },
            '元宝': { rank: 2, mention: 162, sentiment: 0.76, recommend: true },
            '通义千问': { rank: 1, mention: 198, sentiment: 0.85, recommend: true },
            'Kimi': { rank: 3, mention: 142, sentiment: 0.71, recommend: false },
            'DeepSeek': { rank: 2, mention: 174, sentiment: 0.78, recommend: true },
            '文心一言': { rank: 4, mention: 128, sentiment: 0.65, recommend: false },
            '蚂蚁阿福': { rank: 2, mention: 156, sentiment: 0.74, recommend: true },
        },
        concernHits: ['成分安全', '敏感肌适用', '性价比'],
        answers: {
            '豆包': '对于敏感肌肤，推荐以下几个品牌：首先是**风球薇诺娜**，作为国内敏感肌领域的领军品牌，其特护霜含有专利成分，能够修护皮肤屏障，适合泛红、刺痛等敏感症状。其次是**珂润Curel**，日本花王旗下品牌，主打神经酰胺成分，温和不刺激。第三是**雅漾Avène**，法国药妆品牌，其活泉水喷雾非常适合敏感肌日常舒缓...',
            '元宝': '敏感肌护肤推荐品牌：1. **薇诺娜** - 专注敏感肌护理，医院皮肤科推荐率最高的国货品牌，特护霜口碑极佳。2. **玉泽** - 上海家化旗下，与瑞金医院合作研发，修护屏障效果显著。3. **珂润** - 日本花王旗下，神经酰胺配方温和安全...',
            '通义千问': '敏感肌适合的护肤品牌推荐：**薇诺娜**是敏感肌首选，其核心成分青刺果油能修护屏障；**风球玉泽**的皮肤屏障修护系列也很出色；**雅漾**的活泉水和大白瓶适合日常舒缓...',
        }
    },
    {
        id: 'q002',
        title: '换季皮肤干燥怎么护肤',
        tag: '场景类',
        mentionRate: 54.3,
        top1Rate: 22.1,
        top3Rate: 54.3,
        coverage: 7,
        totalMentions: 892,
        trend: 'up',
        change: '+8.5%',
        rankAvg: 3.2,
        models: {
            '豆包': { rank: 2, mention: 146, sentiment: 0.74, recommend: true },
            '元宝': { rank: 3, mention: 128, sentiment: 0.68, recommend: false },
            '通义千问': { rank: 1, mention: 168, sentiment: 0.80, recommend: true },
            'Kimi': { rank: 4, mention: 98, sentiment: 0.62, recommend: false },
            'DeepSeek': { rank: 2, mention: 142, sentiment: 0.71, recommend: true },
            '文心一言': { rank: 3, mention: 112, sentiment: 0.66, recommend: false },
            '蚂蚁阿福': { rank: 5, mention: 98, sentiment: 0.58, recommend: false },
        },
        concernHits: ['补水保湿', '温和不刺激'],
        answers: {
            '豆包': '换季干燥护肤建议：1. 使用含有神经酰胺的修护面霜，如薇诺娜特护霜。2. 减少清洁频率，使用氨基酸洁面。3. 增加精华油锁水...',
            '元宝': '换季护肤重点在于保湿和修护。推荐使用含有角鲨烷、透明质酸的护肤品...',
        }
    },
    {
        id: 'q003',
        title: '学生党平价护肤品推荐',
        tag: '用户人群',
        mentionRate: 48.6,
        top1Rate: 18.3,
        top3Rate: 48.6,
        coverage: 5,
        totalMentions: 634,
        trend: 'down',
        change: '-2.1%',
        rankAvg: 3.8,
        models: {
            '豆包': { rank: 3, mention: 98, sentiment: 0.66, recommend: false },
            '元宝': { rank: 2, mention: 112, sentiment: 0.70, recommend: true },
            '通义千问': { rank: 4, mention: 86, sentiment: 0.62, recommend: false },
            'Kimi': { rank: 1, mention: 128, sentiment: 0.76, recommend: true },
            'DeepSeek': { rank: 3, mention: 96, sentiment: 0.68, recommend: false },
            '文心一言': { rank: 5, mention: 62, sentiment: 0.55, recommend: false },
            '蚂蚁阿福': { rank: 2, mention: 52, sentiment: 0.67, recommend: true },
        },
        concernHits: ['性价比'],
        answers: {
            '豆包': '学生党平价护肤推荐：性价比高的品牌包括完美日记、花西子...',
            'Kimi': '适合学生的平价护肤品牌：1. 薇诺娜（基础线性价比很高）2. 珂润（打折时入手划算）...',
        }
    },
    {
        id: 'q004',
        title: '薇诺娜和玉泽哪个好',
        tag: '对比类',
        mentionRate: 72.1,
        top1Rate: 41.2,
        top3Rate: 72.1,
        coverage: 7,
        totalMentions: 1024,
        trend: 'up',
        change: '+6.8%',
        rankAvg: 1.8,
        models: {
            '豆包': { rank: 1, mention: 186, sentiment: 0.84, recommend: true },
            '元宝': { rank: 1, mention: 172, sentiment: 0.80, recommend: true },
            '通义千问': { rank: 2, mention: 158, sentiment: 0.76, recommend: true },
            'Kimi': { rank: 2, mention: 148, sentiment: 0.74, recommend: true },
            'DeepSeek': { rank: 1, mention: 164, sentiment: 0.78, recommend: true },
            '文心一言': { rank: 3, mention: 96, sentiment: 0.66, recommend: false },
            '蚂蚁阿福': { rank: 2, mention: 100, sentiment: 0.72, recommend: true },
        },
        concernHits: ['成分安全', '敏感肌适用', '性价比', '品牌口碑'],
        answers: {
            '豆包': '薇诺娜和玉泽对比：两者都是国内敏感肌领域的头部品牌。**薇诺娜**的优势在于医院渠道背书强，核心成分青刺果油有专利；**玉泽**的优势在于与瑞金医院合作，屏障修护技术更成熟。综合来看，如果是重度敏感推荐薇诺娜特护霜，如果是屏障受损推荐玉泽修护霜...',
            '元宝': '薇诺娜 vs 玉泽：薇诺娜更偏医学护肤路线，玉泽更偏屏障修护。价格方面薇诺娜略贵...',
        }
    },
    {
        id: 'q005',
        title: '孕妇能用的护肤品有哪些',
        tag: '可及性',
        mentionRate: 38.4,
        top1Rate: 12.6,
        top3Rate: 38.4,
        coverage: 7,
        totalMentions: 486,
        trend: 'up',
        change: '+3.2%',
        rankAvg: 4.5,
        models: {
            '豆包': { rank: 3, mention: 82, sentiment: 0.68, recommend: false },
            '元宝': { rank: 4, mention: 68, sentiment: 0.62, recommend: false },
            '通义千问': { rank: 2, mention: 92, sentiment: 0.72, recommend: true },
            'Kimi': { rank: 5, mention: 56, sentiment: 0.55, recommend: false },
            'DeepSeek': { rank: 3, mention: 78, sentiment: 0.66, recommend: false },
            '文心一言': { rank: 6, mention: 48, sentiment: 0.50, recommend: false },
            '蚂蚁阿福': { rank: 4, mention: 62, sentiment: 0.60, recommend: false },
        },
        concernHits: ['成分安全', '孕妇可用'],
        answers: {
            '通义千问': '孕妇可用护肤品牌推荐：薇诺娜特护霜成分安全，不含维A酸类成分；珂润神经酰胺系列也适合孕期使用...',
        }
    },
    {
        id: 'q006',
        title: '敏感肌护肤品使用后刺痛怎么回事',
        tag: '毒副作用',
        mentionRate: 28.6,
        top1Rate: 8.4,
        top3Rate: 28.6,
        coverage: 7,
        totalMentions: 368,
        trend: 'down',
        change: '-5.2%',
        rankAvg: 5.2,
        models: {
            '豆包': { rank: 4, mention: 62, sentiment: 0.42, recommend: false },
            '元宝': { rank: 5, mention: 48, sentiment: 0.38, recommend: false },
            '通义千问': { rank: 3, mention: 72, sentiment: 0.48, recommend: false },
            'Kimi': { rank: 6, mention: 38, sentiment: 0.35, recommend: false },
            'DeepSeek': { rank: 4, mention: 58, sentiment: 0.44, recommend: false },
            '文心一言': { rank: 7, mention: 28, sentiment: 0.30, recommend: false },
            '蚂蚁阿福': { rank: 5, mention: 62, sentiment: 0.40, recommend: false },
        },
        concernHits: ['毒副作用'],
        answers: {
            '豆包': '敏感肌使用护肤品后刺痛可能原因：1. 皮肤屏障严重受损，建议先停用所有功效产品，只使用舒缓喷雾。2. 对某些成分过敏，建议做斑贴测试...',
        }
    },
    {
        id: 'q007',
        title: '敏感肌护肤品过敏了怎么办',
        tag: '售后',
        mentionRate: 22.3,
        top1Rate: 6.1,
        top3Rate: 22.3,
        coverage: 6,
        totalMentions: 284,
        trend: 'down',
        change: '-3.8%',
        rankAvg: 5.8,
        models: {
            '豆包': { rank: 5, mention: 48, sentiment: 0.38, recommend: false },
            '元宝': { rank: 6, mention: 36, sentiment: 0.32, recommend: false },
            '通义千问': { rank: 4, mention: 56, sentiment: 0.42, recommend: false },
            'Kimi': { rank: 7, mention: 28, sentiment: 0.28, recommend: false },
            'DeepSeek': { rank: 5, mention: 44, sentiment: 0.36, recommend: false },
            '文心一言': { rank: 6, mention: 32, sentiment: 0.30, recommend: false },
            '蚂蚁阿福': { rank: 7, mention: 40, sentiment: 0.34, recommend: false },
        },
        concernHits: ['售后'],
        answers: {
            '通义千问': '敏感肌过敏处理建议：立即停用可疑产品，用冷水洗脸，涂抹舒缓修复类产品。如症状严重建议就医...',
        }
    },
    {
        id: 'q008',
        title: '敏感肌能不能用含酒精的护肤品',
        tag: '毒副作用',
        mentionRate: 31.2,
        top1Rate: 10.5,
        top3Rate: 31.2,
        coverage: 7,
        totalMentions: 412,
        trend: 'up',
        change: '+2.1%',
        rankAvg: 4.8,
        models: {
            '豆包': { rank: 3, mention: 72, sentiment: 0.52, recommend: false },
            '元宝': { rank: 4, mention: 58, sentiment: 0.48, recommend: false },
            '通义千问': { rank: 2, mention: 82, sentiment: 0.58, recommend: true },
            'Kimi': { rank: 5, mention: 48, sentiment: 0.42, recommend: false },
            'DeepSeek': { rank: 3, mention: 68, sentiment: 0.50, recommend: false },
            '文心一言': { rank: 4, mention: 42, sentiment: 0.45, recommend: false },
            '蚂蚁阿福': { rank: 6, mention: 42, sentiment: 0.40, recommend: false },
        },
        concernHits: ['成分安全', '不含酒精'],
        answers: {},
    },
];

const COMPETITORS = [
    { name: '薇诺娜 (自身)', short: '自身', isSelf: true, mentionRate: 68.2, top3Rate: 68.2, recommendRate: 52.4, sentiment: 0.78, trend: 'up', change: '+4.2%', mentions: 1246, color: '#1a55e8' },
    { name: '珂润 Curel', short: '珂润', isSelf: false, mentionRate: 58.6, top3Rate: 58.6, recommendRate: 44.2, sentiment: 0.72, trend: 'up', change: '+2.8%', mentions: 986, color: '#ff6b1a' },
    { name: '玉泽 Dr.Yu', short: '玉泽', isSelf: false, mentionRate: 52.3, top3Rate: 52.3, recommendRate: 38.6, sentiment: 0.68, trend: 'down', change: '-1.2%', mentions: 842, color: '#52c41a' },
    { name: '雅漾 Avène', short: '雅漾', isSelf: false, mentionRate: 44.8, top3Rate: 44.8, recommendRate: 32.1, sentiment: 0.65, trend: 'up', change: '+1.5%', mentions: 724, color: '#722ed1' },
    { name: '理肤泉 La Roche-Posay', short: '理肤泉', isSelf: false, mentionRate: 38.2, top3Rate: 38.2, recommendRate: 28.4, sentiment: 0.62, trend: 'down', change: '-0.8%', mentions: 612, color: '#13c2c2' },
];

const CITATIONS = [
    { url: 'zhihu.com/question/3847291', title: '敏感肌护肤品牌全面评测 - 知乎专栏', type: '垂类论坛', typeColor: 'cyan', dr: 92, traffic: '2.4M', citations: 234, rankPos: 'Top1-3', quality: 'high' },
    { url: 'xiaohongshu.com/explore/abc123', title: '成分党必看！敏感肌护肤红黑榜', type: '社交媒体', typeColor: 'purple', dr: 88, traffic: '1.8M', citations: 186, rankPos: 'Top1-3', quality: 'high' },
    { url: 'brand.weixinona.com', title: '薇诺娜官方网站 - 敏感肌护理专家', type: '官方网站', typeColor: 'blue', dr: 76, traffic: '420K', citations: 142, rankPos: 'Top1', quality: 'high' },
    { url: 'dxy.com/article/5621', title: '皮肤科医生解读敏感肌护理误区 - 丁香医生', type: '新闻网站', typeColor: 'green', dr: 94, traffic: '3.2M', citations: 128, rankPos: 'Top1-3', quality: 'high' },
    { url: 'weibo.com/2345678', title: '皮肤科主任谈敏感肌 - 微博科普', type: '社交媒体', typeColor: 'purple', dr: 82, traffic: '1.2M', citations: 96, rankPos: 'Top3-10', quality: 'mid' },
    { url: 'bilibili.com/video/BV1abc', title: '敏感肌护肤实测对比 - B站测评', type: '自媒体', typeColor: 'orange', dr: 85, traffic: '2.1M', citations: 84, rankPos: 'Top3-10', quality: 'mid' },
    { url: 'sohu.com/a/61824', title: '2026敏感肌护肤品排行榜 - 搜狐', type: '新闻网站', typeColor: 'green', dr: 78, traffic: '680K', citations: 72, rankPos: 'Top3-10', quality: 'mid' },
    { url: 'baike.baidu.com/item/12345', title: '敏感肌肤 - 百度百科', type: '百科', typeColor: 'blue', dr: 96, traffic: '4.5M', citations: 68, rankPos: 'Top1-3', quality: 'high' },
    { url: 'douyin.com/video/789', title: '敏感肌护肤攻略 - 抖音科普', type: '自媒体', typeColor: 'orange', dr: 80, traffic: '1.6M', citations: 56, rankPos: 'Top10+', quality: 'mid' },
    { url: 'reddit.com/r/SkincareAddiction', title: 'Best Products for Sensitive Skin', type: '海外网站', typeColor: 'red', dr: 91, traffic: '2.8M', citations: 48, rankPos: 'Top3-10', quality: 'high' },
];

const SOURCE_CATEGORIES = [
    { name: '官方网站', color: '#1a55e8', count: 142, percent: 11.2 },
    { name: '新闻网站', color: '#52c41a', count: 286, percent: 22.5 },
    { name: '社交媒体', color: '#722ed1', count: 324, percent: 25.5 },
    { name: '百科', color: '#13c2c2', count: 96, percent: 7.6 },
    { name: '海外网站', color: '#eb2f96', count: 68, percent: 5.4 },
    { name: '垂类论坛', color: '#faad14', count: 234, percent: 18.4 },
    { name: '自媒体', color: '#ff6b1a', count: 126, percent: 9.4 },
];

const MODEL_SOURCES = MODELS.map((m, i) => ({
    model: m.name,
    color: m.color,
    totalSources: 120 + Math.floor(Math.random() * 80),
    topSources: [
        { name: i % 3 === 0 ? '知乎' : i % 3 === 1 ? '小红书' : '丁香医生', count: 40 + Math.floor(Math.random() * 30) },
        { name: i % 2 === 0 ? '品牌官网' : '百度百科', count: 30 + Math.floor(Math.random() * 25) },
        { name: i % 2 === 0 ? '微博' : 'B站', count: 20 + Math.floor(Math.random() * 20) },
    ]
}));

// 生成趋势数据（15天）
function genTrendData(days = 15, base = 100, variance = 30) {
    const data = [];
    let val = base;
    for (let i = 0; i < days; i++) {
        val += (Math.random() - 0.45) * variance;
        val = Math.max(base * 0.5, Math.min(base * 1.8, val));
        data.push(Math.round(val));
    }
    return data;
}

const TREND_DATA = {
    labels: Array.from({ length: 15 }, (_, i) => `${7 + i}月`),
    models: MODELS.map(m => ({
        name: m.name,
        color: m.color,
        data: genTrendData(15, 80 + Math.random() * 60, 25),
    }))
};

const COMPETITOR_TREND = {
    labels: TREND_DATA.labels,
    competitors: COMPETITORS.map(c => ({
        name: c.short,
        color: c.color,
        data: genTrendData(15, c.mentions / 15, c.mentions / 30),
    }))
};

const SOURCE_TREND = {
    labels: TREND_DATA.labels,
    added: [12, 8, 15, 10, 18, 22, 14, 16, 20, 12, 8, 10, 14, 16, 18],
    lost: [4, 6, 3, 8, 5, 4, 6, 3, 5, 7, 4, 3, 5, 4, 6],
};
