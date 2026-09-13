"""Classify project names using ordered dictionary rules.

The rules match whole words and selected stems. They return a family where a
rule applies and retain explicit categories for generic or unreadable names.
These are descriptive classifications. Their accuracy requires separate human
validation, and the legacy dictionary-validation sheet was not completed."""
from __future__ import annotations
import re
from collections import OrderedDict

# Ordered: earlier families win ties.
GENRE_RULES: "OrderedDict[str, list[str]]" = OrderedDict([
    ("Health and fitness", ["calorie", "care", "clinic", "diet", "fitness", "gym", "health", "hydration", "meal", "med-", "medic", "meds", "mental", "nutrition", "pill", "run-", "running", "sleep", "step-counter", "therapy", "wellness", "workout", "yoga"]),
    ("Money and admin", ["accounting", "bank", "bill-", "billing", "budget", "crypto", "expense", "finance", "invoice", "ledger", "loan", "money", "pay", "payment", "payroll", "portfolio-track", "receipt", "salary", "saving", "spend", "subscription-track", "tax", "wallet"]),
    ("Shop and commerce", ["booking", "cafe", "cart", "checkout", "e-commerce", "ecommerce", "market", "marketplace", "menu", "order", "product", "product-page", "reservation", "restaurant", "shop", "store", "storefront"]),
    ("Business and clients", ["agency", "b2b", "client", "contract", "crm", "cv", "enterprise", "erp", "helpdesk", "hr", "hr-", "invoice-client", "lead", "lead-", "onboarding", "pipeline", "portfolio-client", "proposal", "recruit", "resume", "saas", "sales", "ticketing"]),
    ("Travel and hospitality", ["travel", "tour", "tours", "trip", "flight", "hotel", "hostel",
                                "booking-travel", "itinerary", "vacation", "holiday", "resort",
                                "airbnb", "rental-stay", "cruise", "safari", "visa", "passport",
                                "escapade", "voyage", "journey-plan", "backpack"]),
    ("Property and home", ["estate", "realty", "property", "rent", "rental", "landlord", "tenant",
                           "housing", "apartment", "mortgage", "interior", "furniture", "garden",
                           "cleaning", "plumb", "renovat", "construct", "builder-home", "architect"]),
    ("Logistics and transport", ["freight", "shipment", "shipping", "logistic", "delivery", "courier",
                                 "fleet", "truck", "cargo", "warehouse", "dispatch", "route",
                                 "driver", "ride", "taxi", "parking", "transport", "supply-chain"]),
    ("Food and drink", ["food", "recipe", "cook", "kitchen", "burger", "pizza", "cuisine", "bakery",
                        "coffee", "espresso", "juice", "grocer", "catering", "chef", "dine", "snack",
                        "lanches", "comida", "receta"]),
    ("Beauty and fashion", ["salon", "barber", "hair", "nails", "beauty", "cosmetic", "spa",
                            "fashion", "clothing", "footwear", "shoes", "apparel", "boutique",
                            "jewel", "tailor", "makeup", "skincare", "styles"]),
    ("Jobs and careers", ["job", "career", "hiring", "resume-build", "interview", "freelance",
                          "gig", "internship", "cv-build", "employ", "staff", "talent", "payroll-hr"]),
    ("Pets and animals", ["pet", "dog", "cat", "puppy", "vet", "animal", "kennel", "aquarium",
                          "horse", "bird"]),
    ("Faith and culture", ["church", "mosque", "temple", "quran", "bible", "islam", "christian",
                           "prayer", "faith", "spiritual", "astro", "horoscope", "tarot", "zodiac",
                           "vivaah", "wedding-culture"]),
    ("News and information", ["news", "magazine", "journal-news", "press", "article", "headline",
                              "weather", "radio", "tv-", "broadcast", "report-news"]),
    ("Sport and outdoors", ["sport", "football", "soccer", "cricket", "basketball", "tennis", "golf",
                            "cycling", "hike", "climb", "surf", "fishing", "match-score", "league",
                            "tournament", "gym-sport"]),
    ("Trackers and dashboards", ["-track", "admin", "analytics", "console", "counter", "dash", "dashboard", "habit", "insight", "insights", "logger", "metrics", "monitor", "panel", "progress", "report", "stats", "streak", "track", "track-", "tracker"]),
    ("Planning and productivity", ["agenda", "calendar", "checklist", "goal", "habit", "inventory", "journal", "kanban", "note", "notes", "organis", "organiser", "organiz", "organizer", "plan", "plan-", "planner", "pomodoro", "reminder", "schedul", "schedule", "task", "timer", "to-do", "todo"]),
    ("Games and toys", ["adventure", "arcade", "bingo", "card", "chess", "clicker", "dungeon", "game", "platformer", "play", "puzzle", "quiz", "quiz-game", "rpg", "snake", "sudoku", "tetris", "trivia", "wordle"]),
    ("Learning and study", ["academy", "campus", "class", "classroom", "course", "edu", "exam", "flashcard", "homework", "language-", "learn", "lesson", "math-", "quiz", "revision", "school", "spelling", "student", "study", "training", "tutor", "vocab"]),
    ("Creative and media", ["-art", "art", "art-", "audio", "canvas", "design", "draw", "film", "gallery", "image", "meme", "music", "paint", "photo", "pixel", "podcast", "poem", "poetry", "sketch", "sound", "story", "studio", "video", "visual", "writing"]),
    ("Community and events", ["charity", "chat-room", "church", "club", "community", "event", "family", "forum", "group", "local", "meetup", "neighbor", "neighbour", "party", "social", "team-", "volunteer", "wedding"]),
    ("AI and chatbots", ["-ai", "agent", "agent-", "ai-", "assistant", "bot", "bot-", "chat", "chatbot", "copilot", "gpt", "llm", "prompt", "summaris", "summariz", "transcrib", "voice", "whisper"]),
    ("Site and portfolio", ["blog", "brand", "cv-", "folio", "homepage", "landing", "linktree", "one-page", "personal-site", "portfolio", "profile-page", "resume", "showcase", "site", "web-site", "webpage", "website"]),
    ("Utilities and converters", ["calc", "calculator", "compress", "convert", "converter", "downloader", "formatter", "generator", "parser", "password", "pdf", "qr", "qr-", "random", "resize", "scanner", "scraper", "timer", "tool-", "translat"]),
])

# Signals that the artifact is aimed at a market rather than at the maker.
COMMERCE_TOKENS = ["saas","b2b","crm","invoice","billing","subscription","pricing","checkout",
                   "stripe","payment","ecommerce","e-commerce","store","shop","agency","client",
                   "lead-","sales","enterprise","premium","pro-plan","marketplace","booking",
                   "monetiz","monetis","revenue","startup"]

# Signals that the artifact is aimed at the maker or their circle.
PERSONAL_TOKENS = ["my-","-my-","personal","family","home-","our-","mum","mom","dad","kids",
                   "wife","husband","grandma","grandpa","baby","pet","dog","cat","wedding",
                   "birthday","gift","friends"]

# Signals of a single occasion.
EPHEMERAL_TOKENS = ["wedding","party","birthday","countdown","timer","workshop","event-",
                    "conference","demo","test-","temp","quick-","today","tonight","oneday",
                    "hackathon","secret-santa","advent","christmas","halloween","new-year"]

_word = re.compile(r"[^a-z0-9]+")


def normalise(slug: str) -> str:
    return "-" + _word.sub("-", str(slug).lower()).strip("-") + "-"


GENERIC_NAME_TOKENS = ["and", "app", "aura", "buddy", "build", "builder", "code", "companion", "compass", "connect", "control", "craft", "creator", "data", "demo", "digital", "echo", "engine", "explorer", "final", "finder", "flow", "forge", "frontend", "future", "global", "glow", "growth", "guard", "guardian", "guide", "harmony", "home", "hub", "journey", "lab", "launchpad", "link", "live", "lovable", "magic", "main", "maker", "manager", "master", "navigator", "new", "nexus", "now", "online", "page", "path", "perfect", "platform", "portal", "pro", "project", "pulse", "quest", "react", "remix", "scribe", "secure", "site", "solutions", "space", "spark", "sparkle", "stream", "style", "suite", "sync", "system", "tech", "test", "the", "vault", "verse", "vision", "web", "wizard", "your", "zen"]


def is_generic_name(slug: str) -> bool:
    """True when every word in the name comes from the builder-era product vocabulary
    (hub, flow, connect, glow) and none of it says what the software does."""
    ws = [w for w in words(slug) if len(w) > 2]
    if not ws:
        return False
    return all(w in GENERIC_NAME_TOKENS for w in ws)


def words(slug: str) -> list[str]:
    """Split a project name into words.

    Names arrive in several shapes: hyphenated (habit-tracker), underscored
    (drmeds_v2) and camel case (CommunityHub). All three are split, because a
    genre signal hidden inside camel case is still a genre signal.
    """
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(slug))
    return [w for w in re.split(r"[^A-Za-z0-9]+", raw.lower()) if w]


def _matches(word: str, key: str) -> bool:
    """Match a keyword against one word of the name.

    Substring matching across the whole name was the original rule and it was
    badly wrong: "art" matched Startup and dollyparton, "cat" matched category,
    "spa" matched space, "press" matched express. Matching is now word-bounded.
    A keyword matches a word exactly, or as its stem when the keyword is at
    least five characters (so "medic" catches medical and "schedul" catches
    scheduling, while "art" cannot reach into "startup").
    """
    if key.startswith("-") or key.endswith("-"):      # explicit affix rules
        k = key.strip("-")
        return word.startswith(k) if key.endswith("-") else word.endswith(k)
    if word == key:
        return True
    return len(key) >= 5 and word.startswith(key)


def genre(slug: str) -> str:
    ws = words(slug)
    for label, tokens in GENRE_RULES.items():
        for t in tokens:
            t = t.strip()
            if any(_matches(w, t) for w in ws):
                return label
    if is_generic_name(slug):
        return "Generic or brand-style name"
    return "Unclassified"


def _has(slug: str, tokens: list[str]) -> bool:
    ws = words(slug)
    return any(_matches(w, t.strip()) for t in tokens for w in ws)


def is_commercial(slug: str) -> bool:
    return _has(slug, COMMERCE_TOKENS)


def is_personal(slug: str) -> bool:
    return _has(slug, PERSONAL_TOKENS)


def is_ephemeral(slug: str) -> bool:
    return _has(slug, EPHEMERAL_TOKENS)


def purpose(slug: str) -> str:
    """Three-way purpose class. Commerce wins over personal when both appear,
    because a named market intent is the stronger claim."""
    if is_commercial(slug):
        return "For a market"
    if is_personal(slug):
        return "For self or circle"
    return "Unstated"


# ---------------------------------------------------------------------------
# Auto-generated slugs
# ---------------------------------------------------------------------------
# Builder tools name a project for the user when the user does not name it.
# Lovable's default is a whimsical adjective-noun-noun triple such as
# "aurora-echo-verse". Those slugs describe nothing, so counting them as
# genres would invent a finding. They are flagged and reported separately
# rather than silently dropped.

_WHIMSY = {
    "aurora","echo","verse","nova","lunar","solar","cosmic","zen","vivid","prism","ember",
    "lumen","halcyon","quartz","onyx","ivory","amber","crimson","azure","cobalt","jade",
    "swift","gentle","silent","radiant","whisper","velvet","glimmer","shimmer","drift",
    "haven","meadow","harbor","harbour","summit","cascade","canyon","willow","cedar","fern",
    "orbit","pulse","spark","flux","nexus","vertex","zephyr","quantum","stellar","celestial",
    "mystic","serene","tranquil","noble","grand","prime","apex","forge","craft","studio",
    "wave","tide","bloom","petal","dawn","dusk","twilight","nimbus","cirrus","atlas",
}


def is_auto_slug(slug: str) -> bool:
    """True when the slug looks machine-named rather than maker-named.

    Two conditions together: the slug has no recognisable purpose token, and
    at least one part comes from the builder's whimsical vocabulary. Requiring
    both keeps genuinely odd human names (a band name, an in-joke) out of the
    flag where they also carry a purpose word.
    """
    if genre(slug) != "Unclassified":
        return False
    parts = [p for p in normalise(slug).strip("-").split("-") if p]
    return len(parts) >= 3 and any(p in _WHIMSY for p in parts)


def genre_combined(slug: str, page_title: str = "") -> str:
    """Genre from the maker's project name, falling back to the live page title.

    The project name supplies the main text signal. It may have been generated
    by the builder tool. A saved page title provides supplementary text where
    the name alone cannot be classified.
    """
    g = genre(slug)
    if g in ("Unclassified", "Generic or brand-style name") and page_title:
        t = genre(str(page_title))
        if t not in ("Unclassified", "Generic or brand-style name"):
            return t
    return g
