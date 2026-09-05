import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

SOURCES_FILE = "sources.txt"
OUTPUT_M3U = "playlist.m3u"

# 支持的视频格式后缀
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.m3u8', '.ts', '.mov', '.avi', '.flv', '.webm')

def parse_directory_listing(base_url):
    """访问目录列表页面，递归或直接提取所有视频文件链接"""
    media_items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        # 忽略 SSL 证书报错（针对部分自签名的测试/IP服务器）
        response = requests.get(base_url, headers=headers, timeout=6, verify=False)
        if response.status_code != 200:
            return media_items
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 遍历页面中所有的超链接 <a> 标签
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # 排除父目录跳转链接
            if href.startswith('?') or href == '../' or href == './' or not href.strip():
                continue
                
            # 拼接出视频文件的绝对直链
            absolute_url = urljoin(base_url, href)
            
            # 检查链接是否以常见视频格式结尾（忽略大小写）
            parsed_path = urlparse(absolute_url).path.lower()
            if parsed_path.endswith(VIDEO_EXTENSIONS):
                # 提取纯文件名作为显示名称
                file_name = os.path.basename(parsed_path)
                # 顺便把上级目录或服务器简写带上，方便在手机里区分来源
                domain_prefix = urlparse(base_url).netloc
                
                media_items.append({
                    "name": f"[{domain_prefix}] {file_name}",
                    "url": absolute_url
                })
                
    except Exception as e:
        print(f"解析出错 {base_url}: {e}")
        
    return media_items

def main():
    if not os.path.exists(SOURCES_FILE):
        print(f"未找到源文件: {SOURCES_FILE}")
        return
        
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    all_items = []
    for line in lines:
        url = line.strip()
        if not url or url.startswith("#"):
            continue
            
        print(正在抓取目录: {url})
        items = parse_directory_listing(url)
        all_items.extend(items)
        
    # 生成标准的 M3U 播放列表
    m3u_content = "#EXTM3U\n"
    for item in all_items:
        m3u_content += f"#EXTINF:-1,{item['name']}\n"
        m3u_content += f"{item['url']}\n"
        
    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write(m3u_content)
        
    print(f"成功生成播放列表: {OUTPUT_M3U}，共收录 {len(all_items)} 个视频文件。")

if __name__ == "__main__":
    # 关闭 requests 的自签名证书警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
