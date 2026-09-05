import os
import requests
import random
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

def is_url_valid(url, session):
    """通过 HEAD/GET 请求验证 URL 是否有效"""
    try:
        response = session.head(url, headers=HEADERS, timeout=5, verify=False, allow_redirects=True)
        if response.status_code == 200:
            return True
    except Exception:
        pass
    
    try:
        response = session.get(url, headers=HEADERS, timeout=5, verify=False, stream=True)
        return response.status_code == 200
    except Exception:
        return False

def parse_site(base_url, max_depth=3):
    """单站点深度递归抓取逻辑（仅收集候选链接，不在此阶段做网络验证）"""
    visited_dirs = set()
    candidate_urls = set()
    session = requests.Session()

    def recursive_crawl(current_url, depth):
        if depth > max_depth:
            return
        
        clean_url = current_url.rstrip('/') + '/'
        if clean_url in visited_dirs:
            return
        visited_dirs.add(clean_url)

        time.sleep(random.uniform(0.3, 0.8))

        try:
            response = session.get(current_url, headers=HEADERS, timeout=10, verify=False)
            if response.status_code != 200:
                return
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                
                if not href or any(x in href.lower() for x in ['?c=', '?n=', '?s=', '?d=', '../', './']):
                    continue
                if href.startswith(('mailto:', 'javascript:', '#')):
                    continue

                absolute_url = urljoin(current_url, href)
                parsed = urlparse(absolute_url)
                path_lower = parsed.path.lower()

                is_dir = href.endswith('/') or ('.' not in os.path.basename(path_lower) and not path_lower.endswith(VIDEO_EXTENSIONS))

                if is_dir:
                    skip_keywords = ['login', 'etc', 'bin', 'search', 'style', 'assets', 'admin']
                    if not any(k in path_lower for k in skip_keywords):
                        recursive_crawl(absolute_url, depth + 1)
                elif path_lower.endswith(VIDEO_EXTENSIONS):
                    candidate_urls.add(absolute_url)
        except Exception:
            pass

    recursive_crawl(base_url, 1)
    return base_url, list(candidate_urls)

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"错误: 未找到源文件 {SOURCES_FILE}")
        return

    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    all_items = []
    seen_urls = set()

    print(f"开始任务，并发线程数: {MAX_THREADS}")
    print("阶段一：并发抓取并收集所有候选视频链接...")

    site_candidates = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(parse_site, url, 3): url for url in urls}
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                base_url, candidates = future.result()
                site_candidates[base_url] = candidates
                print(f"抓取完成: {base_url} (发现候选视频: {len(candidates)} 条)")
            except Exception as e:
                print(f"抓取失败: {url} 错误: {e}")

    print("\n阶段二：并发验证视频链接存活性...")
    session = requests.Session()
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS * 2) as executor:
        future_to_item = {}
        for base_url, candidates in site_candidates.items():
            domain = urlparse(base_url).netloc
            for cand_url in candidates:
                if cand_url not in seen_urls:
                    seen_urls.add(cand_url)
                    future = executor.submit(is_url_valid, cand_url, session)
                    future_to_item[future] = (domain, cand_url)

        valid_count = 0
        for future in as_completed(future_to_item):
            domain, cand_url = future_to_item[future]
            try:
                if future.result():
                    file_name = get_clean_filename(cand_url)
                    if len(file_name) > 3:
                        all_items.append({
                            "name": f"[{domain}] {file_name}",
                            "url": cand_url,
                            "group": domain
                        })
                        valid_count += 1
            except Exception:
                pass

    if all_items:
        with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for item in all_items:
                f.write(f'#EXTINF:-1 group-title="{item["group"]}",{item["name"]}\n')
                f.write(f"{item['url']}\n")
        print(f"\n任务圆满结束，共成功收集并验证了 {len(all_items)} 个有效视频资源。")
        print(f"结果已保存至: {OUTPUT_M3U}")
    else:
        print("\n任务结束，未找到任何有效的视频资源。")

if __name__ == "__main__":
    main()
