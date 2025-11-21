#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BTC自动交易机器人 - 统一启动程序
适用于宝塔面板等单入口部署场景

智能启动：
1. 交易程序（deepseekok2.py）- 始终启动
2. Web监控界面（streamlit）- 根据配置决定是否启动
"""

import os
import sys
import time
import signal
import subprocess
from multiprocessing import Process
from pathlib import Path

# 读取交易配置，决定是否启动Web界面
try:
    # 临时导入获取配置
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deepseekok2
    WEB_CONFIG = deepseekok2.TRADE_CONFIG.get('web_interface', {})
    WEB_ENABLED = WEB_CONFIG.get('enabled', False)
    WEB_PORT = WEB_CONFIG.get('port', 8501)
except:
    WEB_ENABLED = False
    WEB_PORT = 8501

# 只有在启用Web界面时才设置Streamlit环境变量
if WEB_ENABLED:
    os.environ['STREAMLIT_CONFIG_DIR'] = os.path.join(os.getcwd(), '.streamlit_config')
    os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'
    os.environ['STREAMLIT_SERVER_FILE_WATCHER_TYPE'] = 'none'
    os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'

# 全局进程列表
processes = []

def log(message):
    """统一日志输出"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}", flush=True)

def run_trading_bot():
    """运行交易程序"""
    try:
        log("🤖 启动交易程序...")
        # 导入交易程序主函数
        import deepseekok2
        deepseekok2.main()
    except Exception as e:
        log(f"❌ 交易程序异常: {e}")
        import traceback
        traceback.print_exc()
        # 交易程序异常后等待一段时间再重试
        time.sleep(10)
        log("🔄 重启交易程序...")
        run_trading_bot()

def run_web_interface():
    """运行Web界面"""
    try:
        log("🌐 启动Web监控界面...")
        
        # 设置额外的环境变量
        env = os.environ.copy()
        env['STREAMLIT_SERVER_HEADLESS'] = 'true'
        env['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
        env['STREAMLIT_SERVER_FILE_WATCHER_TYPE'] = 'none'
        
        # 使用subprocess运行streamlit
        streamlit_cmd = [
            sys.executable,
            "-m", "streamlit",
            "run",
            "streamlit_app.py",
            "--server.headless", "true",
            "--server.address", "0.0.0.0",
            "--server.port", "8501",
            "--server.enableCORS", "false",
            "--server.enableXsrfProtection", "false",
            "--server.fileWatcherType", "none"
        ]
        
        process = subprocess.Popen(
            streamlit_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env  # 传递环境变量
        )
        
        # 实时输出streamlit日志
        for line in process.stdout:
            log(f"[WEB] {line.strip()}")
        
        process.wait()
        
    except Exception as e:
        log(f"❌ Web界面异常: {e}")
        import traceback
        traceback.print_exc()
        # Web界面异常后等待一段时间再重试
        time.sleep(10)
        log("🔄 重启Web界面...")
        run_web_interface()

def signal_handler(signum, frame):
    """处理终止信号"""
    log("⚠️ 收到终止信号，正在停止所有服务...")
    
    # 终止所有子进程
    for p in processes:
        try:
            if p.is_alive():
                log(f"停止进程: {p.name}")
                p.terminate()
        except (ValueError, AttributeError) as e:
            # 进程已经终止或无效
            log(f"进程 {p.name} 已停止")
    
    # 等待所有进程结束
    for p in processes:
        try:
            p.join(timeout=5)
            if p.is_alive():
                log(f"强制终止进程: {p.name}")
                p.kill()
        except (ValueError, AttributeError) as e:
            # 进程已经终止或无效
            pass
    
    log("✅ 所有服务已停止")
    sys.exit(0)

def check_environment():
    """检查运行环境"""
    log("🔍 检查运行环境...")
    
    # 检查Python版本
    python_version = sys.version_info
    log(f"Python版本: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 8):
        log("❌ 错误: 需要Python 3.8或更高版本")
        sys.exit(1)
    
    # 创建必要的目录
    try:
        # Streamlit配置目录
        streamlit_config_dir = os.path.join(os.getcwd(), '.streamlit_config')
        os.makedirs(streamlit_config_dir, exist_ok=True)
        log(f"✅ Streamlit配置目录: {streamlit_config_dir}")
        
        # 数据目录
        data_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # .streamlit目录（如果不存在）
        streamlit_dir = os.path.join(os.getcwd(), '.streamlit')
        os.makedirs(streamlit_dir, exist_ok=True)
    except Exception as e:
        log(f"⚠️ 警告: 创建目录失败 - {e}")
    
    # 检查必要文件
    required_files = ['deepseekok2.py', 'streamlit_app.py', 'data_manager.py']
    for file in required_files:
        if not Path(file).exists():
            log(f"❌ 错误: 缺少必要文件 {file}")
            sys.exit(1)
    
    # 检查.env文件
    if not Path('.env').exists():
        log("⚠️ 警告: .env文件不存在")
        log("   请创建.env文件并配置API密钥")
        if Path('env.template').exists():
            log("   可以从env.template复制: cp env.template .env")
    
    # 检查依赖包
    try:
        import ccxt
        import openai
        import pandas
        import streamlit
        import plotly
        log("✅ 所有依赖包已安装")
    except ImportError as e:
        log(f"❌ 错误: 缺少依赖包 - {e}")
        log("   请运行: pip install -r requirements.txt")
        sys.exit(1)
    
    log("✅ 环境检查通过")

def main():
    """主函数"""
    # 打印启动信息
    print("=" * 60)
    print("🤖 BTC自动交易机器人 - 统一启动程序")
    print("=" * 60)
    print()
    
    # 检查环境
    check_environment()
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 根据配置决定是否启动Web界面
    if WEB_ENABLED:
        log("🚀 启动交易程序 + Web监控界面...")
    else:
        log("🚀 启动交易程序（Web界面已禁用）...")
    print()
    
    # 创建交易程序进程（始终启动）
    trading_process = Process(
        target=run_trading_bot,
        name="TradingBot"
    )
    processes.append(trading_process)
    
    # 根据配置决定是否创建Web界面进程
    if WEB_ENABLED:
        web_process = Process(
            target=run_web_interface,
            name="WebInterface"
        )
        processes.append(web_process)
    
    # 启动进程
    trading_process.start()
    if WEB_ENABLED:
        time.sleep(2)  # 等待交易程序初始化
        web_process.start()
    
    if WEB_ENABLED:
        log("✅ 交易程序 + Web界面已启动")
        print()
        print("=" * 60)
        print("📊 服务信息")
        print("=" * 60)
        print("🤖 交易程序: 运行中")
        print(f"🌐 Web监控界面: http://0.0.0.0:{WEB_PORT}")
        print("   （宝塔面板会自动映射到您的域名）")
        print("=" * 60)
    else:
        log("✅ 交易程序已启动（Web界面已禁用）")
        print()
        print("=" * 60)
        print("📊 服务信息")
        print("=" * 60)
        print("🤖 交易程序: 运行中")
        print("🌐 Web监控界面: 已禁用")
        print("   （如需启用，请修改配置文件）")
        print("=" * 60)
    print()
    log("💡 按 Ctrl+C 停止所有服务")
    print()
    
    # 监控进程状态
    try:
        while True:
            time.sleep(10)
            
            # 检查进程是否存活
            for p in processes[:]:  # 使用副本遍历，避免修改列表时出错
                try:
                    if not p.is_alive():
                        log(f"⚠️ 警告: 进程 {p.name} 已停止，正在重启...")
                        
                        # 创建新进程
                        if p.name == "TradingBot":
                            new_process = Process(
                                target=run_trading_bot,
                                name="TradingBot"
                            )
                        elif p.name == "WebInterface" and WEB_ENABLED:
                            new_process = Process(
                                target=run_web_interface,
                                name="WebInterface"
                            )
                        else:
                            continue  # 跳过不重启的进程
                        
                        # 替换进程
                        processes.remove(p)
                        processes.append(new_process)
                        new_process.start()
                        
                        log(f"✅ 进程 {new_process.name} 已重启")
                except (ValueError, AttributeError) as e:
                    log(f"⚠️ 检查进程状态时出错: {e}")
    
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

if __name__ == "__main__":
    main()

