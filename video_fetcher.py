import os
import subprocess
from datetime import datetime, timezone, timedelta

# 定义路径
SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"

def fetch_and_parse():
    if not os.path.exists(SOURCES_FILE):
        print(f"未找到源文件: {SOURCES_FILE}")
        return []
    
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    media_items = []
    for line in lines:
        url = line.strip()
        if not url or url.startswith("#"):
            continue
            
        # 示例逻辑：解析或抓取文件名与真实视频链接
        # 您可以根据实际情况修改这里的抓取/解析逻辑
        filename = url.split("//")[-1].split("/")[0] # 简易提取域名/IP作为标识或文件名
        
        # 假设我们最终拿到的是形如 (文件名, 视频直链) 的元组
        media_items.append({
            "name": f"视频源 - {filename}",
            "url": url
        })
        
    return media_items

def generate_m3u(items):
    # 如果您有独立的 convert_m3u.py，也可以通过子进程调用它，或者直接在这里生成标准 M3U
    # 这里直接生成标准手机可播的 m3u 格式内容
    m3u_content = "#EXTM3U\n"
    for item in items:
        m3u_content += f"#EXTINF:-1,{item['name']}\n"
        m3u_content += f"{item['url']}\n"
        
    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write(m3u_content)
    print(f"成功生成播放列表: {OUTPUT_M3U}，共包含 {len(items)} 个条目。")

if __name__ == "__main__":
    # 如果本地有 convert_m3u.py，也可以选择在此调用
    if os.path.exists("convert_m3u.py"):
        print("检测到 convert_m3u.py，正在协同处理...")
        # 视您的 convert_m3u.py 接口而定，可直接调用
        subprocess.run(["python", "convert_m3u.py"], check=False)
    
    items = fetch_and_parse()
    if items:
        generate_m3u(items)