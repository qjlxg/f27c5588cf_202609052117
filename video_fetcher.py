import os
import sys
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"

# 支持的视频格式后缀
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')

# 模拟真实浏览器的 Header，防拦截
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9"
}

def parse_directory_recursive(base_url, current_depth=1, max_depth=2, visited_dirs=None):
    """
    深度递归抓取目录及子目录下的视频文件
    :param base_url: 当前访问的网址
    :param current_depth: 当前递归深度
    :param max_depth: 最大允许深入的层级（防止死循环和无限抓取）
    :param visited_dirs: 已访问过的目录集合，防止循环引用
    """
    if visited_dirs is None:
        visited_dirs = set()
        
    media_items = []
    
    # 规范化 URL 避免重复访问
    clean_base = base_url.rstrip('/') + '/'
    if clean_base in visited_dirs or current_depth > max_depth:
        return media_items
    visited_dirs.add(clean_base)
    
    try:
        print(f"[{current_depth}/{max_depth}] 正在深度抓取: {base_url}", flush=True)
        # 超时时间延长至 12 秒，适应慢服务器
        response = requests.get(base_url, headers=HEADERS, timeout=12, verify=False)
        
        if response.status_code != 200:
            print(f"  -> 访问失败，状态码: {response.status_code}", flush=True)
            return media_items
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            
            # 过滤无效链接、父目录跳转及查询参数
            if not href or href.startswith('?') or href.startswith('#') or href in ('../', './'):
                continue
                
            absolute_url = urljoin(base_url, href)
            parsed_path = urlparse(absolute_url).path.lower()
            
            # 1. 如果是子目录（以 '/' 结尾），且未超过最大深度，进行递归抓取
            if href.endswith('/') and current_depth < max_depth:
                # 排除可能导致死循环的特殊目录名称
                if not any(skip in href.lower() for skip in ['login', 'logout', 'admin', 'search', 'tag']):
                    sub_items = parse_directory_recursive(absolute_url, current_depth + 1, max_depth, visited_dirs)
                    media_items.extend(sub_items)
            
            # 2. 如果是视频文件，严格校验后缀
            elif parsed_path.endswith(VIDEO_EXTENSIONS):
                file_name = os.path.basename(parsed_path)
                
                # 过滤太短的垃圾文件名或广告文件名
                if len(file_name) < 4:
                    continue
                    
                domain_prefix = urlparse(base_url).netloc
                media_items.append({
                    "name": f"[{domain_prefix}] {file_name}",
                    "url": absolute_url
                })
                
    except requests.exceptions.Timeout:
        print(f"  -> 连接超时 ({base_url})，跳过", flush=True)
    except Exception as e:
        print(f"  -> 解析异常 ({base_url}): {e}", flush=True)
        
    return media_items

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"未找到源文件: {SOURCES_FILE}", flush=True)
        return
        
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        
    total_sources = len(lines)
    print(f"共读取到 {total_sources} 个有效源地址，开始遍历...", flush=True)
    
    all_items = []
    seen_urls = set()  # 用于全局 URL 去重
    
    for idx, url in enumerate(lines, 1):
        print(f"\n({idx}/{total_sources}) 正在处理源: {url}", flush=True)
        
        # 调用递归抓取（限制最大深度为 2 层，可按需调大）
        items = parse_directory_recursive(url, current_depth=1, max_depth=2)
        
        added_count = 0
        for item in items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
                added_count += 1
                
        print(f"  -> 本源新增有效视频: {added_count} 个 (累计去重后: {len(all_items)} 个)", flush=True)
        
    # 生成标准的 M3U 播放列表
    m3u_content = "#EXTM3U\n"
    for item in all_items:
        m3u_content += f"#EXTINF:-1,{item['name']}\n"
        m3u_content += f"{item['url']}\n"
        
    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write(m3u_content)
        
    print(f"\n==================== 任务完成 ====================", flush=True)
    print(f"成功生成播放列表: {OUTPUT_M3U}，全局共收录 {len(all_items)} 个独立视频文件。", flush=True)

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
