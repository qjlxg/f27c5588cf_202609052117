import os
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')
MAX_THREADS = 10  # 最大并发线程数

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def get_clean_filename(url):
    """从URL中提取干净的文件名并解码"""
    path = urlparse(url).path
    filename = os.path.basename(path)
    return unquote(filename)

def is_url_valid(url):
    """通过 HEAD 请求验证 URL 是否有效（流媒体有效性检测）"""
    try:
        # 优先使用 HEAD 请求，不下载内容只查状态
        response = requests.head(url, headers=HEADERS, timeout=5, verify=False, allow_redirects=True)
        if response.status_code == 200:
            return True
    except:
        pass
    
    try:
        # 如果 HEAD 不被允许，尝试极简的 GET 请求（stream=True 不下载正文）
        response = requests.get(url, headers=HEADERS, timeout=5, verify=False, stream=True)
        return response.status_code == 200
    except:
        return False

def parse_site(base_url, max_depth=5):
    """单站点深度递归抓取逻辑"""
    visited_dirs = set()
    media_items = []

    def recursive_crawl(current_url, depth):
        if depth > max_depth:
            return
        
        clean_url = current_url.rstrip('/') + '/'
        if clean_url in visited_dirs:
            return
        visited_dirs.add(clean_url)

        # 防止封 IP：在每次页面抓取前进行随机延时
        time.sleep(random.uniform(0.5, 1.5))

        try:
            response = requests.get(current_url, headers=HEADERS, timeout=10, verify=False)
            if response.status_code != 200:
                return
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                
                # 过滤常见无效链接及目录索引排序参数
                if not href or any(x in href.lower() for x in ['?c=', '?n=', '?s=', '?d=', '../', './']):
                    continue
                if href.startswith(('mailto:', 'javascript:', '#')):
                    continue

                absolute_url = urljoin(current_url, href)
                parsed = urlparse(absolute_url)
                path_lower = parsed.path.lower()

                # 判断是否为目录：以/结尾，或路径名中无扩展名点号
                is_dir = href.endswith('/') or ('.' not in os.path.basename(path_lower) and not path_lower.endswith(VIDEO_EXTENSIONS))

                if is_dir:
                    # 排除常见的系统及管理干扰目录
                    skip_keywords = ['login', 'etc', 'bin', 'search', 'style', 'assets', 'admin']
                    if not any(k in path_lower for k in skip_keywords):
                        recursive_crawl(absolute_url, depth + 1)
                
                elif path_lower.endswith(VIDEO_EXTENSIONS):
                    # 在加入列表前进行 URL 有效性验证
                    if is_url_valid(absolute_url):
                        file_name = get_clean_filename(absolute_url)
                        if len(file_name) > 3:
                            domain = urlparse(base_url).netloc
                            media_items.append({
                                "name": f"[{domain}] {file_name}",
                                "url": absolute_url,
                                "group": domain
                            })
        except Exception:
            pass # 抓取过程中个别页面报错不中断整体任务

    recursive_crawl(base_url, 1)
    return media_items

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"错误: 未找到源文件 {SOURCES_FILE}")
        return

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    all_items = []
    seen_urls = set()

    print(f"开始任务，并发线程数: {MAX_THREADS}")
    print("当前配置：深度 3 层，包含流媒体存活检测与随机防封延时。")

    # 使用线程池并发抓取不同网站
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # 此处明确传入深度参数 3
        future_to_url = {executor.submit(parse_site, url, 4): url for url in urls}
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results = future.result()
                count = 0
                for item in results:
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        all_items.append(item)
                        count += 1
                print(f"完成: {url} (新增验证通过视频: {count} 条)")
            except Exception as e:
                print(f"失败: {url} 错误信息: {e}")

    # 生成 M3U 播放列表文件
    if all_items:
        with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for item in all_items:
                # 使用 group-title 属性进行域名分类
                f.write(f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n')
                f.write(f"{item['url']}\n")
        print(f"\n任务圆满结束，共成功收集并验证了 {len(all_items)} 个视频资源。")
        print(f"结果已保存至: {OUTPUT_M3U}")
    else:
        print("\n任务结束，未找到任何有效的视频资源。")

if __name__ == "__main__":
    import urllib3
    # 忽略 https 证书警告
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
