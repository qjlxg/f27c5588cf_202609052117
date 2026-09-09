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
CACHE_DB = "crawl_cache.db"
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')
MAX_THREADS = 20  # 爬取线程数

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
        filename = re.sub(r'[\r\n\t\x00-\x1f]', '', filename)
        return filename if filename else "unknown_video"
    except Exception:
        return "unknown_video"

def parse_site(base_url, max_depth=3):
    """递归收集链接（支持3层：根目录 -> 合集 -> 文件）"""
    cached = get_cached_candidates(base_url)
    if cached is not None:
        return base_url, cached

    visited_dirs = set()
    candidate_urls = set()
    session = get_session(5)

    def recursive_crawl(current_url, depth):
        if depth > max_depth:
            return

        clean_url = current_url.rstrip('/') + '/'
        if clean_url in visited_dirs:
            return
        visited_dirs.add(clean_url)

        time.sleep(random.uniform(0.1, 0.3))

        try:
            response = session.get(current_url, headers=HEADERS, timeout=10, verify=False)
            if response.status_code != 200:
                return

            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()

                if not href or any(x in href.lower() for x in ['?c=', '?n=', '?s=', '?d=', '../', './', 'sort=']):
                    continue
                if href.startswith(('mailto:', 'javascript:', '#')):
                    continue

                absolute_url = urljoin(current_url, href)
                parsed = urlparse(absolute_url)
                path_lower = parsed.path.lower()

                is_dir = href.endswith('/') or ('.' not in os.path.basename(path_lower))

                if is_dir:
                    skip_keywords = ['login', 'etc', 'bin', 'search', 'style', 'assets', 'admin', 'icon', 'poster', 'sub', 'subs', 'cover']
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
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")][:3000]

    print(f"开始任务，并发线程数: {MAX_THREADS} (限制处理前 100 个源)")
    print(f"正在深度爬取目录 (Max Depth: 3)...")

    all_items = []
    seen_urls = set()

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as crawl_executor:
        future_to_url = {crawl_executor.submit(parse_site, url, 3): url for url in urls}

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                base_url, candidates = future.result()
                domain = urlparse(base_url).netloc
                for cand_url in candidates:
                    if cand_url not in seen_urls:
                        seen_urls.add(cand_url)
                        file_name = get_clean_filename(cand_url)
                        if len(file_name) > 3:
                            ext = os.path.splitext(cand_url)[1].lower()
                            if not ext:
                                ext = ".unknown"
                            all_items.append({
                                "name": f"[{domain}] {file_name}",
                                "url": cand_url,
                                "group": domain,
                                "ext": ext
                            })
                print(f"  [+] {base_url} -> 发现并收录 {len(candidates)} 个视频链接")
            except Exception as e:
                print(f"  [!] {url} 爬取失败: {e}")

    print("\n")
    if all_items:
        ext_groups = {}
        for item in all_items:
            ext = item['ext']
            if ext not in ext_groups:
                ext_groups[ext] = []
            ext_groups[ext].append(item)

        # 设定拆分阈值：每个文件最多包含的频道数，或者最大估算字节数（例如 1MB = 1024 * 1024 字节）[cite: 1, 2]
        MAX_CHANNELS_PER_FILE = 500  
        MAX_SIZE_BYTES = 1 * 1024 * 1024  # 1MB 目标大小[cite: 1, 2]

        for ext, items in ext_groups.items():
            ext_name = ext.lstrip('.')
            items.sort(key=lambda x: x['group'])

            file_index = 1
            current_channels = []
            current_size = 0

            def write_chunk(channels, idx):
                output_filename = f"{ext_name}_playlist_part{idx}.m3u"
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for item in channels:
                        inf_line = f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n'
                        url_line = f"{item['url']}\n"
                        f.write(inf_line)
                        f.write(url_line)
                print(f"已生成子播放列表: {output_filename} (包含 {len(channels)} 个资源)")

            for item in items:
                # 预估当前条目写入的字符/字节数 (#EXTINF行 + URL行)[cite: 1, 2]
                entry_str = f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n{item["url"]}\n'
                entry_size = len(entry_str.encode('utf-8'))

                # 检查是否达到拆分条件（超频道数 或 超 1M 大小）[cite: 1, 2]
                if len(current_channels) >= MAX_CHANNELS_PER_FILE or (current_size + entry_size > MAX_SIZE_BYTES and current_channels):
                    write_chunk(current_channels, file_index)
                    file_index += 1
                    current_channels = []
                    current_size = 0

                current_channels.append(item)
                current_size += entry_size

            # 写入剩余的频道[cite: 1, 2]
            if current_channels:
                write_chunk(current_channels, file_index)

        print(f"\n任务圆满结束，总有效资源: {len(all_items)}")
    else:
        print("任务结束，未找到任何有效视频。")

if __name__ == "__main__":
    main()
