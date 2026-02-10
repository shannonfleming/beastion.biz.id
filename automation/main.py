import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import pytz 
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps # Ditambah ImageOps
from groq import Groq, APIError, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# 1. API KEYS
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# 2. TIM PENULIS
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", "Ben Foster (Sports Journalist)"
]

# 3. KATEGORI
VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
]

# 4. RSS SOURCES
RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "US Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
    "UK Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-GB&gl=GB&ceid=GB:en"
}

# 5. DIRECTORIES
CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# ==========================================
# 📸 POOL GAMBAR (ANTI DUPLIKAT)
# ==========================================
# Setiap keyword punya BANYAK pilihan gambar.
# Script akan memilih salah satu secara acak.

KEYWORD_IMAGE_POOL = {
    "arsenal": [
        "https://images.unsplash.com/photo-1575361204480-aadea25e6e68",
        "https://images.unsplash.com/photo-1494195159496-5d2f6233d6b6",
        "https://images.unsplash.com/photo-1516246844974-e39556ee0945"
    ],
    "chelsea": [
        "https://images.unsplash.com/photo-1627341852895-467406c55cc0", 
        "https://images.unsplash.com/photo-1594476664275-c7216c5b078e",
        "https://images.unsplash.com/photo-1605634352771-419b4b045353"
    ],
    "liverpool": [
        "https://images.unsplash.com/photo-1636232707255-08cc5a65383f",
        "https://images.unsplash.com/photo-1626025437642-0b05076ca301",
        "https://images.unsplash.com/photo-1611004183864-1698f1f54497"
    ],
    "man city": [
        "https://images.unsplash.com/photo-1636125015306-03738a9d18b6",
        "https://images.unsplash.com/photo-1616428666355-66236314f852",
        "https://images.unsplash.com/photo-1574629810360-7efbbe195018"
    ],
    "man utd": [
        "https://images.unsplash.com/photo-1605218427306-633ba87c9759",
        "https://images.unsplash.com/photo-1628891544265-2766863640b3",
        "https://images.unsplash.com/photo-1518605348408-8df3d2b45281"
    ],
    "real madrid": [
        "https://images.unsplash.com/photo-1551958219-acbc608c6377",
        "https://images.unsplash.com/photo-1563402778942-1e967df2140b"
    ],
    "barcelona": [
        "https://images.unsplash.com/photo-1543796076-bb4d48d0a87a",
        "https://images.unsplash.com/photo-1558602781-325b5971c975"
    ],
    "generic": [
        "https://images.unsplash.com/photo-1522778119026-d647f0565c6a", 
        "https://images.unsplash.com/photo-1489944440615-453fc2b6a9a9", 
        "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d", 
        "https://images.unsplash.com/photo-1579952363873-27f3bde9be2b", 
        "https://images.unsplash.com/photo-1518091043644-c1d4457512c6"
    ]
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
]

# ==========================================
# 🧠 MEMORY & LINKING
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/articles/{slug}" 
    if len(memory) > 200: memory = dict(list(memory.items())[-200:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    count = min(5, len(items))
    selected_items = random.sample(items, count)
    links_md = ""
    for title, url in selected_items:
        links_md += f"- [{title}]({url})\n"
    return links_md

def inject_links_in_middle(content_body, links_markdown):
    if not links_markdown: return content_body
    injection_block = f"""\n\n> **🔥 RECOMMENDED FOR YOU:**\n>\n{"> " + links_markdown.replace("- ", "> - ")}\n\n"""
    content_body = content_body.replace("\r\n", "\n")
    paragraphs = content_body.split('\n\n')
    if len(paragraphs) < 3: return content_body + injection_block
    target_index = int(len(paragraphs) * 0.4)
    while target_index < len(paragraphs) and paragraphs[target_index].strip().startswith("#"):
        target_index += 1
    paragraphs.insert(target_index, injection_block)
    return '\n\n'.join(paragraphs)

# ==========================================
# 📡 RSS & INDEXING
# ==========================================
def fetch_rss_feed(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        return feedparser.parse(response.content)
    except: return None

def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {"host": host, "key": INDEXNOW_KEY, "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt", "urlList": [url]}
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'}, timeout=5)
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception: pass

# ==========================================
# 🎨 UNIQUE IMAGE GENERATOR (FLIP + FILTER)
# ==========================================
def download_and_make_unique(url, filename):
    try:
        # 1. Download Gambar
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        
        # Tambahkan parameter Unsplash agar dapat versi HD
        if "unsplash" in url and "?" not in url:
            url += "?auto=format&fit=crop&w=1200&q=80"
            
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            if len(response.content) < 5000: return False # Skip file corrupt/error kecil
            
            img = Image.open(BytesIO(response.content)).convert("RGB")
            
            # ----------------------------------------------------
            # TEKNIK 1: MIRRORING (Flip Horizontal secara acak)
            # ----------------------------------------------------
            # 50% kemungkinan gambar akan dibalik.
            # Ini membuat Google menganggapnya sebagai gambar baru.
            if random.random() > 0.5:
                img = ImageOps.mirror(img)
                print("      🎨 Applied: Image Flipping (Unique)")

            # ----------------------------------------------------
            # TEKNIK 2: RANDOM COLOR GRADING (Visual Noise)
            # ----------------------------------------------------
            # Ubah contrast sedikit (antara 0.9 sampai 1.2)
            contrast_factor = random.uniform(0.9, 1.2)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(contrast_factor)
            
            # Ubah brightness sedikit (antara 0.95 sampai 1.05)
            brightness_factor = random.uniform(0.95, 1.05)
            enhancer_b = ImageEnhance.Brightness(img)
            img = enhancer_b.enhance(brightness_factor)

            # Resize standar
            img.thumbnail((1200, 1200))
            
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=85)
            return True
            
    except Exception as e:
        print(f"      ⚠️ Image Error: {e}")
        return False
    return False

def get_unique_image(title, keyword, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"
    
    title_lower = title.lower()
    selected_url = None
    
    # 1. Cari Keyword di Title
    for key, url_list in KEYWORD_IMAGE_POOL.items():
        if key in title_lower:
            # TEKNIK 3: POOLING (Pilih 1 dari banyak opsi)
            selected_url = random.choice(url_list)
            print(f"      📸 Matched Pool: '{key}'")
            break
            
    # 2. Jika tidak ada di title, cek keyword dari AI
    if not selected_url and keyword:
        kw_lower = keyword.lower()
        if kw_lower in KEYWORD_IMAGE_POOL:
            selected_url = random.choice(KEYWORD_IMAGE_POOL[kw_lower])

    # 3. Fallback Generic
    if not selected_url:
        print("      ⚠️ Using Generic Pool")
        selected_url = random.choice(KEYWORD_IMAGE_POOL["generic"])
    
    # 4. Download & Modifikasi
    if download_and_make_unique(selected_url, filename):
        return f"/images/{filename}"
        
    return selected_url # Fallback URL mentah jika download gagal

# ==========================================
# 🧠 CONTENT ENGINE
# ==========================================
def get_article_blueprint(title, summary):
    text = (title + " " + summary).lower()
    if any(x in text for x in ['transfer', 'sign', 'bid', 'fee', 'contract']):
        return "TRANSFER_SAGA", "**SECTION 1: FINANCIALS**\n- H2: Cost Analysis\n- H3: Wages Table (Markdown)\n**SECTION 2: PLAYER**\n- H2: Skills\n**SECTION 3: TACTICS**\n- H2: Fit\n**SECTION 4: VERDICT**\n- H2: Rating"
    elif any(x in text for x in ['vs', 'win', 'loss', 'score']):
        return "MATCH_DEEP_DIVE", "**SECTION 1: STORY**\n- H2: Narrative\n**SECTION 2: TACTICS**\n- H2: Battle\n**SECTION 3: MOMENTS**\n- H2: Turning Point\n**SECTION 4: STATS**\n- H2: Data Table"
    else:
        return "EDITORIAL_FEATURE", "**SECTION 1: CONTEXT**\n- H2: Background\n**SECTION 2: ANALYSIS**\n- H2: Deep Dive (Table)\n**SECTION 3: REACTION**\n- H2: Opinion\n**SECTION 4: FUTURE**\n- H2: Impact"

def clean_json_response(content):
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*$', '', content)
    return content.strip()

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    blueprint_type, blueprint_structure = get_article_blueprint(title, summary)
    
    system_prompt = f"""
    You are {author_name}, a sports journalist. DATE: {current_date}.
    Write a 1500-WORD Article. VALID JSON Output.
    NO Generic Headers (Section 1 etc). Make H2/H3 creative.
    Structure: {blueprint_structure}
    JSON: {{ "title": "Headline", "description": "SEO Desc", "category": "Category", "main_keyword": "Entity", "tags": [], "content_body": "Markdown" }}
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Topic: {title}\nDetails: {summary}\nLink: {link}"}],
                temperature=0.75, max_tokens=8000, response_format={"type": "json_object"}
            )
            return clean_json_response(completion.choices[0].message.content)
        except Exception: time.sleep(2)
    return None

# ==========================================
# 🏁 MAIN
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"🔥 STARTING ENGINE (UNIQUE IMAGE MODE)...")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Source: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        cat_count = 0
        for entry in feed.entries:
            if cat_count >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            print(f"   ⚡ {clean_title[:30]}...")
            
            # 1. Text
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, random.choice(AUTHOR_PROFILES))
            if not raw_json: continue
            try: data = json.loads(raw_json)
            except: continue

            # 2. Unique Image
            keyword = data.get('main_keyword') or clean_title
            final_img = get_unique_image(clean_title, keyword, f"{slug}.webp")
            
            # 3. Links
            links_md = get_internal_links_markdown()
            final_body = inject_links_in_middle(data['content_body'], links_md)
            
            # 4. Save
            is_featured = "true" if random.random() > 0.7 else "false"
            if data.get('category') not in VALID_CATEGORIES: data['category'] = "International"
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{data.get('author', 'Editor')}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
featured: {is_featured}
weight: {random.randint(1, 10)}
---

{final_body}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md_content)
            save_link_to_memory(data['title'], slug)
            
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            print(f"      ✅ DONE: {filename}")
            
            cat_count += 1
            time.sleep(3)

if __name__ == "__main__":
    main()
