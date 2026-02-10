import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import string
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
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
    print("⚠️ Google Indexing Libs not found. Install: pip install google-api-python-client oauth2client")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# TIM PENULIS
AUTHOR_PROFILES = [
    "Dave Harsya (Tactical Analyst)", "Sarah Jenkins (Senior Editor)",
    "Luca Romano (Market Expert)", "Marcus Reynolds (League Correspondent)",
    "Ben Foster (Data Journalist)"
]

VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
]

RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "The Guardian": "https://www.theguardian.com/football/rss"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# Unsplash ID Pool
UNSPLASH_IDS = [
    "1522778119026-d647f0565c6a", "1489944440615-453fc2b6a9a9", "1431324155629-1a6deb1dec8d", 
    "1579952363873-27f3bde9be2b", "1518091043644-c1d4457512c6", "1508098682722-e99c43a406b2",
    "1574629810360-7efbbe195018", "1577223625816-7546f13df25d", "1624880357913-a85cbdec04ca"
]

# ==========================================
# 🧠 HELPER FUNCTIONS (CLEANER ADDED)
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
    count = min(4, len(items))
    selected_items = random.sample(items, count)
    return "\n".join([f"- [{title}]({url})" for title, url in selected_items])

def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

# --- NEW CLEANER FUNCTION ---
def clean_ai_content(text):
    """Membersihkan output AI dari wrapper code block dan tag HTML yang tidak perlu"""
    if not text: return ""
    
    # 1. Hapus wrapper ```html atau ```markdown
    text = re.sub(r'^```[a-zA-Z]*\n', '', text) # Hapus pembuka ```html
    text = re.sub(r'\n```$', '', text)          # Hapus penutup ```
    text = text.replace("```", "")              # Hapus sisa backticks
    
    # 2. Hapus tag HTML dasar jika AI bandel pakai HTML (Convert ke Markdown sederhana)
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<strong>", "**").replace("</strong>", "**")
    text = text.replace("<i>", "*").replace("</i>", "*")
    text = text.replace("<p>", "").replace("</p>", "\n\n")
    
    return text.strip()

# ==========================================
# 🚀 INDEXING FUNCTIONS
# ==========================================
def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=5)
        print(f"      🚀 IndexNow Submitted")
    except Exception as e:
        print(f"      ⚠️ IndexNow Failed: {e}")

def submit_to_google(url):
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

# ==========================================
# 🎨 HYBRID IMAGE ENGINE
# ==========================================
def apply_heavy_modification(img):
    if random.random() > 0.5:
        img = ImageOps.mirror(img)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(random.uniform(0.85, 1.25)) 
    enhancer_c = ImageEnhance.Contrast(img)
    img = enhancer_c.enhance(random.uniform(0.9, 1.1))
    
    width, height = img.size
    vignette = Image.new('L', (width, height), 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(vignette)
    draw.ellipse((30, 30, width-30, height-30), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(100))
    img = ImageOps.colorize(vignette, (10, 10, 10), (255, 255, 255)) 
    return img.resize((1200, 675), Image.Resampling.LANCZOS)

def generate_hybrid_image(query, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    print(f"      🎨 Strategy 1: AI Generating '{query}'...")
    safe_prompt = f"editorial sports photography of {query}, football match action, stadium atmosphere, 4k, hyper-realistic --ar 16:9".replace(" ", "%20")
    seed = random.randint(1, 1000000)
    ai_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&model=flux-realism&seed={seed}&nologo=true"
    
    try:
        resp = requests.get(ai_url, timeout=40)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.3)
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ AI Image Created!")
            return f"/images/{filename}"
    except:
        print(f"      ⚠️ AI Failed. Switching to Backup.")

    print("      🎨 Strategy 2: Unsplash Pool + Modding")
    selected_id = random.choice(UNSPLASH_IDS)
    unsplash_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
    
    try:
        resp = requests.get(unsplash_url, timeout=15)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img = apply_heavy_modification(img)
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Backup Image Saved!")
            return f"/images/{filename}"
    except: pass
    
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a"

# ==========================================
# 🧠 QUALITY CONTENT ENGINE (ANTI-HTML)
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # SYSTEM PROMPT: PENEGASAN MARKDOWN ONLY
    system_prompt = f"""
    You are {author_name}, a strict and professional sports journalist.
    CURRENT DATE: {current_date}.
    
    OBJECTIVE: Write a high-quality, 1000-word analysis article.
    
    🛑 FORMATTING RULES (CRITICAL):
    1. **USE PURE MARKDOWN ONLY.**
    2. **DO NOT USE HTML TAGS.** (NO <table>, NO <p>, NO <h2>).
    3. Use hashtags (#) for headers.
    4. Use standard markdown for tables (| Col | Col |).
    5. Do NOT wrap the content in a code block (```).
    
    🛑 ANTI-HALLUCINATION:
    1. If match is future -> PREVIEW.
    2. No fake quotes.
    
    OUTPUT FORMAT:
    JSON Object keys: "title", "description", "category", "main_keyword", "tags", "content_body".
    """
    
    user_prompt = f"""
    SOURCE MATERIAL:
    - Headline: {title}
    - Summary: {summary}
    - Source Link: {link}
    
    TASK: Write the article now using MARKDOWN SYNTAX only.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError: time.sleep(3)
        except Exception: pass
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 ENGINE STARTED: ANTI-HTML + CLEANER MODE")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. Content Generation
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parse Error")
                continue

            # 2. Image Generation
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_hybrid_image(keyword, f"{slug}.webp")
            
            # 3. CLEANING & FORMATTING (INI PENTING)
            # Membersihkan tag HTML/Code Block jika AI bandel
            clean_body = clean_ai_content(data['content_body'])
            
            links_md = get_internal_links_markdown()
            final_body = clean_body + "\n\n### Read More\n" + links_md
            
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # Create Markdown
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
weight: {random.randint(1, 10)}
---

{final_body}

---
*Reference: Analysis by {author} based on reports from [{source_name}]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # 4. Submit Indexing
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
