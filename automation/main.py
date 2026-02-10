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
    print("⚠️ Warning: Google Indexing libs not installed.")
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

# 5. DIRECTORIES (SUDAH DIPERBAIKI KE 'articles')
# ⚠️ PENTING: Folder output disesuaikan dengan error log kamu
CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# 6. FALLBACK & USER AGENTS (UNTUK ANTI-LIMIT IMAGE)
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
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
    # Simpan dengan path folder yang benar
    memory[title] = f"/articles/{slug}" 
    if len(memory) > 200: 
        memory = dict(list(memory.items())[-200:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    memory = load_link_memory()
    items = list(memory.items())
    
    if not items: 
        return ""
        
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
    
    # Hindari memotong Header Markdown (#)
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
# 🎨 UNLIMITED IMAGE ENGINE (ANTI-LIMIT)
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query)
    models = ["flux", "flux-realism", "any-dark", "turbo"]
    
    print(f"      🎨 Generating Image: {query[:30]}...")

    for attempt in range(4):
        seed = random.randint(1, 999999999)
        model = random.choice(models)
        
        prompt_text = f"editorial sports photography, {clean_query}, stadium atmosphere, 4k, hyperrealistic, no text"
        safe_prompt = prompt_text.replace(" ", "%20")
        
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&nologo=true&model={model}&seed={seed}&enhance=true"
        
        try:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Referer': 'https://google.com'
            }
            
            response = requests.get(image_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.2)
                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=85)
                return f"/images/{filename}" 
            
        except Exception as e:
            time.sleep(1)
            
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🧠 MEGA-PROMPT ENGINE (UNIQUE HEADERS)
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

    user_prompt = f"""
    TOPIC: {title}
    DETAILS: {summary}
    SOURCE: {link}
    Execute the blueprint. Write extensively. Include a Table.
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
                temperature=0.75, 
                max_tokens=8000, 
                response_format={"type": "json_object"}
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
    # SETUP FOLDER (Memastikan folder 'content/articles' dibuat)
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0
    print(f"🔥 STARTING ENGINE (Output: {CONTENT_DIR})...")

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
            
            # 1. GENERATE
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, current_author)
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
            except: continue

            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 2. IMAGE
            img_name = f"{slug}.webp"
            keyword = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword, img_name)
            
            # 3. LINKS
            links_md = get_internal_links_markdown()
            final_body = inject_links_in_middle(data['content_body'], links_md)

            # 4. SAVE
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            
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
---

{final_body}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}). Content generated for informational purposes.*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 5. MEMORY
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
