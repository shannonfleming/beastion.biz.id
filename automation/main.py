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

# 6. STOK FOTO CADANGAN (JIKA AI ERROR, PAKAI INI SUPAYA TETAP BAGUS)
BACKUP_REAL_PHOTOS = [
    "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80", # Stadium
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80", # Goal net
    "https://images.unsplash.com/photo-1579952363873-27f3bde9be2b?auto=format&fit=crop&w=1200&q=80", # Soccer ball
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80", # Fans
    "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?auto=format&fit=crop&w=1200&q=80", # Player kick
    "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1200&q=80", # Generic Football
    "https://images.unsplash.com/photo-1556056504-5c7696c4c28d?auto=format&fit=crop&w=1200&q=80", # Boots
    "https://images.unsplash.com/photo-1518091043644-c1d4457512c6?auto=format&fit=crop&w=1200&q=80", # Crowd
    "https://images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80", # Soccer Field
    "https://images.unsplash.com/photo-1624880357913-a8539238245b?auto=format&fit=crop&w=1200&q=80"  # Red Jersey
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
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
    memory[title] = f"/articles/{slug}" 
    if len(memory) > 200: 
        memory = dict(list(memory.items())[-200:])
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
    
    injection_block = f"""
\n\n
> **🔥 RECOMMENDED FOR YOU:**
>
{"> " + links_markdown.replace("- ", "> - ")}
\n\n
"""
    content_body = content_body.replace("\r\n", "\n")
    paragraphs = content_body.split('\n\n')
    
    if len(paragraphs) < 3:
        return content_body + injection_block
        
    target_index = int(len(paragraphs) * 0.4)
    while target_index < len(paragraphs) and paragraphs[target_index].strip().startswith("#"):
        target_index += 1
        
    paragraphs.insert(target_index, injection_block)
    return '\n\n'.join(paragraphs)

# ==========================================
# 📡 INDEXING & RSS TOOLS
# ==========================================
def fetch_rss_feed(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
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
    except Exception: pass

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
    except: pass

# ==========================================
# 🎨 SMART IMAGE ENGINE (AI + ROBUST FALLBACK)
# ==========================================
def download_image_from_url(url, filename):
    """Fungsi helper untuk download dan optimize gambar"""
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            # Cek ukuran file. Jika < 5KB, kemungkinan itu gambar error placeholder
            if len(response.content) < 5000: 
                return False
                
            img = Image.open(BytesIO(response.content)).convert("RGB")
            # Resize agar ringan tapi tajam
            img.thumbnail((1200, 1200)) 
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)
            
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=85)
            return True
    except Exception as e:
        print(f"      ⚠️ Image Download Error: {e}")
        return False
    return False

def get_best_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"
    
    print(f"      🎨 Processing Image for: {query[:30]}...")
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query)
    
    # 1. COBA AI (POLLINATIONS) - Dengan Model 'Flux' (Paling stabil)
    seed = random.randint(1, 999999)
    # Gunakan prompt yang sangat spesifik
    prompt = f"cinematic sports photography, {clean_query}, premiere league stadium background, dynamic lighting, 4k, realistic, no text"
    safe_prompt = prompt.replace(" ", "%20")
    
    ai_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&nologo=true&model=flux&seed={seed}"
    
    # Coba download AI
    if download_image_from_url(ai_url, filename):
        return f"/images/{filename}"
    
    print("      ⚠️ AI Image Failed/Rate Limited. Switching to HD Backup...")
    
    # 2. JIKA AI GAGAL -> PAKAI STOK FOTO ASLI (Random)
    # Ini memastikan website TIDAK PERNAH tampil jelek
    backup_url = random.choice(BACKUP_REAL_PHOTOS)
    
    # Coba download Backup
    if download_image_from_url(backup_url, filename):
         return f"/images/{filename}"
         
    # 3. Last Resort (Kalau internet parah banget)
    return backup_url

# ==========================================
# 🧠 MEGA-PROMPT ENGINE
# ==========================================
def get_article_blueprint(title, summary):
    text = (title + " " + summary).lower()
    if any(x in text for x in ['transfer', 'sign', 'bid', 'fee', 'contract']):
        return "TRANSFER_SAGA", """
        **SECTION 1 GUIDE: FINANCIALS**
        - H2 Requirement: Unique headline about Money/Cost.
          - H3: Wages/Fee breakdown (Markdown Table Required).
          - H3: Contract clauses.
        **SECTION 2 GUIDE: ANALYSIS**
        - H2 Requirement: Unique headline about Skills.
          - H3: Strengths analysis.
          - H3: Weaknesses.
        **SECTION 3 GUIDE: TACTICS**
        - H2 Requirement: Unique headline about Team Fit.
          - H3: Manager's plan.
        **SECTION 4 GUIDE: VERDICT**
        - H2 Requirement: Unique closing headline.
          - H3: Final rating.
        """
    elif any(x in text for x in ['vs', 'win', 'loss', 'score', 'highlight']):
        return "MATCH_DEEP_DIVE", """
        **SECTION 1 GUIDE: NARRATIVE**
        - H2 Requirement: Dramatic match headline.
          - H3: Context vs Reality.
        **SECTION 2 GUIDE: TACTICS**
        - H2 Requirement: Unique tactical battle headline.
          - H3: Midfield/Defense analysis.
        **SECTION 3 GUIDE: KEY MOMENTS**
        - H2 Requirement: Turning point headline.
          - H3: Goals/VAR.
        **SECTION 4 GUIDE: DATA**
        - H2 Requirement: Stats headline.
          - H3: Ratings Table (Markdown).
        """
    else:
        return "EDITORIAL_FEATURE", """
        **SECTION 1 GUIDE: CONTEXT**
        - H2 Requirement: History/Background headline.
          - H3: Timeline.
        **SECTION 2 GUIDE: DEEP DIVE**
        - H2 Requirement: Core issue headline.
          - H3: Data/Facts (Table Required).
        **SECTION 3 GUIDE: OPINION**
        - H2 Requirement: Reaction headline.
          - H3: Fans/Experts view.
        **SECTION 4 GUIDE: FUTURE**
        - H2 Requirement: Prediction headline.
          - H3: Impact.
        """

def clean_json_response(content):
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*$', '', content)
    return content.strip()

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    blueprint_type, blueprint_structure = get_article_blueprint(title, summary)
    
    system_prompt = f"""
    You are {author_name}, a senior sports journalist.
    DATE: {current_date}.
    MISSION: Write a 1500-WORD Deep Dive. Output VALID JSON.
    
    ⛔ FORBIDDEN WORDS IN HEADERS:
    - "Section", "Introduction", "Conclusion", "Verdict", "Analysis".
    
    ✅ MANDATORY HEADER RULES:
    - Every H2 and H3 must be creative, specific, and catchy.
    
    STRUCTURE GUIDE:
    {blueprint_structure}
    
    JSON OUTPUT FORMAT:
    {{
        "title": "Viral Headline",
        "description": "SEO Description",
        "category": "Pick one: Transfer News, Premier League, Champions League, La Liga, International, Tactical Analysis",
        "main_keyword": "Entity for image",
        "tags": ["tag1", "tag2"],
        "content_body": "Full Markdown content with UNIQUE H2/H3 headers."
    }}
    """
    user_prompt = f"TOPIC: {title}\nDETAILS: {summary}\nSOURCE: {link}\nExecute the blueprint."

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.75, max_tokens=8000, response_format={"type": "json_object"}
            )
            return clean_json_response(completion.choices[0].message.content)
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            time.sleep(3)
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
    print(f"🔥 STARTING ENGINE (Robust Images & Fixed Folder)...")

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
            
            # 1. GENERATE TEXT
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, current_author)
            if not raw_json: continue
            try: data = json.loads(raw_json)
            except: continue

            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 2. GENERATE IMAGE (ROBUST MODE)
            img_name = f"{slug}.webp"
            keyword = data.get('main_keyword') or clean_title
            final_img = get_best_image(keyword, img_name)
            
            # 3. INJECT LINKS
            links_md = get_internal_links_markdown()
            final_body = inject_links_in_middle(data['content_body'], links_md)

            # 4. SAVE (WITH FEATURED PARAM)
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            
            # Tambahkan featured: true secara acak agar homepage tidak bosan
            is_featured = "true" if random.random() > 0.7 else "false"
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {date_now}
author: "{current_author.split('(')[0].strip()}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
featured_image_alt: "{keyword}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
featured: {is_featured}
weight: {random.randint(1, 10)}
---

{final_body}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}). Content generated for informational purposes.*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            print(f"      ✅ Published: {CONTENT_DIR}/{filename}")
            
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            time.sleep(5)

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
