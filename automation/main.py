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
from PIL import Image, ImageEnhance
from groq import Groq, APIError, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    print("⚠️ Warning: Google Indexing libs not installed. Running without Google Indexing.")
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
    print("❌ FATAL ERROR: Groq API Key is missing! Set 'GROQ_API_KEY' env variable.")
    exit(1)

# 2. TIM PENULIS (LENGKAP)
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", 
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", 
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", 
    "Ben Foster (Sports Journalist)",
    "Mateo Rodriguez (European Football Analyst)"
]

# 3. KATEGORI RESMI
VALID_CATEGORIES = [
    "Transfer News", 
    "Premier League", 
    "Champions League", 
    "La Liga", 
    "International", 
    "Tactical Analysis"
]

# 4. SUMBER RSS (LENGKAP SESUAI REQUEST)
RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "US Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
    "UK Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-GB&gl=GB&ceid=GB:en"
}

# 5. DIRECTORIES
CONTENT_DIR = "content/posts"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# 6. FALLBACK IMAGES
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

# ==========================================
# 🧠 MEMORY & LINKING SYSTEM
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}"
    # Simpan 100 link terakhir
    if len(memory) > 100: 
        memory = dict(list(memory.items())[-100:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    """Mengambil 3 link acak untuk disisipkan."""
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    
    selected_items = random.sample(items, min(3, len(items)))
    links_md = ""
    for title, url in selected_items:
        links_md += f"- [{title}]({url})\n"
    return links_md

def inject_links_in_middle(content_body, links_markdown):
    """
    LOGIC BARU: Menyisipkan link di PARAGRAF KE-3 (Tengah Artikel).
    """
    if not links_markdown: return content_body
    
    # Pecah artikel berdasarkan baris kosong (paragraf)
    paragraphs = content_body.split('\n\n')
    
    # Buat blok link yang rapi (Blockquote style agar menonjol)
    injection_block = f"""
> **Recommended for you:**
>
{"> " + links_markdown.replace("- ", "> - ")}
"""

    # Suntikkan di posisi strategis
    if len(paragraphs) > 5:
        paragraphs.insert(3, injection_block) # Insert setelah paragraf ke-3
    elif len(paragraphs) > 2:
        paragraphs.insert(1, injection_block) # Insert setelah paragraf ke-1 jika pendek
    else:
        paragraphs.append(injection_block) # Taruh bawah jika sangat pendek
        
    return '\n\n'.join(paragraphs)

# ==========================================
# 📡 INDEXING & RSS TOOLS
# ==========================================
def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        return feedparser.parse(response.content)
    except: return None

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
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'}, timeout=5)
        print(f"      🚀 IndexNow Submitted")
    except: pass

# ==========================================
# 🎨 IMAGE ENGINE (FLUX + ENHANCER)
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    base_prompt = f"sports press photography, {query}, realistic stadium background, 4k, canon eos r5, sharp focus, cinematic lighting, no text"
    safe_prompt = base_prompt.replace(" ", "%20")[:400]
    
    print(f"      🎨 Generating Image: {query[:30]}...")

    for attempt in range(2):
        seed = random.randint(1, 999999)
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&nologo=true&model=flux-realism&seed={seed}"
        
        try:
            response = requests.get(image_url, timeout=45)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                
                # Optimasi
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.3)
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1)

                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=85)
                
                print(f"      📸 Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception:
            time.sleep(2)
    
    print("      ⚠️ Image gen failed. Using Fallback.")
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🧠 AI LOGIC: DYNAMIC STRUCTURE (1000+ WORDS)
# ==========================================
def get_structure_instructions(title):
    """Menentukan Struktur Artikel Berdasarkan Judul"""
    t = title.lower()
    if any(x in t for x in ['transfer', 'bid', 'sign', 'fee', 'loan', 'contract']):
        return "TRANSFER_ANALYSIS", """
        - H2: The Financial Details (MUST include a Markdown Table of fees/wages)
        - H2: Where He Fits (Tactical Fit)
        - H2: The Ripple Effect on the Squad
        - H2: Verdict: Bust or Bargain?
        """
    elif any(x in t for x in ['vs', 'win', 'loss', 'score', 'highlight']):
        return "MATCH_DEEP_DIVE", """
        - H2: The Key Turning Point
        - H2: Tactical Battle (Manager vs Manager)
        - H2: Player Ratings & Stats (MUST include a Markdown Table)
        - H2: What This Means for the Season
        """
    else:
        return "EDITORIAL_FEATURE", """
        - H2: The Context You Missed
        - H2: Deep Data Dive (MUST include a Markdown Table)
        - H2: Historical Parallels
        - H2: Expert Conclusion
        """

def get_groq_article_json(title, summary, link, author_name):
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    style, specific_headers = get_structure_instructions(title)
    
    system_prompt = f"""
    You are {author_name}, a world-class sports journalist.
    TODAY'S DATE: {current_date}.
    
    YOUR MISSION: Write a **1200-WORD** Feature Article.
    STYLE: {style}.
    
    FORBIDDEN: Do NOT use generic headers like "Introduction", "Conclusion", "Summary".
    REQUIRED: Use these specific narrative angles:
    {specific_headers}
    
    ANTI-HOAX RULES:
    1. If event date > {current_date} -> Write PREVIEW.
    2. If event date <= {current_date} -> Write REPORT.
    3. Do NOT invent fake quotes.
    
    JSON FORMAT:
    {{
        "title": "Viral Headline (Max 65 chars, No Clickbait)",
        "description": "SEO Meta Description",
        "category": "Pick one: {', '.join(VALID_CATEGORIES)}",
        "main_keyword": "Entity for image gen",
        "tags": ["tag1", "tag2"],
        "content_body": "Full Markdown content..."
    }}
    """

    user_prompt = f"""
    TOPIC: {title}
    CONTEXT: {summary}
    SOURCE: {link}
    
    WRITING PLAN (TO ENSURE 1200 WORDS):
    1. **The Lead (250 words):** Hook the reader, set the high stakes.
    2. **The Context (300 words):** Background info, previous form.
    3. **The Deep Analysis (400 words):** Detailed tactical breakdown. MUST INCLUDE A MARKDOWN TABLE.
    4. **The Human Element (250 words):** Fan reactions, player body language.
    5. **The Verdict (150 words):** Strong closing opinion.
    
    IMPORTANT: Do NOT include a 'Read More' or 'Links' section. 
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7, 
                max_tokens=8000, 
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
            continue
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            continue
            
    return None

# ==========================================
# 🏁 MAIN LOOP
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0
    print("🔥 STARTING ENGINE (COMPLETE VERSION)...")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Fetching Source: {source_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_SOURCE: break

            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. GENERATE KONTEN (AI)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, current_author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except: 
                print("      ❌ JSON Error")
                continue

            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 2. GENERATE IMAGE
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
            # 3. INJECT LINKS DI TENGAH (PYTHON LOGIC)
            links_md = get_internal_links_markdown()
            final_body = inject_links_in_middle(data['content_body'], links_md)

            # 4. SAVE FILE
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_list = data.get('lsi_keywords', [])
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {date_now}
author: "{current_author.split('(')[0].strip()}"
categories: ["{data['category']}"]
tags: {json.dumps(tags_list)}
featured_image: "{final_img}"
featured_image_alt: "Image showing {data.get('main_keyword', 'Football Match')}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
---

{final_body}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}). Content generated for informational purposes.*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 5. MEMORY & INDEXING
            save_link_to_memory(data['title'], slug)
            
            print(f"      ✅ Published: {filename}")
            
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            
            time.sleep(8) # Istirahat agak lama agar AI tidak error

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
