# BTC自动交易机器人 + Web监控界面

策略不断的改进中，请关注demo站点ai-okx.zhongdu.net

1113总结：经过连续2周的测试，15分钟交易周期账户总权益有赚有赔，整体总权益基本没有太大变化，现有demo改为1h时间周期测试，原策略不变（ai决策，buy或shell下单并设置止盈止损，hold信号不变止盈止损）
本次更新只是变更了一下时间周期，其他没有变化。

**前期测试了很多项目，亏的一塌糊涂，切记切记**
不稳定盈利不要轻易开仓尝试，或轻仓尝试

## ⚠️ 重要提示：单向持仓模式

本程序使用 **单向持仓** 模式，请确保您的账户设置正确！

## 🚀 最新更新 v3.0.0：震荡市策略优化版

### 🔥 **核心优化 - 解决震荡市亏损问题**
- **🎯 震荡市智能识别**：自动检测价格区间<4%、ATR<1.5%的震荡行情
- **⚡ 快速交易防护**：新增5分钟交易冷却期，彻底解决17:30买→17:31卖问题
- **📊 K线状态验证**：BUY信号只在阴线或下跌时触发，避免追高买入
- **🛡️ 震荡市专用风控**：0.8%止盈、0.5%止损、最大持仓2小时

### ✅ **新增功能**
- ✅ **区间交易策略**：支撑位买入、阻力位卖出，中点谨慎交易
- ✅ **AI信号验证增强**：集成K线阴线检测逻辑，确保信号合理性
- ✅ **环境变量支持**：`base_usdt_amount`等关键参数移至`.env`文件
- ✅ **Docker热重载**：无需修改代码，通过环境变量调整策略

📖 详细说明：查看下方**v3.0.0版本更新日志**

## 🎉 Web实时监控界面 v2.0

### ✨ 全新高端深色主题！专业交易平台级视觉体验

基于Streamlit框架的Web监控界面，实时展示：
- 💰 账户信息和持仓状态（毛玻璃卡片设计）
- 📊 BTC价格和涨跌幅（金色渐变大字体）
- 📈 收益曲线和绩效统计（深色图表主题）
- 🤖 AI实时决策分析（**动态发光效果**）
- 📝 完整交易记录（深色表格）

**新版特色：**
- 🎨 深紫蓝渐变背景
- ✨ AI信号呼吸发光动画
- 🔮 毛玻璃效果卡片
- 🌈 专业配色方案
- 📱 响应式设计

### 🎯 方式一：宝塔面板一键部署

### 服务器部署，推荐美国vps服务器部署，价格便宜，访问速度。
推荐美国老牌服务器厂商RackNerd稳定服务器**支持支付宝付款**
- [推荐：满足要求型：1核心1G内存24GSSD2T带宽11.29美元/年](https://my.racknerd.com/aff.php?aff=13902&pid=903)
- [进阶型：1核心2G内存40GSSD3.5T带宽18.29美元/年](https://my.racknerd.com/aff.php?aff=13902&pid=904)
- [推荐型：2核心3.5G内存65GSSD7T带宽32.49美元/年](https://my.racknerd.com/aff.php?aff=13902&pid=905)
- [高端型：4核心6G内存140GSSD12T带宽59.99美元/年](https://my.racknerd.com/aff.php?aff=13902&pid=907)

### 如活动失效或显示库存不足，推荐购买七牛云新加坡服务器

- [进阶型：1核心2G内存20GSSD3.5T带宽50M138元人民币/年](https://s.qiniu.com/bAn6N3)
- [推荐型：2核心4G内存40GSSD7T带宽100M250元人民币/年](https://s.qiniu.com/Abu6Jb)
- 
**适合VPS/云服务器，图形化管理，自动重启保障！**

```bash
# 1. 安装宝塔面板（请去官方获取最新安装命令）
wget -O install.sh http://download.bt.cn/install/install_6.0.sh && sh install.sh

# 2. 安装Python项目管理器
# 在宝塔面板 -> 软件商店 -> 搜索"Python项目管理器" -> 安装

# 3. 添加项目，启动文件选择: run.py
```

然后通过域名或IP访问Web界面

📖 详细宝塔部署说明：[宝塔面板部署指南.md](宝塔面板部署指南.md)

### 🐳 方式二：Docker部署（推荐本地/开发）

##### 2.1 前置要求
- 安装 [Docker](https://www.docker.com/get-started) 
- 安装 [Docker Compose](https://docs.docker.com/compose/install/)

##### 2.2 快速启动

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd ds-main

# 2. 创建配置文件
cp .env.example .env
# 编辑.env文件，填入你的API密钥

# 3. 启动容器
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 停止服务
docker-compose down
```

##### 2.3 常用命令

```bash
# 查看运行状态
docker-compose ps

# 重启服务
docker-compose restart

# 更新镜像并重启
docker-compose pull
docker-compose up -d

# 进入容器调试
docker-compose exec btc-trading-bot bash

# 查看实时日志
docker-compose logs -f --tail=100
```

然后在浏览器访问：http://localhost:8501

📖 详细Docker部署说明：[DOCKER部署指南.md](DOCKER部署指南.md)

### 🐍 方式三：Python直接运行（推荐开发调试）

```bash
# 1. 创建虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境linux环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动交易程序（终端1）
python deepseekok2.py

# 启动Web界面（终端2）
streamlit run streamlit_app.py

# 或直接启动(以上两个命令二合一)
python run.py
```

然后在浏览器访问：http://localhost:8501

---

## 配置内容

### 配置文件建在策略根目录

### 拷贝模板文件到新名字：.env

cp .env_template .env

```env
DEEPSEEK_API_KEY=你的deepseek api密钥
BINANCE_API_KEY=
BINANCE_SECRET=
OKX_API_KEY=
OKX_SECRET=
OKX_PASSWORD=
```
💡 **详细配置说明**: 查看 [ENV_CONFIG.md](ENV_CONFIG.md) 获取完整配置指南

#### 获取API密钥

**AI模型：**

1. **DeepSeek API** (默认): https://platform.deepseek.com/
   - 注册账号
   - 创建API Key
   - 充值（按使用量计费，约0.14元/百万tokens）
   - 模型：deepseek-chat


**交易所：**

2. **OKX API**: https://www.gtohfmmy.com/join/6746503
   - 使用邀请码注册并完成任务，最高获100usdt奖励
   - API管理 → 创建API
   - 权限：需要"交易"权限
   - **重要**：妥善保管密钥，不要泄露

### 4. 交易参数配置

deepseekok2.py中修改交易参数

*** 投入保证金计算公式=下单基数*信心系数*仓位比例%*趋势系数 ***
例：基数100usdt，中信心，仓位0.5，高趋势，保证金=100*1*0.5*1.2=60

```
TRADE_CONFIG = {
    'symbol': 'BTC/USDT:USDT',  # OKX的合约符号格式
    'leverage': 10,  # 杠杆倍数,只影响保证金不影响下单价值
    'timeframe': '15m',  # 使用15分钟K线
    'test_mode': False,  # 测试模式
    'data_points': 96,  # 24小时数据（96根15分钟K线）
    'analysis_periods': {
        'short_term': 20,  # 短期均线
        'medium_term': 50,  # 中期均线
        'long_term': 96  # 长期趋势
    },
    # 新增智能仓位参数
    'position_management': {
        'enable_intelligent_position': True,  # 🆕 新增：是否启用智能仓位管理
        'base_usdt_amount': 100,  # USDT投入下单基数
        'high_confidence_multiplier': 1.5,  # 高信心系数
        'medium_confidence_multiplier': 1.0,  # 中信心系数
        'low_confidence_multiplier': 0.5,  # 低信心系数
        'max_position_ratio': 50,  # 单次最大仓位比例默认50%
        'trend_strength_multiplier': 1.2  # 趋势系数
    }
```

## 📁 项目文件说明

### 核心文件
- `run.py` - **统一启动入口**（宝塔面板使用）
- `deepseekok2.py` - 主交易程序
- `streamlit_app.py` - Web监控界面
- `data_manager.py` - 数据共享模块
- `requirements.txt` - Python依赖包

### Docker部署文件 🐳
- `Dockerfile` - Web界面镜像
- `Dockerfile.trading` - 交易程序镜像
- `docker-compose.yml` - Docker编排配置
- `docker-start.bat/.sh` - Docker一键启动
- `docker-stop.bat/.sh` - Docker停止脚本
- `env.template` - 环境变量模板
- `DOCKER部署指南.md` - Docker详细文档

### 启动脚本
- `启动交易程序.bat/.sh` - 交易程序启动脚本
- `启动Web界面.bat/.sh` - Web界面启动脚本
- `重启Web界面.bat` - Web界面重启脚本
- `检查状态.py` - 系统状态诊断工具

### 文档
- `部署成功.md` - **✅ 宝塔部署成功案例**
- `宝塔部署问题修复.md` - 故障排除完整指南
- `DOCKER部署指南.md` - Docker完整指南

## 🚀 部署方式对比

| 特性 | 宝塔面板 | Docker部署 | Python直接运行 |
|-----|---------|-----------|---------------|
| 图形化管理 | ✅ 完整Web界面 | ⚠️ 命令行 | ❌ 无 |
| 环境配置 | ✅ 自动处理 | ✅ 无需配置 | ⚠️ 需配置Python |
| 依赖管理 | ✅ 一键安装 | ✅ 自动处理 | ⚠️ 手动安装 |
| 启动方式 | ✅ 单入口启动 | ✅ 一键启动 | ⚠️ 分别启动 |
| 自动重启 | ✅ 支持 | ✅ 支持 | ❌ 不支持 |
| 日志管理 | ✅ 集中查看 | ⚠️ 分散 | ❌ 无 |
| 域名绑定 | ✅ 内置支持 | ⚠️ 需配置 | ❌ 不支持 |
| 资源占用 | ✅ 较低 | ⚠️ 稍高 | ✅ 最低 |
| 推荐场景 | **VPS/云服务器** | 本地/容器化环境 | 开发调试 |

---

## 📋 版本更新日志

### 🎯 **v3.0.0 - 震荡市策略优化版** (2025-11-21)

#### 🔥 **核心优化**
- **震荡市智能识别**：新增`identify_market_condition()`函数，自动识别价格区间<4%、ATR<1.5%的震荡行情
- **区间交易策略**：支撑位买入、阻力位卖出，中点谨慎交易
- **快速交易防护**：新增5分钟交易冷却期，彻底解决17:30买→17:31卖的频繁交易问题
- **K线状态验证**：BUY信号只在阴线或下跌≥0.2%时触发，避免追高买入

#### 🛡️ **风控升级**
- **震荡市专用风控**：
  - 每日最多2次交易
  - 盈利0.8%立即止盈
  - 亏损0.5%立即止损
  - 最大持仓2小时
  - 单笔仓位≤60%
- **AI信号验证增强**：集成K线阴线检测逻辑，确保信号合理性
- **交易连续性**：集成上次交易信号信息，避免快速反向交易

#### ⚙️ **配置优化**
- **环境变量支持**：`base_usdt_amount`等关键参数移至`.env`文件，支持Docker热重载
- **参数动态调整**：无需修改代码，通过环境变量即可调整交易策略
- **代码清理**：移除未使用变量，修复语法警告，提升代码质量

#### 📊 **技术实现**
- 新增`validate_ai_signal()`函数增强版：
  - `get_current_kline_state()`：实时K线状态检测
  - `check_trade_cooldown()`：5分钟交易冷却期
  - 阴线买入验证逻辑
- 新增`detect_trading_range()`：支撑位/阻力位自动识别
- 优化AI提示词：增强震荡市策略描述和风控规则

#### 🎯 **预期效果**
- **减少频繁交易**：5分钟冷却期将显著降低快速反转交易
- **提高买入时机**：只在阴线或下跌时触发，避免追涨杀跌
- **震荡市盈利提升**：区间交易策略配合严格风控
- **部署便利性**：Docker环境变量配置，支持热更新

#### 🔧 **配置变更**
```bash
# 新增环境变量配置（.env文件）
BASE_USDT_AMOUNT=25           # 基础投入金额
TIMEFRAME=15m                 # 交易周期
DATA_POINTS=96               # 数据点数
```

---

### 🚀 **v2.1 - 真实止盈止损订单** (2025-11-15)
- ✅ 自动设置OKX真实止盈止损订单
- ✅ 实时风险保护，价格触发立即执行
- ✅ 智能订单管理，平仓时自动取消旧订单

### 🎨 **v2.0 - Web界面升级** (2025-11-10)
- ✨ 全新深色主题界面
- 📊 实时数据监控
- 📈 收益曲线可视化
- 🤖 AI决策动态展示

### ⚡ **v1.0 - 基础交易功能** (2025-11-01)
- 🤖 AI驱动的交易决策
- 📊 多时间框架技术分析
- 💰 智能仓位管理
- 🔄 自动止盈止损


