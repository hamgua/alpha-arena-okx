import os
import time

from openai import OpenAI
import ccxt
import pandas as pd
import re
from dotenv import load_dotenv
import json
import requests
from datetime import datetime, timedelta
from data_manager import update_system_status, save_trade_record

load_dotenv()

# AI提供商配置（DeepSeek 或 Qwen3-Max）
AI_PROVIDER = os.getenv('AI_PROVIDER', 'deepseek').lower()
ai_client = None
AI_MODEL = None

if AI_PROVIDER == 'qwen':
    ai_client = OpenAI(
        api_key=os.getenv('QWEN_API_KEY'),
        base_url=os.getenv('QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible/v1')
    )
    AI_MODEL = os.getenv('QWEN_MODEL', 'qwen3-max')
else:
    ai_client = OpenAI(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    )
    AI_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')

# 初始化OKX交易所
exchange = ccxt.okx({
    'options': {
        'defaultType': 'swap',  # OKX使用swap表示永续合约
    },
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),  # OKX需要交易密码
})

# 交易参数配置 - 结合两个版本的优点
TRADE_CONFIG = {
    'symbol': 'BTC/USDT:USDT',  # OKX的合约符号格式
    'leverage': 10,  # 杠杆倍数,只影响保证金不影响下单价值。提高杠杆倍数增强收益敏感度
    'timeframe': os.getenv('TIMEFRAME', '15m'),  # 改为15分钟K线，保持交易频率
    'test_mode': False,  # 测试模式
    'data_points': int(os.getenv('DATA_POINTS', '96')),  # 24小时数据（96根15分钟K线）
    'analysis_periods': {
        'short_term': 20,  # 短期均线（20小时）
        'medium_term': 50,  # 中期均线（50小时，约2天）
        'long_term': 168  # 长期趋势（168小时，7天）
    },
    # 极致优化仓位参数 - 微小波动也能产生收益
    'position_management': {
        'enable_intelligent_position': True,
        'base_usdt_amount': 25,  # 大幅提高基础投入
        'high_confidence_multiplier': 5.0,  # 高信心时5倍仓位
        'medium_confidence_multiplier': 3.0,
        'low_confidence_multiplier': 2.0,
        'max_position_ratio': 0.9,  # 最大仓位90%
        'trend_strength_multiplier': 2.0,
        'micro_movement_multiplier': 3.0  # 小波动3倍放大
    },
    
    # 🆕 震荡市专用策略配置 - 解决无规律行情盈利问题
    # 📖 震荡市优化说明：
    # - 减少交易频率，提高单次盈利质量
    # - 增加震荡识别，避免追涨杀跌
    # - 动态仓位调整，降低震荡市风险
    'decline_detection': {
        'data_window': 30,           # 📈 更长分析窗口：30根K线（7.5小时）识别震荡
        'min_decline_duration': 8,   # 🎯 严格抄底：8根阴线（2小时）避免假信号
        'strong_decline_duration': 12, # 💪 强力抄底：12根阴线（3小时）确保底部
        'min_total_decline': 2.5,    # 📉 更高跌幅要求：2.5%才考虑抄底
        'strong_total_decline': 6.0, # 🚀 深度抄底：6%跌幅强力抄底
        'volume_confirmation': True, # ✅ 成交量确认防止假突破
        'require_reversal_signal': True  # 🔍 必须反转信号避免接飞刀
    },
    
    # 🆕 震荡市专用风控配置
    'oscillation_strategy': {
        'enabled': True,            # 启用震荡市策略
        'max_daily_trades': 2,      # 每日最多2次交易避免频繁操作
        'min_profit_threshold': 0.8, # 最小盈利目标0.8%即止盈
        'max_loss_threshold': 0.5,   # 最大亏损0.5%即止损
        'position_size_reduction': 0.6, # 震荡市仓位降低至60%
        'hold_time_limit': 120,     # 最长持仓2小时避免过夜风险
        'volatility_filter': 1.5    # 波动率过滤，低于1.5%不参与
    },
    
    # 🆕 区间交易策略配置
    'range_trading': {
        'enabled': True,            # 启用区间交易
        'range_detection_periods': 36, # 36根K线（9小时）识别区间
        'support_resistance_levels': 3,  # 确认3次高低点形成区间
        'entry_buffer': 0.2,        # 区间边界缓冲0.2%
        'range_break_stop': 0.3,    # 区间突破止损0.3%
        'midpoint_reversal': True   # 区间中点反转交易
    },
    
    # 🆕 Web监控界面配置 - 小白用户友好
    'web_interface': {
        'enabled': False,           # 是否启用Web监控界面（True=开启，False=关闭）
        'port': 8501,              # Web界面端口（默认8501）
        'auto_refresh': True,      # 是否自动刷新（True=每10秒刷新）
        'theme': 'dark'            # 界面主题（dark/light）
    }
}


def setup_exchange():
    """设置交易所参数 - 强制全仓模式"""
    try:

        # 首先获取合约规格信息
        print("🔍 获取BTC合约规格...")
        markets = exchange.load_markets()
        btc_market = markets[TRADE_CONFIG['symbol']]

        # 获取合约乘数
        contract_size = float(btc_market['contractSize'])
        print(f"✅ 合约规格: 1张 = {contract_size} BTC")

        # 存储合约规格到全局配置
        TRADE_CONFIG['contract_size'] = contract_size
        TRADE_CONFIG['min_amount'] = btc_market['limits']['amount']['min']

        print(f"📏 最小交易量: {TRADE_CONFIG['min_amount']} 张")

        # 先检查现有持仓
        print("🔍 检查现有持仓模式...")
        positions = exchange.fetch_positions([TRADE_CONFIG['symbol']])

        has_isolated_position = False
        isolated_position_info = None

        for pos in positions:
            if pos['symbol'] == TRADE_CONFIG['symbol']:
                contracts = float(pos.get('contracts', 0))
                mode = pos.get('mgnMode')

                if contracts > 0 and mode == 'isolated':
                    has_isolated_position = True
                    isolated_position_info = {
                        'side': pos.get('side'),
                        'size': contracts,
                        'entry_price': pos.get('entryPrice'),
                        'mode': mode
                    }
                    break

        # 2. 如果有逐仓持仓，提示并退出
        if has_isolated_position:
            print("❌ 检测到逐仓持仓，程序无法继续运行！")
            print(f"📊 逐仓持仓详情:")
            print(f"   - 方向: {isolated_position_info['side']}")
            print(f"   - 数量: {isolated_position_info['size']}")
            print(f"   - 入场价: {isolated_position_info['entry_price']}")
            print(f"   - 模式: {isolated_position_info['mode']}")
            print("\n🚨 解决方案:")
            print("1. 手动平掉所有逐仓持仓")
            print("2. 或者将逐仓持仓转为全仓模式")
            print("3. 然后重新启动程序")
            return False

        # 3. 设置单向持仓模式
        print("🔄 设置单向持仓模式...")
        try:
            exchange.set_position_mode(False, TRADE_CONFIG['symbol'])  # False表示单向持仓
            print("✅ 已设置单向持仓模式")
        except Exception as e:
            print(f"⚠️ 设置单向持仓模式失败 (可能已设置): {e}")

        # 4. 设置全仓模式和杠杆
        print("⚙️ 设置全仓模式和杠杆...")
        exchange.set_leverage(
            TRADE_CONFIG['leverage'],
            TRADE_CONFIG['symbol'],
            {'mgnMode': 'cross'}  # 强制全仓模式
        )
        print(f"✅ 已设置全仓模式，杠杆倍数: {TRADE_CONFIG['leverage']}x")

        # 5. 验证设置
        print("🔍 验证账户设置...")
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']
        print(f"💰 当前USDT余额: {usdt_balance:.2f}")

        # 获取当前持仓状态
        current_pos = get_current_position()
        if current_pos:
            print(f"📦 当前持仓: {current_pos['side']}仓 {current_pos['size']}张")
        else:
            print("📦 当前无持仓")

        print("🎯 程序配置完成：全仓模式 + 单向持仓")
        return True

    except Exception as e:
        print(f"❌ 交易所设置失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# 全局变量存储历史数据
price_history = []
signal_history = []
position = None

# 全局变量存储止盈止损订单ID
active_tp_sl_orders = {
    'take_profit_order_id': None,
    'stop_loss_order_id': None
}


def calculate_price_position(price_data):
    """计算当前价格在布林带中的相对位置（0-100%）"""
    try:
        kline_data = price_data.get('kline_data', [])
        if len(kline_data) < 20:
            return 50  # 数据不足，返回中性值
            
        closes = [k['close'] for k in kline_data[-20:]]  # 最近20根K线收盘价
        current_price = price_data['price']
        
        # 计算布林带
        sma_20 = sum(closes) / len(closes)
        std_dev = (sum((x - sma_20) ** 2 for x in closes) / len(closes)) ** 0.5
        
        upper_band = sma_20 + 2 * std_dev
        lower_band = sma_20 - 2 * std_dev
        
        # 计算相对位置（0-100）
        if upper_band == lower_band:
            return 50
            
        position = ((current_price - lower_band) / (upper_band - lower_band)) * 100
        return max(0, min(100, position))  # 限制在0-100之间
        
    except Exception as e:
        print(f"价格位置计算错误: {e}")
        return 50

def identify_market_condition(price_data):
    """识别市场状态：震荡市、趋势市、单边市"""
    try:
        kline_data = price_data.get('kline_data', [])
        if len(kline_data) < 30:
            return 'normal'
        
        # 获取最近30根K线数据
        recent_klines = kline_data[-30:]
        
        # 计算价格波动范围
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        closes = [k['close'] for k in recent_klines]
        
        highest_high = max(highs)
        lowest_low = min(lows)
        price_range = ((highest_high - lowest_low) / lowest_low) * 100
        
        # 计算平均真实波幅ATR
        atr_values = []
        for i in range(1, len(recent_klines)):
            prev_close = recent_klines[i-1]['close']
            curr_high = recent_klines[i]['high']
            curr_low = recent_klines[i]['low']
            
            tr1 = curr_high - curr_low
            tr2 = abs(curr_high - prev_close)
            tr3 = abs(curr_low - prev_close)
            atr_values.append(max(tr1, tr2, tr3))
        
        avg_atr = sum(atr_values) / len(atr_values) if atr_values else 0
        avg_atr_pct = (avg_atr / closes[-1]) * 100 if closes else 0
        
        # 计算趋势强度
        sma_10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else closes[-1]
        sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
        trend_strength = abs((sma_10 - sma_20) / sma_20) * 100
        
        # 震荡市识别条件
        if price_range < 4.0 and avg_atr_pct < 1.5 and trend_strength < 0.5:
            return 'oscillation'  # 震荡市
        elif trend_strength > 2.0:
            return 'trending'     # 趋势市
        else:
            return 'normal'       # 正常市
            
    except Exception as e:
        print(f"市场状态识别错误: {e}")
        return 'normal'

def detect_trading_range(price_data):
    """检测交易区间（支撑阻力位）"""
    try:
        config = TRADE_CONFIG['range_trading']
        kline_data = price_data.get('kline_data', [])
        periods = config['range_detection_periods']
        
        if len(kline_data) < periods:
            return None
        
        # 获取指定周期的K线数据
        recent_klines = kline_data[-periods:]
        
        # 寻找支撑和阻力位
        highs = [k['high'] for k in recent_klines]
        lows = [k['low'] for k in recent_klines]
        
        # 使用更严格的方法识别关键价位
        resistance_levels = []
        support_levels = []
        
        # 识别阻力位（多次测试的高点）
        for i in range(len(highs)):
            current_high = highs[i]
            # 检查这个高点是否被多次测试
            test_count = sum(1 for h in highs[max(0, i-5):i+5] if abs(h - current_high) < current_high * 0.002)
            if test_count >= config['support_resistance_levels']:
                resistance_levels.append(current_high)
        
        # 识别支撑位（多次测试的低点）
        for i in range(len(lows)):
            current_low = lows[i]
            # 检查这个低点是否被多次测试
            test_count = sum(1 for l in lows[max(0, i-5):i+5] if abs(l - current_low) < current_low * 0.002)
            if test_count >= config['support_resistance_levels']:
                support_levels.append(current_low)
        
        if not resistance_levels or not support_levels:
            return None
        
        # 取最可靠的支撑阻力位
        resistance = min(resistance_levels)  # 最严格的阻力位
        support = max(support_levels)        # 最严格的支撑位
        
        # 验证区间有效性
        if resistance <= support:
            return None
            
        range_height = ((resistance - support) / support) * 100
        
        # 检查区间是否在合理范围内
        if range_height < 0.5 or range_height > 4.0:  # 区间太窄或太宽都不适合
            return None
        
        current_price = price_data['price']
        
        # 判断当前价格在区间中的位置
        range_position = ((current_price - support) / (resistance - support)) * 100
        
        return {
            'support': support,
            'resistance': resistance,
            'midpoint': (support + resistance) / 2,
            'range_height': range_height,
            'position_in_range': range_position,
            'is_near_support': range_position < 25,      # 靠近支撑位
            'is_near_resistance': range_position > 75,   # 靠近阻力位
            'is_near_midpoint': 40 <= range_position <= 60  # 靠近中点
        }
        
    except Exception as e:
        print(f"区间检测错误: {e}")
        return None

def calculate_decline_pattern(price_data):
    """增强下跌确认和反转信号检测 - 使用配置文件参数"""
    try:
        config = TRADE_CONFIG['decline_detection']
        kline_data = price_data.get('kline_data', [])
        
        # 使用配置中的数据窗口
        data_window = config['data_window']
        if len(kline_data) < data_window:
            return {
                'consecutive_declines': 0, 
                'total_decline': 0.0, 
                'decline_duration': 0,
                'is_reversal': False,
                'confirmation_strength': 0,
                'volume_confirmation': False
            }
        
        # 使用配置中的数据窗口
        recent_klines = kline_data[-data_window:]
        
        # 🆕 计算下跌确认指标
        decline_data = {
            'consecutive_declines': 0,
            'total_decline': 0.0,
            'decline_duration': 0,
            'is_reversal': False,
            'confirmation_strength': 0,
            'volume_confirmation': False
        }
        
        # 1. 计算最长连续下跌序列
        max_consecutive = 0
        current_streak = 0
        total_decline = 0.0
        
        for kline in reversed(recent_klines):
            if kline['close'] < kline['open']:  # 阴线
                current_streak += 1
                decline = ((kline['open'] - kline['close']) / kline['open']) * 100
                total_decline += decline
                max_consecutive = max(max_consecutive, current_streak)
            else:
                break
        
        decline_data['consecutive_declines'] = max_consecutive
        decline_data['total_decline'] = total_decline
        decline_data['decline_duration'] = max_consecutive * 15
        
        # 2. 🆕 反转信号确认
        if len(recent_klines) >= 4:
            last_4_klines = recent_klines[-4:]
            
            # 检查是否出现反转信号
            # 条件：最后3根下跌，第4根开始反弹
            if (len(last_4_klines) == 4 and 
                last_4_klines[0]['close'] < last_4_klines[0]['open'] and  # 第1根下跌
                last_4_klines[1]['close'] < last_4_klines[1]['open'] and  # 第2根下跌
                last_4_klines[2]['close'] < last_4_klines[2]['open'] and  # 第3根下跌
                last_4_klines[3]['close'] > last_4_klines[3]['open']):    # 第4根反弹
                decline_data['is_reversal'] = True
                decline_data['confirmation_strength'] = 3
            
            # 检查是否有长下影线（锤子线信号）
            for kline in last_4_klines[-2:]:  # 最后2根
                body_size = abs(kline['close'] - kline['open'])
                lower_shadow = min(kline['open'], kline['close']) - kline['low']
                upper_shadow = kline['high'] - max(kline['open'], kline['close'])
                
                if lower_shadow > body_size * 2 and upper_shadow < body_size * 0.5:
                    decline_data['is_reversal'] = True
                    decline_data['confirmation_strength'] = 2
        
        # 3. 🆕 成交量确认
        if len(recent_klines) >= 5:
            volumes = [k.get('volume', 0) for k in recent_klines[-5:]]
            if volumes and len(volumes) >= 3:
                avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
                last_volume = volumes[-1]
                # 反转时成交量放大确认
                if last_volume > avg_volume * 1.5:
                    decline_data['volume_confirmation'] = True
        
        return decline_data
        
    except Exception as e:
        print(f"下跌确认计算错误: {e}")
        return {
            'consecutive_declines': 0, 
            'total_decline': 0.0, 
            'decline_duration': 0,
            'is_reversal': False,
            'confirmation_strength': 0
        }

def calculate_intelligent_position(signal_data, price_data):
    """计算智能仓位大小 - 修复版"""
    config = TRADE_CONFIG['position_management']

    # 🆕 新增：如果禁用智能仓位，使用固定仓位
    if not config.get('enable_intelligent_position', True):
        fixed_contracts = 0.1  # 固定仓位大小，可以根据需要调整
        print(f"🔧 智能仓位已禁用，使用固定仓位: {fixed_contracts} 张")
        return fixed_contracts

    try:
        # 获取账户余额 - 确保最小交易量
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']
        
        # 使用账户大部分余额，确保最小交易量
        base_usdt = min(config['base_usdt_amount'], usdt_balance * 0.85)  # 使用85%余额
        print(f"💰 可用USDT余额: {usdt_balance:.2f}, 实际下单基数{base_usdt}")

        # 根据信心程度调整 - 修复这里
        confidence_multiplier = {
            'HIGH': config['high_confidence_multiplier'],
            'MEDIUM': config['medium_confidence_multiplier'],
            'LOW': config['low_confidence_multiplier']
        }.get(signal_data['confidence'], 1.0)  # 添加默认值

        # 根据趋势强度调整
        trend = price_data['trend_analysis'].get('overall', '震荡整理')
        if trend in ['强势上涨', '强势下跌']:
            trend_multiplier = config['trend_strength_multiplier']
        else:
            trend_multiplier = 1.0

        # 🎯 增强连续下跌抄底策略
        rsi = price_data['technical_data'].get('rsi', 50)
        
        # 计算价格相对位置权重
        price_position = calculate_price_position(price_data)
        
        # 🆕 计算连续下跌指标
        decline_data = calculate_decline_pattern(price_data)
        decline_multiplier = 1.0
        
        # 🆕 震荡市智能策略
        market_condition = identify_market_condition(price_data)
        osc_config = TRADE_CONFIG['oscillation_strategy']
        
        # 根据市场状态调整策略
        if market_condition == 'oscillation' and osc_config['enabled']:
            print(f"🌊 检测到震荡市，启用震荡策略")
            
            # 震荡市仓位降低
            position_multiplier = osc_config['position_size_reduction']
            print(f"📉 震荡市仓位降低至{position_multiplier*100:.0f}%")
            
            # 严格入场条件
            if decline_data['consecutive_declines'] < 6:  # 震荡市要求更高
                print("🚫 震荡市：下跌不够深，跳过抄底")
                return 0
                
            # 🆕 使用配置文件参数的增强抄底确认机制
        decline_config = TRADE_CONFIG['decline_detection']
        
        # 1. 反转确认优先（必须满足配置要求）
        if decline_config['require_reversal_signal'] and decline_data['is_reversal']:
            if decline_data['confirmation_strength'] >= 3:
                decline_multiplier *= 2.5
                print(f"🔄 强反转确认，抄底权重: 2.5x")
            elif decline_data['confirmation_strength'] >= 2:
                decline_multiplier *= 1.8
                print(f"🔄 中等反转确认，抄底权重: 1.8x")
        
        # 2. 长期下跌确认（使用配置阈值）
        elif decline_data['consecutive_declines'] >= decline_config['strong_decline_duration']:
            if decline_config['volume_confirmation'] and decline_data['volume_confirmation']:
                decline_multiplier *= 2.0
                print(f"🔻 长期下跌{decline_data['decline_duration']}分钟+放量确认，强力抄底: 2.0x")
            else:
                decline_multiplier *= 1.6
                print(f"📉 长期下跌{decline_data['decline_duration']}分钟，谨慎抄底: 1.6x")
        
        # 3. 中期下跌确认
        elif decline_data['consecutive_declines'] >= decline_config['min_decline_duration']:
            decline_multiplier *= 1.3
            print(f"📊 中期下跌{decline_data['decline_duration']}分钟，抄底权重: 1.3x")
        
        # 4. 下跌幅度补充权重（使用配置阈值）
        if decline_data['total_decline'] > decline_config['strong_total_decline']:
            decline_multiplier *= 1.2
            print(f"📊 深度下跌{decline_data['total_decline']:.2f}%，补充权重: 1.2x")
        elif decline_data['total_decline'] > decline_config['min_total_decline']:
            decline_multiplier *= 1.1
            print(f"📊 中度下跌{decline_data['total_decline']:.2f}%，补充权重: 1.1x")
        
        # 5. 🆕 震荡市仓位调整
        position_weight = 1.0
        if market_condition == 'oscillation' and osc_config['enabled']:
            decline_multiplier *= osc_config['position_size_reduction']
            
            # 低位+下跌组合权重
            if price_position < 30 and decline_data['consecutive_declines'] >= 2:
                position_weight *= 2.2  # 低位+连续下跌，强力抄底
                print(f"🎯 低位({price_position:.1f}%) + 连续下跌，强力抄底: 2.2x")
            elif price_position < 40 and decline_data['consecutive_declines'] >= 2:
                position_weight *= 1.8  # 相对低位+连续下跌
                print(f"🎯 相对低位({price_position:.1f}%) + 连续下跌: 1.8x")
            elif price_position < 30:  # 仅价格低位
                position_weight *= 1.5
                print(f"🎯 价格低位({price_position:.1f}%)，加大仓位权重: 1.5x")
            elif price_position > 70:  # 价格高位
                position_weight *= 0.7
                print(f"⚠️ 价格高位({price_position:.1f}%)，减小仓位权重: 0.7x")

        # 超敏感价格变化检测
        price_change = abs(price_data.get('price_change', 0))
        if price_change < 0.02:  # 极低波动
            micro_multiplier = decline_config.get('micro_movement_multiplier', 3.0)
        elif price_change < 0.05:
            micro_multiplier = 2.0
        elif price_change < 0.1:
            micro_multiplier = 1.5
        else:
            micro_multiplier = 1.0
            
        # RSI超卖超买权重调整
        rsi_multiplier = 1.0
        if rsi < 35:  # 超卖区域 - 加大买入权重
            rsi_multiplier = 1.4
            print(f"🟢 RSI超卖({rsi:.1f})，加大仓位权重: 1.4x")
        elif rsi > 70:  # 超买区域 - 减小买入权重
            rsi_multiplier = 0.6
            print(f"🔴 RSI超买({rsi:.1f})，减小仓位权重: 0.6x")

        # 🎯 计算最终仓位（加入连续下跌抄底权重）
        suggested_usdt = base_usdt * confidence_multiplier * trend_multiplier * rsi_multiplier * micro_multiplier * position_weight * decline_multiplier

        # 风险管理：不超过总资金的指定比例
        max_usdt = usdt_balance * config['max_position_ratio']
        final_usdt = min(suggested_usdt, max_usdt)

        # 正确的合约张数计算！
        # 公式：合约张数 = (投入USDT) / (当前价格 * 合约乘数)
        contract_size = (final_usdt) / (price_data['price'] * TRADE_CONFIG['contract_size'])

        print(f"📊 仓位计算详情:")
        print(f"   - 基础USDT: {base_usdt}")
        print(f"   - 信心倍数: {confidence_multiplier}")
        print(f"   - 趋势倍数: {trend_multiplier}")
        print(f"   - RSI倍数: {rsi_multiplier}")
        print(f"   - 位置权重: {position_weight}")
        print(f"   - 下跌权重: {decline_multiplier}")
        print(f"   - 波动倍数: {micro_multiplier}")
        print(f"   - 建议USDT: {suggested_usdt:.2f}")
        print(f"   - 最终USDT: {final_usdt:.2f}")
        print(f"   - 合约乘数: {TRADE_CONFIG['contract_size']}")
        print(f"   - 计算合约: {contract_size:.4f} 张")

        # 精度处理：OKX BTC合约最小交易单位为0.01张
        contract_size = round(contract_size, 2)  # 保留2位小数

        # 确保最小交易量
        min_contracts = max(TRADE_CONFIG.get('min_amount', 0.01), 0.05)  # 最小0.05张
        if contract_size < min_contracts:
            contract_size = min_contracts
            print(f"⚠️ 仓位小于最小值，调整为: {contract_size} 张")

        print(f"🎯 最终仓位: {final_usdt:.2f} USDT → {contract_size:.2f} 张合约")
        return contract_size

    except Exception as e:
        print(f"❌ 仓位计算失败，使用基础仓位: {e}")
        # 紧急备用计算
        base_usdt = config['base_usdt_amount']
        contract_size = (base_usdt * TRADE_CONFIG['leverage']) / (
                    price_data['price'] * TRADE_CONFIG.get('contract_size', 0.01))
        return round(max(contract_size, TRADE_CONFIG.get('min_amount', 0.01)), 2)


def calculate_technical_indicators(df):
    """计算技术指标 - 来自第一个策略"""
    try:
        # 移动平均线
        df['sma_5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['sma_20'] = df['close'].rolling(window=20, min_periods=1).mean()
        df['sma_50'] = df['close'].rolling(window=50, min_periods=1).mean()

        # 指数移动平均线
        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # 相对强弱指数 (RSI)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # 布林带
        df['bb_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # 成交量均线
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        # 支撑阻力位
        df['resistance'] = df['high'].rolling(20).max()
        df['support'] = df['low'].rolling(20).min()

        # 填充NaN值
        df = df.bfill().ffill()

        return df
    except Exception as e:
        print(f"技术指标计算失败: {e}")
        return df


def get_support_resistance_levels(df, lookback=20):
    """计算支撑阻力位"""
    try:
        recent_high = df['high'].tail(lookback).max()
        recent_low = df['low'].tail(lookback).min()
        current_price = df['close'].iloc[-1]

        resistance_level = recent_high
        support_level = recent_low

        # 动态支撑阻力（基于布林带）
        bb_upper = df['bb_upper'].iloc[-1]
        bb_lower = df['bb_lower'].iloc[-1]

        return {
            'static_resistance': resistance_level,
            'static_support': support_level,
            'dynamic_resistance': bb_upper,
            'dynamic_support': bb_lower,
            'price_vs_resistance': ((resistance_level - current_price) / current_price) * 100,
            'price_vs_support': ((current_price - support_level) / support_level) * 100
        }
    except Exception as e:
        print(f"支撑阻力计算失败: {e}")
        return {}


def get_sentiment_indicators():
    """获取情绪指标 - 简洁版本"""
    try:
        API_URL = "https://service.cryptoracle.network/openapi/v2/endpoint"
        API_KEY = os.getenv('CRYPTO_ORACLE_API_KEY')

        if not API_KEY:
            return None

        # 获取最近4小时数据
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=4)

        request_body = {
            "apiKey": API_KEY,
            "endpoints": ["CO-A-02-01", "CO-A-02-02"],  # 只保留核心指标
            "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeType": "15m",
            "token": ["BTC"]
        }

        headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
        response = requests.post(API_URL, json=request_body, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200 and data.get("data"):
                time_periods = data["data"][0]["timePeriods"]

                # 查找第一个有有效数据的时间段
                for period in time_periods:
                    period_data = period.get("data", [])

                    sentiment = {}
                    valid_data_found = False

                    for item in period_data:
                        endpoint = item.get("endpoint")
                        value = item.get("value", "").strip()

                        if value:  # 只处理非空值
                            try:
                                if endpoint in ["CO-A-02-01", "CO-A-02-02"]:
                                    sentiment[endpoint] = float(value)
                                    valid_data_found = True
                            except (ValueError, TypeError):
                                continue

                    # 如果找到有效数据
                    if valid_data_found and "CO-A-02-01" in sentiment and "CO-A-02-02" in sentiment:
                        positive = sentiment['CO-A-02-01']
                        negative = sentiment['CO-A-02-02']
                        net_sentiment = positive - negative

                        # 正确的时间延迟计算
                        data_delay = int((datetime.now() - datetime.strptime(
                            period['startTime'], '%Y-%m-%d %H:%M:%S')).total_seconds() // 60)

                        print(f"✅ 使用情绪数据时间: {period['startTime']} (延迟: {data_delay}分钟)")

                        return {
                            'positive_ratio': positive,
                            'negative_ratio': negative,
                            'net_sentiment': net_sentiment,
                            'data_time': period['startTime'],
                            'data_delay_minutes': data_delay
                        }

                print("❌ 所有时间段数据都为空")
                return None

        return None
    except Exception as e:
        print(f"情绪指标获取失败: {e}")
        return None


def get_market_trend(df):
    """判断市场趋势"""
    try:
        current_price = df['close'].iloc[-1]

        # 多时间框架趋势分析
        trend_short = "上涨" if current_price > df['sma_20'].iloc[-1] else "下跌"
        trend_medium = "上涨" if current_price > df['sma_50'].iloc[-1] else "下跌"

        # MACD趋势
        macd_trend = "bullish" if df['macd'].iloc[-1] > df['macd_signal'].iloc[-1] else "bearish"

        # 综合趋势判断
        if trend_short == "上涨" and trend_medium == "上涨":
            overall_trend = "强势上涨"
        elif trend_short == "下跌" and trend_medium == "下跌":
            overall_trend = "强势下跌"
        else:
            overall_trend = "震荡整理"

        return {
            'short_term': trend_short,
            'medium_term': trend_medium,
            'macd': macd_trend,
            'overall': overall_trend,
            'rsi_level': df['rsi'].iloc[-1]
        }
    except Exception as e:
        print(f"趋势分析失败: {e}")
        return {}


def get_btc_ohlcv_enhanced():
    """增强版：获取BTC K线数据并计算技术指标"""
    try:
        # 获取K线数据
        ohlcv = exchange.fetch_ohlcv(TRADE_CONFIG['symbol'], TRADE_CONFIG['timeframe'],
                                     limit=TRADE_CONFIG['data_points'])

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # 计算技术指标
        df = calculate_technical_indicators(df)

        current_data = df.iloc[-1]
        previous_data = df.iloc[-2]

        # 获取技术分析数据
        trend_analysis = get_market_trend(df)
        levels_analysis = get_support_resistance_levels(df)

        return {
            'price': current_data['close'],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'high': current_data['high'],
            'low': current_data['low'],
            'volume': current_data['volume'],
            'timeframe': TRADE_CONFIG['timeframe'],
            'price_change': ((current_data['close'] - previous_data['close']) / previous_data['close']) * 100,
            'kline_data': df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(10).to_dict('records'),
            'technical_data': {
                'sma_5': current_data.get('sma_5', 0),
                'sma_20': current_data.get('sma_20', 0),
                'sma_50': current_data.get('sma_50', 0),
                'rsi': current_data.get('rsi', 0),
                'macd': current_data.get('macd', 0),
                'macd_signal': current_data.get('macd_signal', 0),
                'macd_histogram': current_data.get('macd_histogram', 0),
                'bb_upper': current_data.get('bb_upper', 0),
                'bb_lower': current_data.get('bb_lower', 0),
                'bb_position': current_data.get('bb_position', 0),
                'volume_ratio': current_data.get('volume_ratio', 0)
            },
            'trend_analysis': trend_analysis,
            'levels_analysis': levels_analysis,
            'full_data': df
        }
    except Exception as e:
        print(f"获取增强K线数据失败: {e}")
        return None


def generate_technical_analysis_text(price_data):
    """生成技术分析文本"""
    if 'technical_data' not in price_data:
        return "技术指标数据不可用"

    tech = price_data['technical_data']
    trend = price_data.get('trend_analysis', {})
    levels = price_data.get('levels_analysis', {})

    # 检查数据有效性
    def safe_float(value, default=0):
        return float(value) if value and pd.notna(value) else default

    analysis_text = f"""
    【技术指标分析】
    📈 移动平均线:
    - 5周期: {safe_float(tech['sma_5']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_5'])) / safe_float(tech['sma_5']) * 100:+.2f}%
    - 20周期: {safe_float(tech['sma_20']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_20'])) / safe_float(tech['sma_20']) * 100:+.2f}%
    - 50周期: {safe_float(tech['sma_50']):.2f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_50'])) / safe_float(tech['sma_50']) * 100:+.2f}%

    🎯 趋势分析:
    - 短期趋势: {trend.get('short_term', 'N/A')}
    - 中期趋势: {trend.get('medium_term', 'N/A')}
    - 整体趋势: {trend.get('overall', 'N/A')}
    - MACD方向: {trend.get('macd', 'N/A')}

    📊 动量指标:
    - RSI: {safe_float(tech['rsi']):.2f} ({'超买' if safe_float(tech['rsi']) > 70 else '超卖' if safe_float(tech['rsi']) < 30 else '中性'})
    - MACD: {safe_float(tech['macd']):.4f}
    - 信号线: {safe_float(tech['macd_signal']):.4f}

    🎚️ 布林带位置: {safe_float(tech['bb_position']):.2%} ({'上部' if safe_float(tech['bb_position']) > 0.7 else '下部' if safe_float(tech['bb_position']) < 0.3 else '中部'})

    💰 关键水平:
    - 静态阻力: {safe_float(levels.get('static_resistance', 0)):.2f}
    - 静态支撑: {safe_float(levels.get('static_support', 0)):.2f}
    """
    return analysis_text


def get_current_position():
    """获取当前持仓情况 - OKX版本"""
    try:
        positions = exchange.fetch_positions([TRADE_CONFIG['symbol']])

        for pos in positions:
            if pos['symbol'] == TRADE_CONFIG['symbol']:
                contracts = float(pos['contracts']) if pos['contracts'] else 0

                if contracts > 0:
                    return {
                        'side': pos['side'],  # 'long' or 'short'
                        'size': contracts,
                        'entry_price': float(pos['entryPrice']) if pos['entryPrice'] else 0,
                        'unrealized_pnl': float(pos['unrealizedPnl']) if pos['unrealizedPnl'] else 0,
                        'leverage': float(pos['leverage']) if pos['leverage'] else TRADE_CONFIG['leverage'],
                        'symbol': pos['symbol']
                    }

        return None

    except Exception as e:
        print(f"获取持仓失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def safe_json_parse(json_str):
    """安全解析JSON，处理格式不规范的情况"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        try:
            # 修复常见的JSON格式问题
            json_str = json_str.replace("'", '"')
            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON解析失败，原始内容: {json_str}")
            print(f"错误详情: {e}")
            return None


def create_fallback_signal(price_data):
    """创建备用交易信号"""
    return {
        "signal": "HOLD",
        "reason": "因技术分析暂时不可用，采取保守策略",
        "stop_loss": price_data['price'] * 0.98,  # -2%
        "take_profit": price_data['price'] * 1.02,  # +2%
        "confidence": "LOW",
        "is_fallback": True
    }


def identify_market_state(price_data, tech_data):
    """量化识别市场状态"""
    try:
        df = price_data['full_data']

        # 计算ATR (波动率) - 使用14周期
        high_low = df['high'] - df['low']
        atr = high_low.rolling(14).mean()
        atr_pct = (atr.iloc[-1] / price_data['price']) * 100

        # 获取均线数据
        sma_5 = tech_data.get('sma_5', 0)
        sma_20 = tech_data.get('sma_20', 0)
        sma_50 = tech_data.get('sma_50', 0)

        # 均线排列判断趋势强度
        if sma_5 > sma_20 > sma_50:
            trend_strength = "强上涨"
            confidence = 0.9
        elif sma_5 < sma_20 < sma_50:
            trend_strength = "强下跌"
            confidence = 0.9
        elif abs(sma_5 - sma_20) / sma_20 < 0.005:  # 0.5%以内
            trend_strength = "震荡"
            confidence = 0.7
        else:
            trend_strength = "弱趋势"
            confidence = 0.5

        # 综合判断市场状态
        if atr_pct > 3:  # 高波动
            state = "高波动" + trend_strength
        elif atr_pct < 1:  # 低波动
            state = "低波动震荡"
        else:
            state = trend_strength

        return {
            'state': state,
            'confidence': confidence,
            'atr_pct': atr_pct,
            'trend_strength': trend_strength
        }
    except Exception as e:
        print(f"市场状态识别失败: {e}")
        return {
            'state': '未知',
            'confidence': 0.5,
            'atr_pct': 2.0,
            'trend_strength': '未知'
        }


def calculate_dynamic_tp_sl(signal, current_price, market_state, position=None):
    """基于市场状态动态计算止盈止损"""

    atr_pct = market_state.get('atr_pct', 2.0)  # 波动率

    # 🆕 超敏感止损设置 - 及时止损保护利润
    atr_pct = market_state.get('atr_pct', 2.0)
    
    # 🆕 更敏感的止损设置（针对BTC小幅波动优化）
    if atr_pct > 2.5:  # 高波动
        base_sl_pct = 0.003  # 超紧止损 0.3%
        base_tp_pct = 0.08   # 保持8%止盈
    elif atr_pct < 1.0:  # 极低波动
        base_sl_pct = 0.0015  # 极紧止损 0.15%
        base_tp_pct = 0.05   # 保持5%止盈
    else:  # 正常波动
        base_sl_pct = 0.002  # 紧止损 0.2%
        base_tp_pct = 0.065  # 保持6.5%止盈
    
    # 持仓盈亏动态调整
    if position and position.get('unrealized_pnl', 0) > 0:
        profit_pct = position['unrealized_pnl'] / (position['entry_price'] * position['size'] * 0.01)
        if profit_pct > 0.03:  # 盈利3%以上，放宽止盈
            base_tp_pct *= 1.2  # 止盈放大20%
        elif profit_pct > 0.05:  # 盈利5%以上，继续放宽
            base_tp_pct *= 1.5  # 止盈放大50%
    
    # 趋势强度调整
    if market_state['trend_strength'] == '强上涨':
        base_tp_pct *= 1.3  # 强趋势放大止盈
    elif market_state['trend_strength'] == '强下跌':
        base_sl_pct *= 0.8  # 强下跌趋势收紧止损

    # 根据信号方向计算
    if signal == 'BUY':
        stop_loss = current_price * (1 - base_sl_pct)
        take_profit = current_price * (1 + base_tp_pct)
    elif signal == 'SELL':
        stop_loss = current_price * (1 + base_sl_pct)
        take_profit = current_price * (1 - base_tp_pct)
    else:  # HOLD
        stop_loss = current_price * 0.98
        take_profit = current_price * 1.02

    # 🆕 超早移动止损 - 保护微利润
    if position and position.get('unrealized_pnl', 0) > 0:
        entry_price = position.get('entry_price', current_price)
        position_size = position.get('size', 0)

        if entry_price > 0 and position_size > 0:
            profit_pct = position['unrealized_pnl'] / (entry_price * position_size * 0.01)

            # 🆕 微盈利即保护 - 避免利润回吐
            if profit_pct > 0.008:  # 盈利>0.8%即移动止损
                # 移动止损到保本+0.3%
                if position['side'] == 'long':
                    stop_loss = max(stop_loss, entry_price * 1.003)
                    print(f"🛡️ 微盈利{profit_pct:.2%}，超早移动止损: {stop_loss:.2f}")
            elif profit_pct > 0.02:  # 盈利>2%进一步保护
                if position['side'] == 'long':
                    stop_loss = max(stop_loss, entry_price * 1.008)
                    print(f"🛡️ 盈利{profit_pct:.1%}，加强保护: {stop_loss:.2f}")

    return {
        'stop_loss': round(stop_loss, 2),
        'take_profit': round(take_profit, 2),
        'sl_pct': base_sl_pct,
        'tp_pct': base_tp_pct
    }


def validate_ai_signal(ai_signal, price_data, tech_data):
    """量化验证AI信号，防止明显错误和快速交易"""

    signal = ai_signal.get('signal', 'HOLD')
    tech = tech_data
    current_price = price_data['price']
    kline_data = price_data.get('kline_data', [])

    print(f"\n🔍 【AI信号验证开始】")
    print(f"   AI原始信号: {signal} (信心: {ai_signal.get('confidence', 'N/A')})")
    print(f"   当前价格: ${current_price:.2f}")

    # 🆕 新增：K线状态验证
    def get_current_kline_state():
        """获取当前K线状态"""
        if len(kline_data) < 2:
            return {'is_red': False, 'is_green': False, 'change': 0}
        
        latest_kline = kline_data[-1]
        change = ((latest_kline['close'] - latest_kline['open']) / latest_kline['open']) * 100
        
        return {
            'is_red': latest_kline['close'] < latest_kline['open'],  # 阴线
            'is_green': latest_kline['close'] > latest_kline['open'],  # 阳线
            'change': change,
            'open': latest_kline['open'],
            'close': latest_kline['close']
        }

    # 🆕 新增：交易冷却期检查
    def check_trade_cooldown():
        """检查是否有足够的交易冷却期"""
        if len(signal_history) < 2:
            print(f"   ✅ 首次交易或历史不足，允许交易")
            return True
        
        # 检查最近两次交易的时间间隔
        last_trade = signal_history[-1]
        if 'timestamp' in last_trade:
            try:
                last_time = datetime.strptime(last_trade['timestamp'], '%Y-%m-%d %H:%M:%S')
                current_time = datetime.now()
                time_diff = (current_time - last_time).total_seconds() / 60  # 分钟
                
                print(f"   📊 上次交易时间: {last_trade['timestamp']}")
                print(f"   ⏰ 距离上次交易: {time_diff:.1f}分钟")
                
                # 最少冷却5分钟
                if time_diff < 5:
                    print(f"   🚫 交易冷却期不足：{time_diff:.1f}分钟 < 5分钟，跳过交易")
                    return False
                else:
                    print(f"   ✅ 冷却期充足：{time_diff:.1f}分钟 ≥ 5分钟")
            except Exception as e:
                print(f"   ⚠️ 时间解析异常: {e}")
        return True

    # 🆕 新增：K线验证逻辑
    kline_state = get_current_kline_state()
    print(f"   📈 K线状态: {'阴线' if kline_state['is_red'] else '阳线' if kline_state['is_green'] else '十字星'}")
    print(f"   📊 K线涨跌: {kline_state['change']:+.2f}%")
    
    # 规则0: 交易冷却期检查
    if not check_trade_cooldown():
        ai_signal['signal'] = 'HOLD'
        ai_signal['reason'] = "交易冷却期不足，避免频繁交易"
        print(f"   ❌ 验证结果: 跳过交易 (冷却期不足)")
        return ai_signal

    # 规则1: K线状态验证 - 防止在阳线高位买入，RSI极端时放宽限制
    if signal == 'BUY':
        print(f"   🔍 检查BUY信号合理性...")
        
        # 获取RSI用于智能调整
        rsi = tech.get('rsi', 50)
        
        # 极端超卖时放宽阳线限制（RSI < 25）
        if kline_state['is_green'] and kline_state['change'] > 0.5:
            if rsi < 25:  # 极端超卖，允许小幅反弹买入
                print(f"   ✅ 超卖反弹: RSI{rsi:.1f}超卖，阳线{kline_state['change']:.2f}%视为反弹信号")
            else:
                print(f"   ⚠️ 拒绝原因: 阳线上涨{kline_state['change']:.2f}%，追高风险高")
                ai_signal['confidence'] = 'LOW'
                ai_signal['reason'] += f" [阳线上涨{kline_state['change']:.2f}%]"
        
        # 新增：阴线买入验证
        elif kline_state['is_red'] or kline_state['change'] < -0.2:
            print(f"   ✅ 通过验证: 阴线或下跌{kline_state['change']:.2f}%，适合抄底")
        else:
            # 小幅阳线但在低位，可以谨慎买入
            if rsi < 30:
                print(f"   ✅ 低位反弹: RSI{rsi:.1f}低位，小幅阳线{kline_state['change']:.2f}%可接受")
            else:
                print(f"   ⚠️ 谨慎信号: 当前状态{kline_state['change']:+.2f}%，降低信心")
                ai_signal['confidence'] = 'LOW'

    if signal == 'SELL':
        print(f"   🔍 检查SELL信号合理性...")
        
        # 获取RSI用于智能调整
        rsi = tech.get('rsi', 50)
        
        # 极端超买时放宽阴线限制（RSI > 75）
        if kline_state['is_red'] and kline_state['change'] < -0.5:
            if rsi > 75:  # 极端超买，允许小幅回调卖出
                print(f"   ✅ 超买回调: RSI{rsi:.1f}超买，阴线{kline_state['change']:.2f}%视为回调信号")
            else:
                print(f"   ⚠️ 拒绝原因: 阴线下跌{kline_state['change']:.2f}%，杀跌风险高")
                ai_signal['confidence'] = 'LOW'
                ai_signal['reason'] += f" [阴线下跌{kline_state['change']:.2f}%]"
        else:
            # 小幅阴线但在高位，可以谨慎卖出
            if rsi > 70:
                print(f"   ✅ 高位回调: RSI{rsi:.1f}高位，小幅阴线{kline_state['change']:.2f}%可接受")
            else:
                print(f"   ✅ 通过验证: 当前状态适合卖出")

    # 规则2: RSI极端值检查
    rsi = tech.get('rsi', 50)
    print(f"   📊 RSI指标: {rsi:.1f}")
    if rsi > 80 and signal == 'BUY':
        print(f"   ⚠️ RSI超买({rsi:.1f}>80)，BUY信号降级")
        ai_signal['confidence'] = 'LOW'
        ai_signal['reason'] += " [RSI超买警告]"

    if rsi < 20 and signal == 'SELL':
        print(f"   ⚠️ RSI超卖({rsi:.1f}<20)，SELL信号降级")
        ai_signal['confidence'] = 'LOW'
        ai_signal['reason'] += " [RSI超卖警告]"
    elif 20 <= rsi <= 80:
        print(f"   ✅ RSI正常区间({rsi:.1f})")

    # 规则4: 止盈止损合理性检查
    current_price = price_data['price']
    stop_loss = ai_signal.get('stop_loss', 0)
    take_profit = ai_signal.get('take_profit', 0)

    print(f"   📊 止盈止损检查:")
    print(f"      建议止损: ${stop_loss:.2f}")
    print(f"      建议止盈: ${take_profit:.2f}")

    if signal == 'BUY':
        # 止损应该低于当前价
        if stop_loss >= current_price:
            old_sl = stop_loss
            ai_signal['stop_loss'] = current_price * 0.98
            print(f"      ⚠️ 修正止损: ${old_sl:.2f} → ${ai_signal['stop_loss']:.2f}")
        # 止盈应该高于当前价
        if take_profit <= current_price:
            old_tp = take_profit
            ai_signal['take_profit'] = current_price * 1.03
            print(f"      ⚠️ 修正止盈: ${old_tp:.2f} → ${ai_signal['take_profit']:.2f}")

    elif signal == 'SELL':
        # 止损应该高于当前价
        if stop_loss <= current_price:
            old_sl = stop_loss
            ai_signal['stop_loss'] = current_price * 1.02
            print(f"      ⚠️ 修正止损: ${old_sl:.2f} → ${ai_signal['stop_loss']:.2f}")
        # 止盈应该低于当前价
        if take_profit >= current_price:
            old_tp = take_profit
            ai_signal['take_profit'] = current_price * 0.97
            print(f"      ⚠️ 修正止盈: ${old_tp:.2f} → ${ai_signal['take_profit']:.2f}")

    # 最终决策总结
    final_signal = ai_signal.get('signal', 'HOLD')
    final_confidence = ai_signal.get('confidence', 'N/A')
    print(f"   🎯 最终决策: {final_signal} (信心: {final_confidence})")
    if final_signal == 'HOLD':
        reason = ai_signal.get('reason', '系统保护')
        print(f"   📋 跳过原因: {reason}")
    else:
        print(f"   📋 执行理由: {ai_signal.get('reason', '通过验证')}")
    print(f"   🔚 【验证完成】\n")

    return ai_signal


def analyze_with_deepseek(price_data):
    """使用DeepSeek分析市场并生成交易信号（优化版）"""

    # 生成技术分析文本
    # technical_analysis = generate_technical_analysis_text(price_data)

    # 构建K线数据文本
    kline_text = f"【最近5根{TRADE_CONFIG['timeframe']}K线数据】\n"
    for i, kline in enumerate(price_data['kline_data'][-5:]):
        trend = "阳线" if kline['close'] > kline['open'] else "阴线"
        change = ((kline['close'] - kline['open']) / kline['open']) * 100
        kline_text += f"K线{i + 1}: {trend} 开盘:{kline['open']:.2f} 收盘:{kline['close']:.2f} 涨跌:{change:+.2f}%\n"

    # 添加上次交易信号
    last_signal_info = ""
    if signal_history:
        last_signal = signal_history[-1]
        last_signal_info = f"\n【上次信号】{last_signal.get('signal', 'N/A')} (信心: {last_signal.get('confidence', 'N/A')})"

    # 获取情绪数据
    sentiment_data = get_sentiment_indicators()
    if sentiment_data:
        sign = '+' if sentiment_data['net_sentiment'] >= 0 else ''
        sentiment_text = f"【市场情绪】乐观{sentiment_data['positive_ratio']:.1%} 悲观{sentiment_data['negative_ratio']:.1%} 净值{sign}{sentiment_data['net_sentiment']:.3f}"
    else:
        sentiment_text = "【市场情绪】数据暂不可用"

    # 添加当前持仓信息
    current_pos = get_current_position()
    position_text = "无持仓" if not current_pos else f"{current_pos['side']}仓, 数量: {current_pos['size']}, 盈亏: {current_pos['unrealized_pnl']:.2f}USDT"

    # 识别市场状态
    tech_data = price_data.get('technical_data', {})
    market_state = identify_market_state(price_data, tech_data)

    # 动态计算建议的止盈止损
    suggested_tp_sl = calculate_dynamic_tp_sl('BUY', price_data['price'], market_state, current_pos)
    tp_sl_hint = f"建议止损±{suggested_tp_sl['sl_pct']*100:.1f}%, 止盈±{suggested_tp_sl['tp_pct']*100:.1f}%"

    # 🎯 优化的低价买入权重判断
    # 计算相对价格位置（0-100，越低越接近底部）
    price_position = calculate_price_position(price_data)
    
    # 计算买入权重增强
    buy_weight_multiplier = 1.0
    if price_position < 30:  # 价格处于相对低位
        buy_weight_multiplier *= 1.5
    if market_state['atr_pct'] < 1.5:  # 低波动市场
        buy_weight_multiplier *= 1.3
    if price_data['technical_data'].get('rsi', 50) < 35:  # 超卖区域
        buy_weight_multiplier *= 1.4
    
    # 优化的Prompt - 增强低价买入逻辑
    prompt = f"""
你是专业的BTC波段交易大师，专注精准抄底。{TRADE_CONFIG['timeframe']}周期分析：

【🎯 核心价格分析】
当前价格: ${price_data['price']:,.2f}
相对位置: {price_position:.1f}% (0%=底部,100%=顶部)
价格变化: {price_data['price_change']:+.2f}%
波动率: {market_state['atr_pct']:.2f}%

【📊 技术状态】
RSI: {price_data['technical_data'].get('rsi', 50):.1f} ({'超卖' if price_data['technical_data'].get('rsi', 50) < 35 else '正常' if price_data['technical_data'].get('rsi', 50) < 70 else '超买'})
MACD: {price_data['trend_analysis'].get('macd', 'N/A')}
均线状态: {price_data['trend_analysis'].get('overall', 'N/A')}

【💰 博弈策略】
价格低位权重: {buy_weight_multiplier:.1f}x
超卖信号: {'✅' if price_data['technical_data'].get('rsi', 50) < 35 else '❌'}
低波动机会: {'✅' if market_state['atr_pct'] < 1.5 else '❌'}

【🎯 震荡市专用策略】
震荡市识别条件：价格波动<4%，ATR<1.5%，趋势强度<0.5%

🔄 区间交易策略：
1. 靠近支撑位（<25%）+ 反转信号 → HIGH信心BUY
2. 靠近阻力位（>75%）+ 反转信号 → HIGH信心SELL
3. 区间中点（40-60%）+ 明确信号 → MEDIUM信心交易
4. 区间突破立即止损（0.3%）

⚠️ 震荡市风控：
- 每日最多2次交易
- 盈利0.8%立即止盈
- 亏损0.5%立即止损
- 仓位降低至60%
- 最长持仓2小时

🚫 禁止交易：
- 波动率<1.5%（无行情）
- 无明确区间形成
- 区间太窄（<0.5%）或太宽（>4%）

【⚠️ 风险控制】
{tp_sl_hint}
仓位管理: 低位买入可加大仓位，但单次不超过30%
止损设置: 严格2%止损，确保小亏大盈

【持仓状态】
{position_text}
{last_signal_info}

【市场情绪】
{sentiment_text}

【输出格式】
严格JSON格式：
{{
    "signal": "BUY|SELL|HOLD",
    "reason": "买入理由(如:超卖反弹/低位抄底/震荡底部)",
    "stop_loss": 具体价格数字,
    "take_profit": 具体价格数字,
    "confidence": "HIGH|MEDIUM|LOW"
}}
"""

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system",
                 "content": f"您是专业交易员，专注{TRADE_CONFIG['timeframe']}周期趋势分析。严格输出JSON格式，不要添加任何解释文字。"},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=0.1
        )

        # 安全解析JSON
        result = response.choices[0].message.content
        print(f"🤖 AI原始回复: {result[:200]}...")

        # 提取JSON部分
        start_idx = result.find('{')
        end_idx = result.rfind('}') + 1

        if start_idx != -1 and end_idx != 0:
            json_str = result[start_idx:end_idx]
            signal_data = safe_json_parse(json_str)

            if signal_data is None:
                signal_data = create_fallback_signal(price_data)
        else:
            signal_data = create_fallback_signal(price_data)

        # 验证必需字段
        required_fields = ['signal', 'reason', 'stop_loss', 'take_profit', 'confidence']
        if not all(field in signal_data for field in required_fields):
            signal_data = create_fallback_signal(price_data)

        # 🆕 量化验证AI信号
        print(f"📊 AI原始信号: {signal_data['signal']} (信心: {signal_data['confidence']})")
        signal_data = validate_ai_signal(signal_data, price_data, tech_data)
        print(f"✅ 验证后信号: {signal_data['signal']} (信心: {signal_data['confidence']})")

        # 🆕 使用动态止盈止损（如果AI的不合理）
        dynamic_tp_sl = calculate_dynamic_tp_sl(signal_data['signal'], price_data['price'], market_state, current_pos)

        # 检查AI的止盈止损是否合理，不合理则使用动态计算的
        if signal_data['signal'] != 'HOLD':
            ai_sl = signal_data.get('stop_loss', 0)
            ai_tp = signal_data.get('take_profit', 0)
            current_price = price_data['price']

            # 验证止损止盈的合理性
            sl_valid = False
            tp_valid = False

            if signal_data['signal'] == 'BUY':
                sl_valid = ai_sl < current_price and ai_sl > current_price * 0.95  # 止损在当前价下方且不超过5%
                tp_valid = ai_tp > current_price and ai_tp < current_price * 1.10  # 止盈在当前价上方且不超过10%
            elif signal_data['signal'] == 'SELL':
                sl_valid = ai_sl > current_price and ai_sl < current_price * 1.05  # 止损在当前价上方且不超过5%
                tp_valid = ai_tp < current_price and ai_tp > current_price * 0.90  # 止盈在当前价下方且不超过10%

            if not sl_valid or not tp_valid:
                print(f"⚠️ AI止盈止损不合理，使用动态计算: SL={dynamic_tp_sl['stop_loss']}, TP={dynamic_tp_sl['take_profit']}")
                signal_data['stop_loss'] = dynamic_tp_sl['stop_loss']
                signal_data['take_profit'] = dynamic_tp_sl['take_profit']

        # 保存信号到历史记录
        signal_data['timestamp'] = price_data['timestamp']
        signal_history.append(signal_data)
        if len(signal_history) > 30:
            signal_history.pop(0)

        # 信号统计
        signal_count = len([s for s in signal_history if s.get('signal') == signal_data['signal']])
        total_signals = len(signal_history)
        print(f"信号统计: {signal_data['signal']} (最近{total_signals}次中出现{signal_count}次)")

        # 信号连续性检查
        if len(signal_history) >= 3:
            last_three = [s['signal'] for s in signal_history[-3:]]
            if len(set(last_three)) == 1:
                print(f"⚠️ 注意：连续3次{signal_data['signal']}信号")

        return signal_data

    except Exception as e:
        print(f"DeepSeek分析失败: {e}")
        return create_fallback_signal(price_data)


def get_active_tp_sl_orders():
    """
    查询当前活跃的止盈止损订单

    返回:
        dict: 包含止盈止损订单信息的字典
    """
    try:
        # 转换交易对格式：BTC/USDT:USDT -> BTC-USDT-SWAP
        inst_id = TRADE_CONFIG['symbol'].replace('/USDT:USDT', '-USDT-SWAP').replace('/', '-')

        # 使用OKX专用的算法订单API查询
        response = exchange.private_get_trade_orders_algo_pending({
            'instType': 'SWAP',
            'instId': inst_id,
            'ordType': 'conditional'  # 查询条件单
        })

        active_orders = {
            'stop_loss_orders': [],
            'take_profit_orders': []
        }

        if response.get('code') == '0' and response.get('data'):
            for order in response['data']:
                ord_type = order.get('ordType')

                # 检查是否是止盈止损订单
                if ord_type == 'conditional':
                    # 判断是止损还是止盈
                    if order.get('slTriggerPx'):
                        active_orders['stop_loss_orders'].append({
                            'order_id': order['algoId'],
                            'trigger_price': float(order['slTriggerPx']),
                            'size': float(order['sz']),
                            'side': order['side'],
                            'state': order['state']
                        })
                    elif order.get('tpTriggerPx'):
                        active_orders['take_profit_orders'].append({
                            'order_id': order['algoId'],
                            'trigger_price': float(order['tpTriggerPx']),
                            'size': float(order['sz']),
                            'side': order['side'],
                            'state': order['state']
                        })

        return active_orders

    except Exception as e:
        print(f"⚠️ 查询止盈止损订单失败: {e}")
        return {'stop_loss_orders': [], 'take_profit_orders': []}


def cancel_existing_tp_sl_orders():
    """取消现有的止盈止损算法订单"""
    global active_tp_sl_orders

    try:
        # 转换交易对格式：例如 "BTC/USDT:USDT" -> "BTC-USDT-SWAP"
        inst_id = TRADE_CONFIG['symbol'].replace('/USDT:USDT', '-USDT-SWAP').replace('/', '-')

        # 查询活跃算法订单（止盈止损）
        response = exchange.private_get_trade_orders_algo_pending({
            'instType': 'SWAP',
            'instId': inst_id,
            'ordType': 'conditional'
        })

        if not response or response.get('code') != '0' or not response.get('data'):
            print(f"ℹ️ 无可取消算法订单或查询异常: {response}")
            return

        cancel_params = []
        for order in response['data']:
            ord_type = order.get('ordType')
            if ord_type in ['conditional', 'oco']:
                algo_id = order.get('algoId')
                if algo_id:
                    cancel_params.append({
                        "instId": inst_id,
                        "algoId": str(algo_id)
                    })
                else:
                    print(f"⚠️ 发现算法订单但缺少 algoId: {order}")

        if cancel_params:
            print("➡️ 准备取消算法订单: ", json.dumps(cancel_params, ensure_ascii=False))
            cancel_response = exchange.request(
                path="trade/cancel-algos",
                api="private",
                method="POST",
                params=cancel_params
            )
            print("⬅️ 返回: ", cancel_response)

            if cancel_response.get('code') == '0':
                print(f"✅ 成功发送取消请求，共 {len(cancel_params)} 个")
            else:
                print(f"⚠️ 取消算法订单失败: {cancel_response}")
        else:
            print("ℹ️ 没有符合条件的止盈止损算法订单需要取消")

        # 重置全局状态
        active_tp_sl_orders['take_profit_order_id'] = None
        active_tp_sl_orders['stop_loss_order_id'] = None

    except Exception as e:
        print(f"⚠️ 取消止盈止损订单时出错: {e}")


def check_existing_tp_sl_orders(position_side, stop_loss_price, take_profit_price, position_size):
    """
    检查是否已存在相同的止盈止损订单，避免重复创建

    返回: True=已存在相同订单，False=需要创建新订单
    """
    try:
        inst_id = TRADE_CONFIG['symbol'].replace('/USDT:USDT', '-USDT-SWAP').replace('/', '-')

        # 查询当前活跃的算法订单
        response = exchange.private_get_trade_orders_algo_pending({
            'instType': 'SWAP',
            'instId': inst_id,
            'ordType': 'conditional'
        })

        if response.get('code') == '0' and response.get('data'):
            orders = response['data']

            # 检查是否有匹配的订单
            has_sl = False
            has_tp = False

            for order in orders:
                # 检查订单方向和数量是否匹配
                order_side = order.get('side')
                order_sz = float(order.get('sz', 0))

                # 平仓方向应该与持仓相反
                expected_side = 'sell' if position_side == 'long' else 'buy'

                if order_side == expected_side and abs(order_sz - position_size) < 0.01:
                    # 检查止损订单
                    if order.get('slTriggerPx'):
                        sl_trigger = float(order['slTriggerPx'])
                        if abs(sl_trigger - stop_loss_price) < 1:  # 价格差异小于1美元
                            has_sl = True

                    # 检查止盈订单
                    if order.get('tpTriggerPx'):
                        tp_trigger = float(order['tpTriggerPx'])
                        if abs(tp_trigger - take_profit_price) < 1:  # 价格差异小于1美元
                            has_tp = True

            # 如果止损和止盈订单都已存在，返回True
            if has_sl and has_tp:
                print(f"ℹ️ 止盈止损订单已存在，无需重复创建")
                return True

        return False

    except Exception as e:
        print(f"⚠️ 检查订单失败: {e}")
        return False



def set_stop_loss_take_profit(position_side, stop_loss_price, take_profit_price, position_size, force_update=False, auto_fix=True, tp_pct=0.05, sl_pct=0.02):
    """
    设置止盈止损订单 - 增强版（自动 TP/SL 百分比支持）
    参数:
        position_side: 'long' 或 'short'
        stop_loss_price: 如果为 None 则根据 entry_price 与 sl_pct 自动计算
        take_profit_price: 如果为 None 则根据 entry_price 与 tp_pct 自动计算
        position_size: 持仓数量 (正数)
        force_update: 是否强制更新（默认False，会检查是否已存在相同订单）
        auto_fix: 若价格方向不符合规则，是否自动修正（默认True）
        tp_pct: 止盈百分比 (默认 0.005 -> 0.5%)
        sl_pct: 止损百分比 (默认 0.025 -> 2.5%)
    返回:
        True/False
    说明:
        - 若你传入 stop_loss_price/take_profit_price 为具体数值，则以该值为准（仍做合法性检查，可 auto_fix）。
        - 若传入 None，则会尝试从上下文/全局或传入的 TRADE_CONFIG 中获取 entry_price/avg_entry_price 进行按百分比计算。
    """
    global active_tp_sl_orders

    try:
        inst_id = TRADE_CONFIG['symbol'].replace('/USDT:USDT', '-USDT-SWAP').replace('/', '-')

        # 如果不是强制更新，先检查是否已存在相同订单
        if not force_update:
            if check_existing_tp_sl_orders(position_side, stop_loss_price, take_profit_price, position_size):
                return True

        # 取消现有的止盈止损订单（如果有）
        cancel_existing_tp_sl_orders()

        # 先尝试获取 entry_price（有时脚本会把 entry_price 存入 position 或 TRADE_CONFIG）
        entry_price = None
        # 尝试从 position/global/TRADE_CONFIG 获取
        try:
            # 如果外层有 position 对象，可传入；这里只是兜底检查
            if 'position' in globals() and position is not None:
                entry_price = float(position.get('avgEntryPrice') or position.get('entry_price') or 0) if isinstance(position, dict) else None
        except Exception:
            entry_price = None

        # 如果没有 entry_price，从交易所获取最新成交价作为近似 entry（fallback）
        if entry_price is None:
            try:
                ticker = exchange.fetch_ticker(TRADE_CONFIG['symbol'])
                entry_price = float(ticker.get('last') or ticker.get('close') or 0)
            except Exception:
                try:
                    t = exchange.public_get_market_ticker({'instId': inst_id})
                    entry_price = float(t['data'][0]['last'])
                except Exception:
                    entry_price = None

        # 打印基本信息
        print(f"📊 [TP/SL] inst_id={inst_id} position_side={position_side} position_size={position_size}")
        print(f"    entry_price (or fallback last) = {entry_price}")
        print(f"    requested stop_loss_price = {stop_loss_price}")
        print(f"    requested take_profit_price = {take_profit_price}")
        print(f"    default tp_pct = {tp_pct*100:.3f}%, sl_pct = {sl_pct*100:.3f}%")

        # 如果用户没有传 stop_loss_price / take_profit_price，则根据 entry_price 计算
        if entry_price is not None:
            if stop_loss_price is None:
                if position_side == 'long':
                    stop_loss_price = round(entry_price * (1 - sl_pct), 8)
                else:
                    stop_loss_price = round(entry_price * (1 + sl_pct), 8)
                print(f"    auto-calculated stop_loss_price = {stop_loss_price}")
            if take_profit_price is None:
                if position_side == 'long':
                    take_profit_price = round(entry_price * (1 + tp_pct), 8)
                else:
                    take_profit_price = round(entry_price * (1 - tp_pct), 8)
                print(f"    auto-calculated take_profit_price = {take_profit_price}")
        else:
            # 如果没有 entry_price 且用户也没传价格，拒绝下单
            if stop_loss_price is None or take_profit_price is None:
                print("❌ 无法获取 entry_price 且未传入 stop_loss/take_profit，拒绝下单")
                return False

        # 再次获取最新市价（用于合法性校验）
        last_price = None
        try:
            ticker = exchange.fetch_ticker(TRADE_CONFIG['symbol'])
            last_price = float(ticker.get('last') or ticker.get('close') or 0)
        except Exception:
            try:
                t = exchange.public_get_market_ticker({'instId': inst_id})
                last_price = float(t['data'][0]['last'])
            except Exception:
                last_price = None

        print(f"    last_price = {last_price}")

        # 校验并基于持仓方向调整（long: SL < last < TP, short: TP < last < SL）
        adjusted_sl = stop_loss_price
        adjusted_tp = take_profit_price
        eps = 0.001  # 0.1% nudge

        if last_price is not None:
            if position_side == 'long':
                # SL must be < last_price
                if float(adjusted_sl) >= last_price:
                    if auto_fix:
                        adjusted_sl = round(last_price * (1 - eps), 8)
                        print(f"⚠️ long: SL {stop_loss_price} >= last {last_price}, auto-fix -> {adjusted_sl}")
                    else:
                        print(f"❌ long: SL {stop_loss_price} invalid (>= last). Refuse.")
                        adjusted_sl = None
                # TP must be > last_price
                if float(adjusted_tp) <= last_price:
                    if auto_fix:
                        adjusted_tp = round(last_price * (1 + eps), 8)
                        print(f"⚠️ long: TP {take_profit_price} <= last {last_price}, auto-fix -> {adjusted_tp}")
                    else:
                        print(f"❌ long: TP {take_profit_price} invalid (<= last). Refuse.")
                        adjusted_tp = None
            else:
                # short: SL > last_price, TP < last_price
                if float(adjusted_sl) <= last_price:
                    if auto_fix:
                        adjusted_sl = round(last_price * (1 + eps), 8)
                        print(f"⚠️ short: SL {stop_loss_price} <= last {last_price}, auto-fix -> {adjusted_sl}")
                    else:
                        print(f"❌ short: SL {stop_loss_price} invalid (<= last). Refuse.")
                        adjusted_sl = None
                if float(adjusted_tp) >= last_price:
                    if auto_fix:
                        adjusted_tp = round(last_price * (1 - eps), 8)
                        print(f"⚠️ short: TP {take_profit_price} >= last {last_price}, auto-fix -> {adjusted_tp}")
                    else:
                        print(f"❌ short: TP {take_profit_price} invalid (>= last). Refuse.")
                        adjusted_tp = None

        # 选择平仓方向
        close_side = 'sell' if position_side == 'long' else 'buy'

        # 确保 tag 合法（无下划线，长度 <= 16）
        tag_value = f"autoTPSL"
        if len(tag_value) > 16:
            tag_value = tag_value[:16]

        # 下单：先 SL 再 TP（两单分开）
        if adjusted_sl:
            sl_params = {
                'instId': inst_id,
                'tdMode': 'cross',
                'side': close_side,
                'ordType': 'conditional',
                'sz': str(position_size),
                'slTriggerPx': str(adjusted_sl),
                'slOrdPx': '-1',
                'reduceOnly': 'true',
                'tag': tag_value
            }
            print("📤 Sending SL params:", json.dumps(sl_params, ensure_ascii=False))
            try:
                sl_resp = exchange.private_post_trade_order_algo(sl_params)
                print("📥 SL response:", json.dumps(sl_resp, ensure_ascii=False))
                if sl_resp.get('code') == '0' and sl_resp.get('data'):
                    algo_id = sl_resp['data'][0].get('algoId')
                    active_tp_sl_orders['stop_loss_order_id'] = algo_id
                    print(f"✅ 止损订单已设置: trigger={adjusted_sl}, algoId={algo_id}")
                else:
                    print(f"❌ 设置止损订单失败: {sl_resp}")
            except Exception as e:
                print(f"❌ 设置止损订单异常: {e}")

        if adjusted_tp:
            tp_params = {
                'instId': inst_id,
                'tdMode': 'cross',
                'side': close_side,
                'ordType': 'conditional',
                'sz': str(position_size),
                'tpTriggerPx': str(adjusted_tp),
                'tpOrdPx': '-1',
                'reduceOnly': 'true',
                'tag': tag_value
            }
            print("📤 Sending TP params:", json.dumps(tp_params, ensure_ascii=False))
            try:
                tp_resp = exchange.private_post_trade_order_algo(tp_params)
                print("📥 TP response:", json.dumps(tp_resp, ensure_ascii=False))
                if tp_resp.get('code') == '0' and tp_resp.get('data'):
                    algo_id = tp_resp['data'][0].get('algoId')
                    active_tp_sl_orders['take_profit_order_id'] = algo_id
                    print(f"✅ 止盈订单已设置: trigger={adjusted_tp}, algoId={algo_id}")
                else:
                    print(f"❌ 设置止盈订单失败: {tp_resp}")
            except Exception as e:
                print(f"❌ 设置止盈订单异常: {e}")

        return True

    except Exception as e:
        print(f"❌ 设置止盈止损失败: {e}")
        return False


def execute_intelligent_trade(signal_data, price_data):
    """执行智能交易 - OKX版本（支持同方向加仓减仓）"""
    global position

    current_position = get_current_position()

    if current_position and signal_data['signal'] != 'HOLD':
        current_side = current_position['side']  # 'long' 或 'short'

        if signal_data['signal'] == 'BUY':
            new_side = 'long'
        elif signal_data['signal'] == 'SELL':
            new_side = 'short'
        else:
            new_side = None

        if new_side and new_side != current_side:
            if signal_data.get('confidence') != 'HIGH':
                print(f"🔒 非高信心反转信号，保持现有{current_side}仓")
                return

            if len(signal_history) >= 2:
                last_signals = [s['signal'] for s in signal_history[-2:]]
                if signal_data['signal'] in last_signals:
                    print(f"🔒 近期已出现{signal_data['signal']}信号，避免频繁反转")
                    return

    # 计算智能仓位
    position_size = calculate_intelligent_position(signal_data, price_data)

    print(f"交易信号: {signal_data['signal']}")
    print(f"信心程度: {signal_data['confidence']}")
    print(f"智能仓位: {position_size:.2f} 张")
    print(f"理由: {signal_data['reason']}")
    print(f"当前持仓: {current_position}")

    # 风险管理
    if signal_data['confidence'] == 'LOW' and not TRADE_CONFIG['test_mode']:
        print("⚠️ 低信心信号，跳过执行")
        return

    if TRADE_CONFIG['test_mode']:
        print("测试模式 - 仅模拟交易")
        return

    try:
        # 执行交易逻辑 - 支持同方向加仓减仓
        if signal_data['signal'] == 'BUY':
            if current_position and current_position['side'] == 'short':
                # 先检查空头持仓是否真实存在且数量正确
                if current_position['size'] > 0:
                    print(f"平空仓 {current_position['size']:.2f} 张并开多仓 {position_size:.2f} 张...")
                    # 取消现有的止盈止损订单
                    cancel_existing_tp_sl_orders()
                    # 平空仓
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'buy',
                        current_position['size'],
                        params={'reduceOnly': True, 'tag': 'c314b0aecb5bBCDE'}
                    )
                    time.sleep(1)
                    # 开多仓
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'buy',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )
                else:
                    print("⚠️ 检测到空头持仓但数量为0，直接开多仓")
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'buy',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )

            elif current_position and current_position['side'] == 'long':
                # 同方向，检查是否需要调整仓位
                size_diff = position_size - current_position['size']

                if abs(size_diff) >= 0.01:  # 有可调整的差异
                    if size_diff > 0:
                        # 加仓
                        add_size = round(size_diff, 2)
                        print(
                            f"多仓加仓 {add_size:.2f} 张 (当前:{current_position['size']:.2f} → 目标:{position_size:.2f})")
                        exchange.create_market_order(
                            TRADE_CONFIG['symbol'],
                            'buy',
                            add_size,
                            params={'tag': 'c314b0aecb5bBCDE'}
                        )
                    else:
                        # 减仓
                        reduce_size = round(abs(size_diff), 2)
                        print(
                            f"多仓减仓 {reduce_size:.2f} 张 (当前:{current_position['size']:.2f} → 目标:{position_size:.2f})")
                        exchange.create_market_order(
                            TRADE_CONFIG['symbol'],
                            'sell',
                            reduce_size,
                            params={'reduceOnly': True, 'tag': 'c314b0aecb5bBCDE'}
                        )
                else:
                    print(
                        f"已有多头持仓，仓位合适保持现状 (当前:{current_position['size']:.2f}, 目标:{position_size:.2f})")
            else:
                # 无持仓时开多仓
                print(f"开多仓 {position_size:.2f} 张...")
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'buy',
                    position_size,
                    params={'tag': 'c314b0aecb5bBCDE'}
                )

        elif signal_data['signal'] == 'SELL':
            if current_position and current_position['side'] == 'long':
                # 先检查多头持仓是否真实存在且数量正确
                if current_position['size'] > 0:
                    print(f"平多仓 {current_position['size']:.2f} 张并开空仓 {position_size:.2f} 张...")
                    # 取消现有的止盈止损订单
                    cancel_existing_tp_sl_orders()
                    # 平多仓
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'sell',
                        current_position['size'],
                        params={'reduceOnly': True, 'tag': 'c314b0aecb5bBCDE'}
                    )
                    time.sleep(1)
                    # 开空仓
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'sell',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )
                else:
                    print("⚠️ 检测到多头持仓但数量为0，直接开空仓")
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'sell',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )

            elif current_position and current_position['side'] == 'short':
                # 同方向，检查是否需要调整仓位
                size_diff = position_size - current_position['size']

                if abs(size_diff) >= 0.01:  # 有可调整的差异
                    if size_diff > 0:
                        # 加仓
                        add_size = round(size_diff, 2)
                        print(
                            f"空仓加仓 {add_size:.2f} 张 (当前:{current_position['size']:.2f} → 目标:{position_size:.2f})")
                        exchange.create_market_order(
                            TRADE_CONFIG['symbol'],
                            'sell',
                            add_size,
                            params={'tag': 'c314b0aecb5bBCDE'}
                        )
                    else:
                        # 减仓
                        reduce_size = round(abs(size_diff), 2)
                        print(
                            f"空仓减仓 {reduce_size:.2f} 张 (当前:{current_position['size']:.2f} → 目标:{position_size:.2f})")
                        exchange.create_market_order(
                            TRADE_CONFIG['symbol'],
                            'buy',
                            reduce_size,
                            params={'reduceOnly': True, 'tag': 'c314b0aecb5bBCDE'}
                        )
                else:
                    print(
                        f"已有空头持仓，仓位合适保持现状 (当前:{current_position['size']:.2f}, 目标:{position_size:.2f})")
            else:
                # 无持仓时开空仓
                print(f"开空仓 {position_size:.2f} 张...")
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'sell',
                    position_size,
                    params={'tag': 'c314b0aecb5bBCDE'}
                )

        elif signal_data['signal'] == 'HOLD':
            print("建议观望，不执行交易")
            # 🆕 优化：如果有持仓，检查止盈止损订单是否存在，不存在才创建
            if current_position and current_position['size'] > 0:
                stop_loss_price = signal_data.get('stop_loss')
                take_profit_price = signal_data.get('take_profit')

                # 只有当止盈止损价格有效时才处理
                if stop_loss_price and take_profit_price:
                    # 检查是否已存在订单（不强制更新）
                    if not check_existing_tp_sl_orders(
                        current_position['side'],
                        stop_loss_price,
                        take_profit_price,
                        current_position['size']
                    ):
                        print(f"\n📊 创建止盈止损订单:")
                        print(f"   止损价格: {stop_loss_price}")
                        print(f"   止盈价格: {take_profit_price}")

                        set_stop_loss_take_profit(
                            position_side=current_position['side'],
                            stop_loss_price=stop_loss_price,
                            take_profit_price=take_profit_price,
                            position_size=current_position['size'],
                            force_update=False  # 不强制更新
                        )
                    else:
                        print(f"ℹ️ 止盈止损订单已存在，无需更新")
            return

        print("智能交易执行成功")
        time.sleep(2)
        position = get_current_position()
        print(f"更新后持仓: {position}")

        # 🆕 交易后设置止盈止损订单（强制更新）
        if position and position['size'] > 0:
            stop_loss_price = signal_data.get('stop_loss')
            take_profit_price = signal_data.get('take_profit')

            if stop_loss_price or take_profit_price:
                print(f"\n📊 设置止盈止损:")
                print(f"   止损价格: {stop_loss_price}")
                print(f"   止盈价格: {take_profit_price}")

                set_stop_loss_take_profit(
                    position_side=position['side'],
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    position_size=position['size'],
                    force_update=True  # 交易后强制更新订单
                )

        # 保存交易记录
        try:
            # 计算实际盈亏（如果有持仓）
            pnl = 0
            if current_position and position:
                # 如果方向改变或平仓，计算盈亏
                if current_position['side'] != position.get('side'):
                    if current_position['side'] == 'long':
                        pnl = (price_data['price'] - current_position['entry_price']) * current_position['size'] * TRADE_CONFIG.get('contract_size', 0.01)
                    else:
                        pnl = (current_position['entry_price'] - price_data['price']) * current_position['size'] * TRADE_CONFIG.get('contract_size', 0.01)
            
            trade_record = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'signal': signal_data['signal'],
                'price': price_data['price'],
                'amount': position_size,
                'confidence': signal_data['confidence'],
                'reason': signal_data['reason'],
                'pnl': pnl
            }
            save_trade_record(trade_record)
            print("✅ 交易记录已保存")
        except Exception as e:
            print(f"保存交易记录失败: {e}")

    except Exception as e:
        print(f"交易执行失败: {e}")

        # 如果是持仓不存在的错误，尝试直接开新仓
        if "don't have any positions" in str(e):
            print("尝试直接开新仓...")
            try:
                if signal_data['signal'] == 'BUY':
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'buy',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )
                elif signal_data['signal'] == 'SELL':
                    exchange.create_market_order(
                        TRADE_CONFIG['symbol'],
                        'sell',
                        position_size,
                        params={'tag': 'c314b0aecb5bBCDE'}
                    )
                print("直接开仓成功")
            except Exception as e2:
                print(f"直接开仓也失败: {e2}")

        import traceback
        traceback.print_exc()


def analyze_with_deepseek_with_retry(price_data, max_retries=2):
    """带重试的DeepSeek分析"""
    for attempt in range(max_retries):
        try:
            signal_data = analyze_with_deepseek(price_data)
            if signal_data and not signal_data.get('is_fallback', False):
                return signal_data

            print(f"第{attempt + 1}次尝试失败，进行重试...")
            time.sleep(1)

        except Exception as e:
            print(f"第{attempt + 1}次尝试异常: {e}")
            if attempt == max_retries - 1:
                return create_fallback_signal(price_data)
            time.sleep(1)

    return create_fallback_signal(price_data)


def wait_for_next_period():
    now = datetime.now()
    tf = TRADE_CONFIG.get('timeframe', '15m')
    unit = tf[-1]
    value = int(tf[:-1]) if tf[:-1].isdigit() else 15

    if unit == 'm':
        period_minutes = value
    elif unit == 'h':
        period_minutes = value * 60
    elif unit == 'd':
        period_minutes = value * 60 * 24
    else:
        period_minutes = 15

    total_minutes = now.hour * 60 + now.minute
    next_block = ((total_minutes // period_minutes) + 1) * period_minutes
    minutes_to_wait = (next_block - total_minutes) % (24 * 60)
    seconds_to_wait = minutes_to_wait * 60 - now.second

    if minutes_to_wait > 0:
        display_minutes = minutes_to_wait - 1 if now.second > 0 else minutes_to_wait
        display_seconds = 60 - now.second if now.second > 0 else 0
        if display_minutes > 0:
            print(f"🕒 等待 {display_minutes} 分 {display_seconds} 秒到整点...")
        else:
            print(f"🕒 等待 {display_seconds} 秒到整点...")
    else:
        print(f"🕒 等待 {60 - now.second} 秒到整点...")

    return max(seconds_to_wait, 0)


def trading_bot():
    # 等待到整点再执行
    wait_seconds = wait_for_next_period()
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    """主交易机器人函数"""
    print("\n" + "=" * 60)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 获取增强版K线数据
    price_data = get_btc_ohlcv_enhanced()
    if not price_data:
        return

    print(f"BTC当前价格: ${price_data['price']:,.2f}")
    print(f"数据周期: {TRADE_CONFIG['timeframe']}")
    print(f"价格变化: {price_data['price_change']:+.2f}%")

    # 2. 获取账户信息
    try:
        balance = exchange.fetch_balance()
        account_info = {
            'balance': float(balance['USDT'].get('free', 0)),
            'equity': float(balance['USDT'].get('total', 0)),
            'leverage': TRADE_CONFIG['leverage']
        }
    except Exception as e:
        print(f"获取账户信息失败: {e}")
        account_info = None

    # 3. 获取当前持仓
    current_position = get_current_position()
    position_info = None
    if current_position:
        position_info = {
            'side': current_position['side'],
            'size': current_position['size'],
            'entry_price': current_position['entry_price'],
            'unrealized_pnl': current_position['unrealized_pnl']
        }

    # 4. 使用DeepSeek分析（带重试）
    signal_data = analyze_with_deepseek_with_retry(price_data)

    if signal_data.get('is_fallback', False):
        print("⚠️ 使用备用交易信号")

    # 5. 更新系统状态到Web界面
    try:
        update_system_status(
            status='running',
            account_info=account_info,
            btc_info={
                'price': price_data['price'],
                'change': price_data['price_change'],
                'timeframe': TRADE_CONFIG['timeframe'],
                'mode': '全仓-单向'
            },
            position=position_info,
            ai_signal={
                'signal': signal_data['signal'],
                'confidence': signal_data['confidence'],
                'reason': signal_data['reason'],
                'stop_loss': signal_data['stop_loss'],
                'take_profit': signal_data['take_profit']
            },
            tp_sl_orders={
                'stop_loss_order_id': active_tp_sl_orders.get('stop_loss_order_id'),
                'take_profit_order_id': active_tp_sl_orders.get('take_profit_order_id')
            }
        )
        print("✅ 系统状态已更新到Web界面")
    except Exception as e:
        print(f"更新系统状态失败: {e}")

    # 6. 执行智能交易
    execute_intelligent_trade(signal_data, price_data)


def main():
    """主函数"""
    print("BTC/USDT OKX自动交易机器人启动成功！")
    print("融合技术指标策略 + OKX实盘接口")

    if TRADE_CONFIG['test_mode']:
        print("当前为模拟模式，不会真实下单")
    else:
        print("实盘交易模式，请谨慎操作！")

    print(f"交易周期: {TRADE_CONFIG['timeframe']}")
    print("已启用完整技术指标分析和持仓跟踪功能")

    # 设置交易所
    if not setup_exchange():
        print("交易所初始化失败，程序退出")
        return
    
    # 初始化Web界面数据文件
    print("🌐 初始化Web界面数据...")
    try:
        # 确保数据文件存在
        from data_manager import load_trades_history, load_equity_history, save_equity_snapshot
        
        # 预加载确保文件创建
        load_trades_history()
        load_equity_history()
        
        # 获取初始账户信息
        balance = exchange.fetch_balance()
        current_equity = float(balance['USDT'].get('total', 0))
        initial_account = {
            'balance': float(balance['USDT'].get('free', 0)),
            'equity': current_equity,
            'leverage': TRADE_CONFIG['leverage']
        }
        
        # 获取当前BTC价格
        ticker = exchange.fetch_ticker(TRADE_CONFIG['symbol'])
        initial_btc = {
            'price': float(ticker['last']),
            'change': float(ticker['percentage']) if ticker.get('percentage') else 0,
            'timeframe': TRADE_CONFIG['timeframe'],
            'mode': '全仓-单向'
        }
        
        # 获取当前持仓
        current_pos = get_current_position()
        initial_position = None
        if current_pos:
            initial_position = {
                'side': current_pos['side'],
                'size': current_pos['size'],
                'entry_price': current_pos['entry_price'],
                'unrealized_pnl': current_pos['unrealized_pnl']
            }
        
        # 初始化权益快照
        save_equity_snapshot(current_equity)
        
        # 初始化系统状态
        update_system_status(
            status='running',
            account_info=initial_account,
            btc_info=initial_btc,
            position=initial_position,
            ai_signal={
                'signal': 'HOLD',
                'confidence': 'N/A',
                'reason': '系统启动中，等待首次分析...',
                'stop_loss': 0,
                'take_profit': 0
            }
        )
        print("✅ Web界面数据初始化完成")
    except Exception as e:
        print(f"⚠️ Web界面数据初始化失败: {e}")
        # 创建空文件确保后续正常运行
        try:
            from data_manager import save_equity_snapshot
            save_equity_snapshot(100.0)  # 默认初始权益
        except:
            pass
        print("继续运行，将在首次交易时创建数据")

    tf = TRADE_CONFIG.get('timeframe', '15m')
    unit = tf[-1]
    value = tf[:-1] if tf[:-1].isdigit() else '15'
    unit_cn = '分钟' if unit == 'm' else ('小时' if unit == 'h' else ('天' if unit == 'd' else '分钟'))
    print(f"执行频率: 每{value}{unit_cn}整点执行")

    # 循环执行（不使用schedule）
    while True:
        trading_bot()  # 函数内部会自己等待整点

        # 执行完后等待一段时间再检查（避免频繁循环）
        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    main()

