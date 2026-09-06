import os
import requests
import random
import time
import re
import sqlite3
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3
from requests.adapters import HTTPAdapter

# 禁用 HTTPS 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置参数
SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"
CACHE_DB = "crawl_cache.db"
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')
MAX_THREADS = 10  # 爬取线程数
VALIDATE_THREADS = 20 # 验证线程数

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

def init_db():
    """初始化 SQLite 缓存数据库"""
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS site_candidates (
            base_url TEXT PRIMARY KEY,
            candidates TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_candidates(base_url):
    """从数据库读取已有缓存"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT candidates FROM site_candidates WHERE base_url = ?', (base_url,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0].split('\n')
    except Exception:
        pass
    return None

def save_candidates_to_cache(base_url, candidates):
    """保存候选链接至数据库缓存"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO site_candidates (base_url, candidates) VALUES (?, ?)',
                       (base_url, '\n'.join(candidates)))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_session(pool_size):
    """创建一个带有大连接池的 Session"""
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_clean_filename(url):
    """从URL中提取干净的文件名并解码，配合正则剔除异常字符"""
    try:
        path = urlparse(url).path
        filename = os.path.basename(path)
        if not filename:
            return "unknown_video"
        filename = unquote(filename)
        # 使用正则替换掉回车、换行、制表符及不可见控制字符
        filename = re.sub(r'[\r\n\t\x00-\x1f]', '', filename)
        return filename if filename else "unknown_video"
    except Exception:
        return "unknown_video"

def is_url_valid(url, session):
    """通过 HEAD/GET 请求验证 URL 是否有效"""
    try:
        # 尝试 HEAD 请求
        response = session.head(url, headers=HEADERS, timeout=7, verify=False, allow_redirects=True)
        if response.status_code == 200:
            return True
    except Exception:
        pass

    try:
        # 如果 HEAD 不行，尝试 GET 流式请求（只读头部）
        response = session.get(url, headers=HEADERS, timeout=7, verify=False, stream=True)
        return response.status_code == 200
    except Exception:
        return False

def parse_site(base_url, max_depth=3):
    """阶段一：递归收集链接（含断点续传检测）"""
    # 优先使用本地 SQLite 缓存，避免重复请求源站
    cached = get_cached_candidates(base_url)
    if cached is not None:
        return base_url, cached

    visited_dirs = set()
    candidate_urls = set()
    session = get_session(5) # 爬取阶段每个站点小连接池即可

    def recursive_crawl(current_url, depth):
        if depth > max_depth:
            return

        # 规范化 URL 避免重复访问
        clean_url = current_url.rstrip('/') + '/'
        if clean_url in visited_dirs:
            return
        visited_dirs.add(clean_url)

        # 爬取时的随机延时，保护源站
        time.sleep(random.uniform(0.2, 0.5))

        try:
            response = session.get(current_url, headers=HEADERS, timeout=10, verify=False)
            if response.status_code != 200:
                return

            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()

                # 过滤无关链接
                if not href or any(x in href.lower() for x in ['?c=', '?n=', '?s=', '?d=', '../', './']):
                    continue
                if href.startswith(('mailto:', 'javascript:', '#')):
                    continue

                absolute_url = urljoin(current_url, href)
                parsed = urlparse(absolute_url)
                path_lower = parsed.path.lower()

                # 简单逻辑判断目录还是文件
                is_dir = href.endswith('/') or ('.' not in os.path.basename(path_lower))

                if is_dir:
                    skip_keywords = ['login', 'etc', 'bin', 'search', 'style', 'assets', 'admin', 'icon']
                    if not any(k in path_lower for k in skip_keywords):
                        recursive_crawl(absolute_url, depth + 1)
                elif path_lower.endswith(VIDEO_EXTENSIONS):
                    candidate_urls.add(absolute_url)
        except Exception:
            pass

    recursive_crawl(base_url, 1)
    result_list = list(candidate_urls)
    save_candidates_to_cache(base_url, result_list)
    return base_url, result_list

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"错误: 未找到源文件 {SOURCES_FILE}")
        return

    init_db()

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"开始任务，并发线程数: {MAX_THREADS}")
    print(f"阶段一：正在深度爬取目录 (Max Depth: 2)...")

    site_candidates = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as crawl_executor:
        # 将默认最大深度降为 2 级，防止文件过大导致播放器卡死
        future_to_url = {crawl_executor.submit(parse_site, url, 2): url for url in urls}

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                base_url, candidates = future.result()
                site_candidates[base_url] = candidates
                print(f"  [+] {base_url} -> 发现 {len(candidates)} 个候选链接")
            except Exception as e:
                print(f"  [!] {url} 爬取失败: {e}")

    print(f"\n阶段二：正在并发验证链接存活性 (并发数: {VALIDATE_THREADS})...")

    all_items = []
    seen_urls = set()
    # 验证阶段使用大连接池 Session
    validate_session = get_session(VALIDATE_THREADS)

    with ThreadPoolExecutor(max_workers=VALIDATE_THREADS) as val_executor:
        future_to_info = {}
        for base_url, candidates in site_candidates.items():
            domain = urlparse(base_url).netloc
            for cand_url in candidates:
                if cand_url not in seen_urls:
                    seen_urls.add(cand_url)
                    future = val_executor.submit(is_url_valid, cand_url, validate_session)
                    future_to_info[future] = (domain, cand_url)

        total_to_verify = len(future_to_info)
        processed = 0

        for future in as_completed(future_to_info):
            domain, cand_url = future_to_info[future]
            processed += 1
            try:
                if future.result():
                    file_name = get_clean_filename(cand_url)
                    if len(file_name) > 3:
                        all_items.append({
                            "name": f"[{domain}] {file_name}",
                            "url": cand_url,
                            "group": domain
                        })
            except Exception:
                pass

            if processed % 10 == 0 or processed == total_to_verify:
                print(f"\r  进度: {processed}/{total_to_verify} (已找到有效视频: {len(all_items)})", end="", flush=True)

    print("\n")
    if all_items:
        # 按域名分组排序，让播放列表更整齐
        all_items.sort(key=lambda x: x['group'])

        with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for item in all_items:
                f.write(f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n')
                f.write(f"{item['url']}\n")
        print(f"任务圆满结束，有效资源: {len(all_items)}")
        print(f"结果已保存至: {OUTPUT_M3U}")
    else:
        print("任务结束，未找到任何有效视频。")

if __name__ == "__main__":
    main()
