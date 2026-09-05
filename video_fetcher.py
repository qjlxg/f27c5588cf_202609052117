import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from itemsview import ItemsView
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')
MAX_THREADS = 10  # 最大线程数

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def get_clean_filename(url):
    """从URL中提取干净的文件名并解码"""
    path = urlparse(url).path
    filename = os.path.basename(path)
    return unquote(filename)

def parse_site(base_url, max_depth=5):
    """单站点抓取逻辑"""
    visited_dirs = set()
    media_items = []

    def recursive_crawl(current_url, depth):
        if depth > max_depth:
            return
        
        clean_url = current_url.rstrip('/') + '/'
        if clean_url in visited_dirs:
            return
        visited_dirs.add(clean_url)

        try:
            # 降低超时，增加响应速度
            response = requests.get(current_url, headers=HEADERS, timeout=10, verify=False)
            if response.status_code != 200:
                return
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                
                # 过滤常见无关链接
                if not href or any(x in href.lower() for x in ['?C=', '?N=', '?S=', '?D=', '../', './']):
                    continue
                if href.startswith(('mailto:', 'javascript:', '#')):
                    continue

                absolute_url = urljoin(current_url, href)
                parsed = urlparse(absolute_url)
                path_lower = parsed.path.lower()

                # 目录判断：以/结尾，或者没有后缀名且不含点
                is_dir = href.endswith('/') or ('.' not in os.path.basename(path_lower) and not path_lower.endswith(VIDEO_EXTENSIONS))

                if is_dir:
                    # 排除干扰目录名
                    skip_keywords = ['login', 'etc', 'bin', 'search', 'style', 'assets']
                    if not any(k in path_lower for k in skip_keywords):
                        recursive_crawl(absolute_url, depth + 1)
                
                elif path_lower.endswith(VIDEO_EXTENSIONS):
                    file_name = get_clean_filename(absolute_url)
                    if len(file_name) > 3:
                        domain = urlparse(base_url).netloc
                        media_items.append({
                            "name": f"[{domain}] {file_name}",
                            "url": absolute_url,
                            "group": domain
                        })
        except Exception as e:
            pass # 递归中静默处理单页错误

    recursive_crawl(base_url, 1)
    return media_items

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"Error: {SOURCES_FILE} not found.")
        return

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    all_items = []
    seen_urls = set()

    print(f"开始任务，线程数: {MAX_THREADS}...")

    # 使用线程池并发抓取不同网站
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(parse_site, url): url for url in urls}
        
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
                print(f"完成: {url} (新增 {count} 条)")
            except Exception as e:
                print(f"失败: {url} 错误: {e}")

    # 写入 M3U
    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in all_items:
            # 增加 group-title 方便播放器分类
            f.write(f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n')
            f.write(f"{item['url']}\n")

    print(f"\n任务结束，共收集 {len(all_items)} 个视频。")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
