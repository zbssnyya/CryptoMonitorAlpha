#!/usr/bin/env python3
import requests
import pandas as pd
import time
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, scrolledtext
from tkinter import font as tkFont # <--- 引入 tkFont
from datetime import datetime
import threading
import sys
import os
import json

# Matplotlib 和 mplfinance 用于图表
import matplotlib
matplotlib.use("TkAgg") # 重要：告诉matplotlib使用Tkinter后端
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import mplfinance as mpf


# --- 配置参数 ---
DEFAULT_CONFIG = {
    "top_n_coins": 100, 
    "vs_currency": 'usd',
    "short_ma_period": 5,
    "long_ma_period": 20,
    "days_for_1h_data_ma": 3,      
    "days_for_4h_data_base_ma": 10, 
    "days_for_1h_chart": "2",      
    "days_for_4h_chart": "14",     
    "check_interval_seconds": 300
}
COINGECKO_API_BASE_URL = "https://api.coingecko.com/api/v3"

# --- 全局变量 ---
# ... (全局变量保持不变)
monitoring_active = False
monitor_thread = None
last_alert_status = {}
top_coins_data_detailed = []
fig_1h, ax_1h = None, None
fig_4h, ax_4h = None, None
canvas_1h, canvas_4h = None, None
current_selected_coin_id = None


def get_application_path():
    # ... (此函数保持不变)
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    elif __file__:
        application_path = os.path.dirname(os.path.abspath(__file__))
    else:
        application_path = os.getcwd()
    return application_path

CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = os.path.join(get_application_path(), CONFIG_FILE_NAME)

def load_config():
    # ... (此函数保持不变)
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                return {**DEFAULT_CONFIG, **{k: loaded_config.get(k, DEFAULT_CONFIG.get(k)) for k in DEFAULT_CONFIG}}
        except json.JSONDecodeError:
            messagebox.showerror("Error", f"配置文件 {CONFIG_FILE_NAME} 格式错误，将使用默认配置。")
            return DEFAULT_CONFIG
        except Exception as e:
            messagebox.showerror("Error", f"加载配置文件失败 ({e})，将使用默认配置。")
            return DEFAULT_CONFIG
    else:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        messagebox.showinfo("Info", f"未找到配置文件 {CONFIG_FILE_NAME}，已在程序目录下创建默认配置。\n请根据需要修改后重启程序。")
        return DEFAULT_CONFIG

config = load_config()
# ... (config 加载后的全局变量赋值保持不变)
TOP_N_COINS = int(config['top_n_coins'])
VS_CURRENCY = config['vs_currency']
SHORT_MA_PERIOD = int(config['short_ma_period'])
LONG_MA_PERIOD = int(config['long_ma_period'])
DAYS_FOR_1H_DATA_MA = int(config['days_for_1h_data_ma'])
DAYS_FOR_4H_DATA_BASE_MA = int(config['days_for_4h_data_base_ma'])
DAYS_FOR_1H_CHART = str(config['days_for_1h_chart']) 
DAYS_FOR_4H_CHART = str(config['days_for_4h_chart']) 
CHECK_INTERVAL_SECONDS = int(config['check_interval_seconds'])


class CryptoMonitorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("加密货币监控 Alpha (MA, 价格, K线图)")
        self.geometry("1000x750") 

        # --- 字体定义 ---
        # 获取 ScrolledText 的默认字体信息
        default_font = tkFont.nametofont(scrolledtext.ScrolledText().cget("font"))
        default_family = default_font.actual("family")
        default_size = default_font.actual("size")
        
        # 定义新的提醒字体：红色、加粗、字号增大2
        self.alert_font_style = tkFont.Font(family=default_family, 
                                            size=default_size + 2, 
                                            weight="bold")

        # --- 顶部控制区域 ---
        # ... (顶部控制区域代码保持不变)
        self.top_controls_frame = tk.Frame(self)
        self.top_controls_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.config_frame = tk.LabelFrame(self.top_controls_frame, text="监控设置")
        self.config_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(self.config_frame, text=f"监控前 {TOP_N_COINS} 币种 (计价: {VS_CURRENCY.upper()})").pack(side=tk.LEFT, padx=5)
        self.start_button = tk.Button(self.config_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = tk.Button(self.config_frame, text="停止监控", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.refresh_button = tk.Button(self.config_frame, text="刷新价格", command=self.refresh_displayed_prices, state=tk.DISABLED)
        self.refresh_button.pack(side=tk.LEFT, padx=5)

        # --- 主内容区域 (左右分隔) ---
        # ... (main_paned_window, left_pane, coins_frame, coins_tree 初始化代码保持不变)
        self.main_paned_window = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.main_paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.left_pane = tk.PanedWindow(self.main_paned_window, orient=tk.VERTICAL, sashrelief=tk.RAISED)
        self.main_paned_window.add(self.left_pane, width=500)

        self.coins_frame = tk.LabelFrame(self.left_pane, text="监控币种实时信息 (UTC+0)")
        self.left_pane.add(self.coins_frame, height=400)

        self.coins_tree = ttk.Treeview(self.coins_frame, columns=("rank", "name", "price", "change_24h", "change_1d_utc"), show="headings")
        self.coins_tree.heading("rank", text="排名")
        self.coins_tree.heading("name", text="名称 (符号)")
        self.coins_tree.heading("price", text=f"现价 ({VS_CURRENCY.upper()})")
        self.coins_tree.heading("change_24h", text="24h%")
        self.coins_tree.heading("change_1d_utc", text="UTC日%")
        self.coins_tree.column("rank", width=40, anchor=tk.CENTER, stretch=False)
        self.coins_tree.column("name", width=150, stretch=True)
        self.coins_tree.column("price", width=90, anchor=tk.E, stretch=False)
        self.coins_tree.column("change_24h", width=70, anchor=tk.E, stretch=False)
        self.coins_tree.column("change_1d_utc", width=70, anchor=tk.E, stretch=False)
        self.coins_tree_scrollbar = ttk.Scrollbar(self.coins_frame, orient="vertical", command=self.coins_tree.yview)
        self.coins_tree.configure(yscrollcommand=self.coins_tree_scrollbar.set)
        self.coins_tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.coins_tree.pack(fill=tk.BOTH, expand=True)
        self.coins_tree.bind("<<TreeviewSelect>>", self.on_coin_select)

        self.coins_tree.tag_configure('positive', foreground='red')
        self.coins_tree.tag_configure('negative', foreground='green')
        self.coins_tree.tag_configure('neutral', foreground='black')

        self.alert_frame = tk.LabelFrame(self.left_pane, text="MA交叉提醒")
        self.left_pane.add(self.alert_frame) 
        self.alert_text = scrolledtext.ScrolledText(self.alert_frame, state=tk.DISABLED, height=8)
        self.alert_text.pack(fill=tk.BOTH, expand=True)
        
        # 为 ScrolledText 定义标签和字体
        self.alert_text.tag_configure("alert_style", 
                                      font=self.alert_font_style, 
                                      foreground="red")


        # --- 右侧面板 (K线图) ---
        # ... (right_pane 和 K线图相关初始化代码保持不变)
        self.right_pane = tk.Frame(self.main_paned_window) 
        self.main_paned_window.add(self.right_pane)
        self.charts_notebook = ttk.Notebook(self.right_pane) 
        self.chart_frame_1h_container = ttk.Frame(self.charts_notebook)
        self.charts_notebook.add(self.chart_frame_1h_container, text='1H K线图')
        self.chart_label_1h = tk.Label(self.chart_frame_1h_container, text="请在左侧列表选择币种以加载图表")
        self.chart_label_1h.pack(expand=True, fill=tk.BOTH)
        self.chart_frame_4h_container = ttk.Frame(self.charts_notebook)
        self.charts_notebook.add(self.chart_frame_4h_container, text='4H K线图')
        self.chart_label_4h = tk.Label(self.chart_frame_4h_container, text="请在左侧列表选择币种以加载图表")
        self.chart_label_4h.pack(expand=True, fill=tk.BOTH)
        self.charts_notebook.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        self.selected_coin_label = tk.Label(self.right_pane, text="当前选择: 无")
        self.selected_coin_label.pack(fill=tk.X, pady=2)

        # --- 底部状态栏 ---
        # ... (底部状态栏代码保持不变)
        self.status_label = tk.StringVar(self)
        self.status_label.set("就绪")
        tk.Label(self, textvariable=self.status_label, bd=1, relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._init_chart_canvases()

    def _init_chart_canvases(self):
        # ... (此方法保持不变)
        global fig_1h, ax_1h, canvas_1h, fig_4h, ax_4h, canvas_4h
        fig_1h, ax_1h = plt.subplots(figsize=(5,3)) 
        plt.style.use('seaborn-v0_8-darkgrid') 
        fig_1h.patch.set_facecolor('lightgrey') 
        ax_1h.set_facecolor('white') 
        canvas_1h = FigureCanvasTkAgg(fig_1h, master=self.chart_frame_1h_container)
        fig_4h, ax_4h = plt.subplots(figsize=(5,3))
        fig_4h.patch.set_facecolor('lightgrey')
        ax_4h.set_facecolor('white')
        canvas_4h = FigureCanvasTkAgg(fig_4h, master=self.chart_frame_4h_container)

    def update_coins_display(self, coins_details):
        # ... (此方法保持不变)
        for item in self.coins_tree.get_children():
            self.coins_tree.delete(item)
        for rank, coin_detail in enumerate(coins_details, 1):
            try:
                coin_id, symbol, name, price, change_24h_raw, _, change_1d_utc_raw = coin_detail
                price_str = f"{price:,.4f}" if price is not None else "N/A"
                tags_24h = ['neutral']
                change_24h_str = "N/A"
                if change_24h_raw is not None:
                    change_24h_str = f"{change_24h_raw:.2f}%"
                    if change_24h_raw > 0: tags_24h = ['positive']
                    elif change_24h_raw < 0: tags_24h = ['negative']
                tags_1d_utc = ['neutral']
                change_1d_utc_str = "N/A"
                if change_1d_utc_raw is not None:
                    change_1d_utc_str = f"{change_1d_utc_raw:.2f}%"
                    if change_1d_utc_raw > 0: tags_1d_utc = ['positive']
                    elif change_1d_utc_raw < 0: tags_1d_utc = ['negative']
                item_main_tag = tags_24h[0] 
                self.coins_tree.insert("", tk.END, iid=coin_id, values=(
                    rank,
                    f"{name} ({symbol.upper()})",
                    price_str,
                    change_24h_str, 
                    change_1d_utc_str 
                ), tags=(item_main_tag,)) 
            except Exception as e:
                print(f"更新币种显示错误: {coin_detail} - {e}")
                self.coins_tree.insert("", tk.END, values=(rank, f"数据错误", "N/A", "N/A", "N/A"))
        self.coins_tree.tag_configure('positive', foreground='red')
        self.coins_tree.tag_configure('negative', foreground='green')

    def on_coin_select(self, event):
        # ... (此方法保持不变)
        global current_selected_coin_id
        selected_item = self.coins_tree.focus() 
        if not selected_item:
            return
        current_selected_coin_id = selected_item
        item_details = self.coins_tree.item(selected_item)
        coin_name_symbol = item_details['values'][1] if item_details['values'] else "N/A"
        self.selected_coin_label.config(text=f"当前选择: {coin_name_symbol} ({current_selected_coin_id})")
        print(f"选中币种: {current_selected_coin_id} - {coin_name_symbol}")
        self.chart_label_1h.pack_forget()
        self.chart_label_4h.pack_forget()
        if canvas_1h: canvas_1h.get_tk_widget().pack(fill=tk.BOTH, expand=True) 
        if canvas_4h: canvas_4h.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.status_label.set(f"正在加载 {coin_name_symbol} 的图表数据...")
        threading.Thread(target=self._load_and_draw_charts, args=(current_selected_coin_id,), daemon=True).start()

    def _load_and_draw_charts(self, coin_id):
        # ... (此方法保持不变)
        global fig_1h, ax_1h, canvas_1h, fig_4h, ax_4h, canvas_4h
        if not coin_id:
            return
        df_1h_chart = get_ohlc_for_chart(coin_id, days_param=DAYS_FOR_1H_CHART, target_interval='1h')
        if df_1h_chart is not None and not df_1h_chart.empty:
            self.draw_chart(df_1h_chart, fig_1h, ax_1h, canvas_1h, f"{coin_id.capitalize()} 1H K线")
        else:
            ax_1h.clear()
            ax_1h.text(0.5, 0.5, "无1H图表数据", ha='center', va='center')
            canvas_1h.draw_idle()
            print(f"无1H图表数据 для {coin_id}")
        df_4h_chart = get_ohlc_for_chart(coin_id, days_param=DAYS_FOR_4H_CHART, target_interval='4h')
        if df_4h_chart is not None and not df_4h_chart.empty:
            self.draw_chart(df_4h_chart, fig_4h, ax_4h, canvas_4h, f"{coin_id.capitalize()} 4H K线")
        else:
            ax_4h.clear()
            ax_4h.text(0.5, 0.5, "无4H图表数据", ha='center', va='center')
            canvas_4h.draw_idle()
            print(f"无4H图表数据 для {coin_id}")
        self.status_label.set(f"{coin_id.capitalize()} 图表加载完成。")

    def draw_chart(self, df, fig, ax, canvas, title):
        # ... (此方法保持不变)
        if df is None or df.empty:
            ax.clear()
            ax.text(0.5, 0.5, "无数据可绘制", ha='center', va='center')
            canvas.draw_idle()
            return
        ax.clear() 
        mc = mpf.make_marketcolors(up='red', down='green',
                                   edge={'up':'red', 'down':'green'},
                                   wick={'up':'red', 'down':'green'},
                                   volume='inherit', ohlc='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='default', gridstyle=':')
        df.index.name = 'Date' 
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            print("K线图数据缺少OHLC列")
            ax.text(0.5, 0.5, "数据格式错误", ha='center', va='center')
            canvas.draw_idle()
            return
        try:
            mpf.plot(df, type='candle', style=s, ax=ax,
                     datetime_format='%m-%d %H:%M', 
                     xrotation=20, 
                     show_nontrading=False,
                     tight_layout=True) 
            ax.set_title(title, fontsize=10)
            ax.tick_params(axis='x', labelsize=8)
            ax.tick_params(axis='y', labelsize=8)
        except Exception as e:
            print(f"绘制图表错误 ({title}): {e}")
            ax.text(0.5, 0.5, f"绘制错误: {e}", ha='center', va='center', fontsize=8, color='red')
        canvas.draw_idle() 

    def on_closing(self): 
        # ... (此方法保持不变)
        global monitoring_active, monitor_thread
        self.status_label.set("正在关闭...")
        monitoring_active = False
        if monitor_thread and monitor_thread.is_alive():
            print("等待监控线程结束...")
            monitor_thread.join(timeout=7)
            if monitor_thread.is_alive(): print("监控线程未能及时结束。")
        print("销毁窗口。")
        if canvas_1h: canvas_1h.get_tk_widget().destroy()
        if canvas_4h: canvas_4h.get_tk_widget().destroy()
        if fig_1h: plt.close(fig_1h) 
        if fig_4h: plt.close(fig_4h)
        self.destroy()

    def start_monitoring(self): 
        # ... (此方法保持不变)
        global monitoring_active, monitor_thread, top_coins_data_detailed
        if not monitoring_active:
            self.status_label.set("获取监控币种及价格...")
            self.start_button.config(state=tk.DISABLED)
            self.refresh_button.config(state=tk.DISABLED)
            threading.Thread(target=self._fetch_and_start_monitoring, daemon=True).start()
        else:
            messagebox.showinfo("Info", "监控已在运行。")

    def _fetch_and_start_monitoring(self): 
        # ... (此方法保持不变)
        global monitoring_active, monitor_thread, top_coins_data_detailed
        fetched_data = get_top_coin_data_detailed(TOP_N_COINS)
        if fetched_data:
            top_coins_data_detailed = fetched_data
            self.update_coins_display(top_coins_data_detailed)
            monitoring_active = True
            self.status_label.set("开始MA交叉监控...")
            self.stop_button.config(state=tk.NORMAL)
            self.refresh_button.config(state=tk.NORMAL)
            monitor_thread = threading.Thread(target=self.monitoring_loop_ma_cross, daemon=True)
            monitor_thread.start()
        else:
            self.status_label.set("获取监控币种失败。请检查网络或API。")
            self.start_button.config(state=tk.NORMAL)

    def refresh_displayed_prices(self): 
        # ... (此方法保持不变)
        if not monitoring_active and not (monitor_thread and monitor_thread.is_alive()):
            self.status_label.set("正在刷新价格...") 
            threading.Thread(target=self._fetch_and_display_prices, daemon=True).start()
            return
        self.status_label.set("正在刷新价格列表...")
        self.refresh_button.config(state=tk.DISABLED)
        threading.Thread(target=self._fetch_and_display_prices, daemon=True).start()

    def _fetch_and_display_prices(self): 
        # ... (此方法保持不变)
        global top_coins_data_detailed
        fetched_data = get_top_coin_data_detailed(TOP_N_COINS)
        if fetched_data:
            top_coins_data_detailed = fetched_data
            self.update_coins_display(top_coins_data_detailed)
            self.status_label.set(f"价格已于 {datetime.utcnow().strftime('%H:%M:%S UTC')} 更新")
        else:
            self.status_label.set("刷新价格失败。")
        if monitoring_active :
             self.refresh_button.config(state=tk.NORMAL)
        elif not (monitor_thread and monitor_thread.is_alive()): 
            self.refresh_button.config(state=tk.NORMAL)

    def stop_monitoring(self): 
        # ... (此方法保持不变)
        global monitoring_active
        if monitoring_active:
            monitoring_active = False
            self.status_label.set("正在停止MA交叉监控...")
            self.stop_button.config(state=tk.DISABLED)
        else:
            messagebox.showinfo("Info", "MA交叉监控尚未启动。")

    # --- 修改 display_alert 方法 ---
    def display_alert(self, message): 
        self.alert_text.config(state=tk.NORMAL)
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        # 插入带标签的文本
        self.alert_text.insert(tk.END, f"[{timestamp}] {message}\n\n", "alert_style") 
        self.alert_text.see(tk.END)
        self.alert_text.config(state=tk.DISABLED)

    def monitoring_loop_ma_cross(self): 
        # ... (此方法保持不变)
        global top_coins_data_detailed, last_alert_status, monitoring_active
        print(f"MA交叉监控循环启动. 检查间隔: {CHECK_INTERVAL_SECONDS / 60:.1f} 分钟.")
        next_price_refresh_time = time.time() 

        while monitoring_active:
            current_loop_start_time = time.time()
            if current_loop_start_time >= next_price_refresh_time:
                print(f"循环内刷新价格显示... {datetime.utcnow().strftime('%H:%M:%S UTC')}")
                threading.Thread(target=self._fetch_and_display_prices, daemon=True).start()
                next_price_refresh_time = current_loop_start_time + CHECK_INTERVAL_SECONDS 

            print(f"\n--- 新的MA交叉检查周期: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} ---")
            if not top_coins_data_detailed:
                print("币种详细数据为空，无法进行MA检查。")
                time.sleep(5)
                continue
            for coin_detail in top_coins_data_detailed:
                if not monitoring_active: break
                try: coin_id, coin_symbol, coin_name, _, _, _, _ = coin_detail
                except ValueError: print(f"数据格式错误，跳过: {coin_detail}"); continue
                # print(f"处理MA交叉 {coin_name} ({coin_symbol.upper()})...") # 减少打印
                df_1h_raw = get_historical_ohlc_for_ma(coin_id, days=DAYS_FOR_1H_DATA_MA) 
                time.sleep(1.0) 
                if not df_1h_raw.empty: self.calculate_mas_and_check_crossover(df_1h_raw, coin_id, coin_name, coin_symbol, "1H")
                if not monitoring_active: break
                df_hourly_for_4h_resample = get_historical_ohlc_for_ma(coin_id, days=DAYS_FOR_4H_DATA_BASE_MA) 
                time.sleep(1.0)
                if not df_hourly_for_4h_resample.empty and 'timestamp' in df_hourly_for_4h_resample.columns:
                    try:
                        df_temp = df_hourly_for_4h_resample.set_index('timestamp')
                        df_4h_close = df_temp['close'].resample('4H').last().dropna()
                        if not df_4h_close.empty:
                            df_4h_processed = pd.DataFrame({'close': df_4h_close})
                            self.calculate_mas_and_check_crossover(df_4h_processed, coin_id, coin_name, coin_symbol, "4H")
                    except Exception as e: print(f"4H 数据重采样错误 для {coin_name}: {e}")
            if monitoring_active:
                elapsed_time = time.time() - current_loop_start_time
                sleep_duration = max(0, CHECK_INTERVAL_SECONDS - elapsed_time)
                granular_sleep_total = sleep_duration; slept_time = 0; sleep_chunk = 1
                # print(f"--- MA交叉周期完成. 等待 {granular_sleep_total:.1f} 秒. ---") # 减少打印
                while monitoring_active and slept_time < granular_sleep_total:
                    time.sleep(min(sleep_chunk, granular_sleep_total - slept_time))
                    slept_time += sleep_chunk
        print("MA交叉监控循环已停止.")
        self.status_label.set("MA交叉监控已停止。")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def calculate_mas_and_check_crossover(self, df_ohlc, coin_id, coin_name, coin_symbol, interval_str):
        # ... (此方法保持不变，确保其中的 print 语句已修正)
        global last_alert_status
        if df_ohlc.empty or len(df_ohlc) < LONG_MA_PERIOD + 1: return
        if 'close' not in df_ohlc.columns and isinstance(df_ohlc, pd.DataFrame) and len(df_ohlc.columns) == 1: close_prices = df_ohlc.iloc[:, 0]
        elif 'close' in df_ohlc.columns: close_prices = df_ohlc['close']
        else: return
        try:
            ma_short = close_prices.rolling(window=SHORT_MA_PERIOD).mean()
            ma_long = close_prices.rolling(window=LONG_MA_PERIOD).mean()
        except Exception as e: print(f"计算 MA 错误 для {coin_name} ({interval_str}): {e}"); return
        if ma_short.empty or ma_long.empty or len(ma_short) < 2 or len(ma_long) < 2: return
        current_ma_short = ma_short.iloc[-1]; previous_ma_short = ma_short.iloc[-2]
        current_ma_long = ma_long.iloc[-1]; previous_ma_long = ma_long.iloc[-2]
        if pd.isna(current_ma_short) or pd.isna(previous_ma_short) or pd.isna(current_ma_long) or pd.isna(previous_ma_long): return
        current_price = close_prices.iloc[-1]; alert_key = (coin_id, interval_str)
        if previous_ma_short <= previous_ma_long and current_ma_short > current_ma_long:
            current_status_key = "golden_cross"
            if last_alert_status.get(alert_key) != current_status_key:
                message = (f"币种: {coin_name} ({coin_symbol.upper()})\n周期: {interval_str}\n类型: 金叉 (MA{SHORT_MA_PERIOD} 上穿 MA{LONG_MA_PERIOD})\n价格触发时: ${current_price:,.4f}\nMA{SHORT_MA_PERIOD}: {current_ma_short:,.4f}\nMA{LONG_MA_PERIOD}: {current_ma_long:,.4f}")
                self.display_alert(message); print(f"交叉提醒: {message.replace(chr(10), ' | ')}"); last_alert_status[alert_key] = current_status_key
        elif previous_ma_short >= previous_ma_long and current_ma_short < current_ma_long:
            current_status_key = "death_cross"
            if last_alert_status.get(alert_key) != current_status_key:
                message = (f"币种: {coin_name} ({coin_symbol.upper()})\n周期: {interval_str}\n类型: 死叉 (MA{SHORT_MA_PERIOD} 下穿 MA{LONG_MA_PERIOD})\n价格触发时: ${current_price:,.4f}\nMA{SHORT_MA_PERIOD}: {current_ma_short:,.4f}\nMA{LONG_MA_PERIOD}: {current_ma_long:,.4f}")
                self.display_alert(message); print(f"交叉提醒: {message.replace(chr(10), ' | ')}"); last_alert_status[alert_key] = current_status_key
        elif current_ma_short > current_ma_long : last_alert_status[alert_key] = "golden_cross"
        elif current_ma_short < current_ma_long : last_alert_status[alert_key] = "death_cross"

# --- 数据获取函数 ---
# ... (get_top_coin_data_detailed, get_ohlc_for_chart, get_historical_ohlc_for_ma 保持不变)
def get_top_coin_data_detailed(limit=TOP_N_COINS):
    url = f"{COINGECKO_API_BASE_URL}/coins/markets"
    params = {'vs_currency': VS_CURRENCY, 'order': 'market_cap_desc', 'per_page': limit, 'page': 1, 'sparkline': 'false', 'price_change_percentage': '1d,24h'}
    # print(f"调用API (markets): {url} 参数: {params}") # 减少打印
    try:
        response = requests.get(url, params=params, timeout=10); response.raise_for_status(); data = response.json()
        return [(c['id'], c['symbol'], c['name'], c.get('current_price'), c.get('price_change_percentage_24h_in_currency'), c.get('price_change_percentage_24h'), c.get('price_change_percentage_1d_in_currency')) for c in data]
    except requests.exceptions.RequestException as e: print(f"获取顶级币种详细数据错误: {e}"); return []
    except Exception as e: print(f"处理顶级币种详细数据错误: {e}"); return []

def get_ohlc_for_chart(coin_id, days_param, target_interval='1h'):
    print(f"获取图表数据: {coin_id}, days={days_param}, interval_hint={target_interval}")
    url = f"{COINGECKO_API_BASE_URL}/coins/{coin_id}/ohlc"
    params = {'vs_currency': VS_CURRENCY, 'days': str(days_param)}
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True) 
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(inplace=True)
        return df
    except requests.exceptions.RequestException as e:
        print(f"获取图表OHLC数据 ({coin_id}, days={days_param}) 错误: {e}")
        if hasattr(e, 'response') and e.response is not None: print(f"响应: {e.response.text}")
        return pd.DataFrame()
    except Exception as e:
        print(f"处理图表OHLC数据 ({coin_id}) 意外错误: {e}")
        return pd.DataFrame()

def get_historical_ohlc_for_ma(coin_id, days): 
    url = f"{COINGECKO_API_BASE_URL}/coins/{coin_id}/market_chart"
    params = {'vs_currency': VS_CURRENCY, 'days': str(days)}
    try:
        response = requests.get(url, params=params, timeout=15); response.raise_for_status(); data = response.json()
        if not data or 'prices' not in data or not data['prices']: return pd.DataFrame()
        df = pd.DataFrame(data['prices'], columns=['timestamp', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['open'] = df['close']; df['high'] = df['close']; df['low'] = df['close']
        for col in ['open', 'high', 'low', 'close']: df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(inplace=True); return df
    except requests.exceptions.Timeout: print(f"获取MA数据 ({coin_id}, days={days}) 超时。"); return pd.DataFrame()
    except requests.exceptions.RequestException as e: print(f"获取MA数据 ({coin_id}, days={days}) 错误: {e}"); return pd.DataFrame()
    except Exception as e: print(f"处理MA数据 ({coin_id}) 意外错误: {e}"); return pd.DataFrame()


def main():
    app = CryptoMonitorGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
