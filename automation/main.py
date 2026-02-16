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
from PIL import Image
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
    # print("⚠️ Google Indexing Libs not found.") 

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# API KEYS
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# WEBSITE CONFIG
WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# CHECK KEYS
if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# AUTHOR DATABASE
AUTHOR_PROFILES = [
    "Dave Harsya (Tactical Analyst)", "Sarah Jenkins (Senior Editor)",
    "Luca Romano (Market Expert)", "Marcus Reynolds (League Correspondent)",
    "Ben Foster (Data Journalist)"
]

# CATEGORY LIST
VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
]

# RSS FEEDS
RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "The Guardian": "https://www.theguardian.com/football/rss"
}

# DIRECTORIES
CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# ==========================================
# 🧠 HELPER FUNCTIONS
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

def clean_ai_content(text):
    if not text: return ""
    text = re.sub(r'^```[a-zA-Z]*\n', '', text)
    text = re.sub(r'\n```$', '', text)
    text = text.replace("```", "")
    text = text.replace("<h1>", "# ").replace("</h1>", "\n")
    text = text.replace("<h2>", "## ").replace("</h2>", "\n")
    text = text.replace("<h3>", "### ").replace("</h3>", "\n")
    text = text.replace("<b>", "**").replace("</b>", "**")
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
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=10)
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
# 🎨 MULTI-PROVIDER AI IMAGE GENERATOR
# ==========================================
def generate_ai_image(prompt, filename):
    """
    Sistem Multi-Layer untuk menghindari Error 530 (IP Block).
    1. Pollinations (Flux)
    2. Hercai (Backup Server)
    3. Default Image
    """
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # Perkaya Prompt
    clean_prompt = prompt.replace('"', '').replace("'", "").strip()
    enhanced_prompt = f"{clean_prompt}, football match action, dynamic angle, 8k resolution, photorealistic, cinematic lighting, highly detailed texture, sports photography"
    encoded_prompt = requests.utils.quote(enhanced_prompt)
    seed = random.randint(1, 9999999)

    # --- PROVIDER 1: POLLINATIONS (FLUX) ---
    url_pollinations = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&model=flux&seed={seed}&nologo=true&enhance=true"
    
    # Headers "Paranoid" agar terlihat seperti Chrome asli
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://pollinations.ai/",
        "Origin": "https://pollinations.ai",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }

    print(f"      🎨 Generating Image...")
    
    # ATTEMPT 1: Pollinations
    try:
        resp = requests.get(url_pollinations, headers=headers, timeout=25)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.save(output_path, "WEBP", quality=90)
            print("      ✅ Image Saved (Provider: Pollinations)")
            return f"/images/{filename}"
        else:
            print(f"      ⚠️ Pollinations Refused ({resp.status_code}). Switching to backup...")
    except Exception:
        print("      ⚠️ Pollinations Timeout. Switching to backup...")

    # ATTEMPT 2: HERCAI (BACKUP PROVIDER - BEDA SERVER)
    # API ini jarang memblokir GitHub
    try:
        print("      🔄 Trying Backup Provider (Hercai)...")
        # Menggunakan model v3 (prodia/realism)
        hercai_url = f"https://hercai.onrender.com/v3/text2image?prompt={encoded_prompt}"
        resp_hercai = requests.get(hercai_url, headers=headers, timeout=30)
        
        if resp_hercai.status_code == 200:
            json_data = resp_hercai.json()
            if "url" in json_data:
                image_url = json_data["url"]
                # Download gambar dari URL hasil Hercai
                img_data = requests.get(image_url, headers=headers, timeout=20).content
                img = Image.open(BytesIO(img_data)).convert("RGB")
                img.save(output_path, "WEBP", quality=90)
                print("      ✅ Image Saved (Provider: Hercai)")
                return f"/images/{filename}"
    except Exception as e:
        print(f"      ⚠️ Backup Provider Failed: {e}")

    # FINAL FALLBACK: Default Image
    # Pastikan file 'default-football.webp' ada di folder static/images/
    print("      ⚠️ All AI Generators failed. Using Default.")
    return "/images/default-football.webp"

# ==========================================
# 🧠 CONTENT ENGINE
# ==========================================

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a professional sports journalist.
    CURRENT DATE: {current_date}.
    
    OBJECTIVE: Write a high-quality, 800-word analysis article.
    
    OUTPUT FORMAT:
    JSON Object keys: "title", "description", "category", "main_keyword", "tags", "content_body".
    "main_keyword" MUST be a visual description for an image generator (e.g., "Mo Salah celebrating goal at Anfield, wide angle").
    """
    
    user_prompt = f"""
    SOURCE:
    - Headline: {title}
    - Summary: {summary}
    - Link: {link}
    
    TASK: Write the article now using MARKDOWN.
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
                max_tokens=6000,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Rate Limit Hit, switching key...")
            time.sleep(2)
        except Exception: pass
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 ENGINE STARTED: MULTI-PROVIDER MODE")

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
            
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parse Error")
                continue

            # Generate Image (Dengan Backup System)
            image_prompt = data.get('main_keyword', clean_title)
            final_img_path = generate_ai_image(image_prompt, f"{slug}.webp")
            
            # Clean & Save
            clean_body = clean_ai_content(data['content_body'])
            links_md = get_internal_links_markdown()
            final_body = clean_body + "\n\n### Read More\n" + links_md
            
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img_path}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
url: "/{slug}/"
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
            
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
