import google.generativeai as genai
import json
import re
import time
import httpx

from jarvis.config import GEMINI_API_KEY, GROQ_API_KEY


MODEL_NAME = "gemini-2.0-flash"

CORRECT_PREFIXES = {
    "dsa": "04-dsa",
    "frontend": "05-frontend",
    "backend": "06-backend",
    "fullstack": "07-fullstack",
    "databases": "08-databases",
    "system-design": "09-system-design",
    "devops": "10-devops",
    "cloud": "11-cloud",
    "ai-ml": "12-ai-ml",
    "security": "13-security",
    "data-engineering": "14-data-engineering",
    "mobile": "15-mobile",
    "testing": "16-testing",
    "automation": "17-automation",
    "web-scraping": "18-web-scraping",
    "linux-shell": "19-linux-shell",
    "open-source": "20-open-source",
    "creators": "21-creators",
    "knowledge-base": "22-knowledge-base",
    "projects": "23-projects",
    "career": "24-career",
    "research": "25-research",
    "programming": "03-programming",
    "core-cs": "02-core-cs",
    "foundations": "01-foundations",
}


if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def clean_json_response(text):
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_json(text):
    if not text:
        return None
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass

    try:
        fixed = text[start : end + 1] if start != -1 else text
        fixed = fixed.replace("'", '"')
        return json.loads(fixed)
    except Exception:
        pass

    return None


def validate_folder_path(folder_path):
    if not folder_path:
        return folder_path

    parts = folder_path.split("/")
    if not parts:
        return folder_path

    current_prefix = parts[0]
    domain = re.sub(r"^\d+-", "", current_prefix)
    correct_prefix = CORRECT_PREFIXES.get(domain)
    if correct_prefix and correct_prefix != current_prefix:
        parts[0] = correct_prefix
        return "/".join(parts)

    return folder_path


def detect_dsa_pattern(text):
    lower_text = (text or "").lower()

    if any(
        key in lower_text
        for key in [
            "sliding window",
            "subarray",
            "substring window",
            "window size",
            "expand right",
            "shrink left",
        ]
    ):
        return "sliding-window"

    if any(
        key in lower_text
        for key in [
            "two pointer",
            "two-pointer",
            "left right pointer",
            "slow fast pointer",
            "fast slow",
            "tortoise hare",
        ]
    ):
        return "two-pointers"

    if any(
        key in lower_text
        for key in [
            "binary search",
            "sorted array search",
            "search rotated",
            "find mid",
            "lo hi mid",
        ]
    ):
        return "binary-search"

    if any(
        key in lower_text
        for key in [
            "dynamic programming",
            "dp table",
            "memoization",
            "bottom up",
            "top down dp",
            "dp[i]",
            "subproblem",
        ]
    ):
        return "dynamic-programming"

    if any(
        key in lower_text
        for key in [
            "backtracking",
            "try all",
            "undo",
            "n-queens",
            "permutation",
            "combination sum",
            "explore all paths",
        ]
    ):
        return "backtracking"

    if any(
        key in lower_text
        for key in [
            "binary tree",
            "bst",
            "binary search tree",
            "inorder",
            "preorder",
            "postorder",
            "level order",
            "tree traversal",
            "root node",
            "left child",
            "right child",
            "leaf node",
            "tree depth",
            "tree height",
            "lowest common ancestor",
            "lca",
            "serialize tree",
            "deserialize tree",
            "trie",
        ]
    ):
        return "trees"

    if (
        ("binary tree" in lower_text or "bst" in lower_text)
        and ("bfs" in lower_text or "dfs" in lower_text)
    ):
        return "trees"

    if any(
        key in lower_text
        for key in [
            "graph",
            "bfs",
            "dfs",
            "breadth first",
            "depth first",
            "adjacency",
            "visited",
            "connected components",
        ]
    ):
        return "graphs"

    if any(
        key in lower_text
        for key in [
            "heap",
            "priority queue",
            "min heap",
            "max heap",
            "top k",
            "k largest",
            "k smallest",
        ]
    ):
        return "heaps"

    if any(
        key in lower_text
        for key in [
            "linked list",
            "next pointer",
            "prev pointer",
            "head node",
            "dummy node",
            "reverse list",
        ]
    ):
        return "linked-lists"

    if any(
        key in lower_text
        for key in [
            "stack",
            "monotonic stack",
            "next greater",
            "previous smaller",
            "push pop",
        ]
    ):
        return "stacks"

    if any(
        key in lower_text
        for key in [
            "greedy",
            "always pick",
            "local optimal",
            "interval scheduling",
            "activity selection",
        ]
    ):
        return "greedy"

    if any(
        key in lower_text
        for key in [
            "trie",
            "prefix tree",
            "word search",
            "autocomplete",
            "insert word search",
        ]
    ):
        return "tries"

    if any(
        key in lower_text
        for key in [
            "lc-",
            "leetcode",
            "leet code",
            "problem",
            "time complexity",
            "space complexity",
            "o(n",
            "o(log",
        ]
    ):
        return "arrays"

    return ""


def detect_note_type(text, source):
    lower_text = (text or "").lower()
    lower_source = (source or "").lower()

    if lower_source == "leetcode":
        return "dsa"

    if any(
        key in lower_text
        for key in [
            "bug:",
            "error:",
            "exception:",
            "traceback",
            "not working",
            "broken",
            "fix:",
            "fixed by",
            "issue:",
            "debug",
        ]
    ):
        return "bug"

    if any(
        key in lower_text
        for key in [
            "def ",
            "function ",
            "class ",
            "import ",
            "```",
            "const ",
            "let ",
            "var ",
            "=>",
            "snippet",
            "reusable",
        ]
    ):
        return "snippet"

    if lower_source in {"youtube", "video"}:
        return "video-summary"

    if lower_source == "article" or any(
        key in lower_text for key in ["article", "blog post", "post about"]
    ):
        return "article"

    return "concept"


def build_classification_prompt(text, source, source_url, pre_type, dsa_pattern):
    dsa_value = dsa_pattern if dsa_pattern else "none"
    return f"""
You are Jarvis, a precise AI classifier for a personal engineering knowledge OS.
Return ONLY valid JSON. No explanation. No markdown fences. No extra text.
Start your response with {{ and end with }}.

Input note:
Source: {source}
URL: {source_url}
Pre-detected type: {pre_type}
Pre-detected DSA pattern: {dsa_value}
Content: {text}

Return this exact JSON:
{{
    "domain": "dsa|frontend|backend|fullstack|databases|devops|cloud|ai-ml|security|system-design|data-engineering|mobile|testing|automation|linux-shell|core-cs|programming|foundations|open-source|research|career|creator-content|knowledge-base",
    "subdomain": "specific technology: redis, react, docker, sliding-window, jwt, etc",
    "type": "concept|bug|snippet|dsa|video-summary|article|project|cheatsheet|command",
    "title": "clean descriptive title max 8 words in title case",
    "tags": ["exactly 4 lowercase specific tags"],
    "folder_path": "exact repo path like 08-databases/redis or 04-dsa/sliding-window",
    "complexity": "beginner|intermediate|advanced",
    "creator": "channel name if video else empty string",
    "summary": "one sentence describing this note",
    "dsa_pattern": "{dsa_pattern if dsa_pattern else ''}",
    "confidence": 0.85
}}
"""


def _normalize_classification(classification, pre_type, dsa_pattern, text, source):
    default_title = (text or "").strip()[:50]
    default_summary = (text or "").strip()[:100]
    safe_dsa = dsa_pattern or ""

    if not isinstance(classification, dict):
        classification = {}

    classification.setdefault("domain", "knowledge-base")
    classification.setdefault("subdomain", "unsorted")
    classification.setdefault("type", pre_type)
    classification.setdefault("title", default_title or "Untitled Note")
    classification.setdefault("tags", [source, "unsorted", "review-needed", pre_type])
    classification.setdefault("folder_path", "22-knowledge-base/unsorted")
    classification.setdefault("complexity", "beginner")
    classification.setdefault("creator", "")
    classification.setdefault("summary", default_summary)
    classification.setdefault("dsa_pattern", safe_dsa)
    classification.setdefault("confidence", 0.0)

    if pre_type in {"dsa", "bug"}:
        classification["type"] = pre_type

    if classification.get("type") == "dsa" and not classification.get("dsa_pattern"):
        classification["dsa_pattern"] = dsa_pattern or "arrays"

    tags = classification.get("tags")
    if not isinstance(tags, list) or len(tags) < 4:
        tags = [source, "unsorted", "review-needed", pre_type]
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
    while len(tags) < 4:
        tags.append("unsorted")
    classification["tags"] = tags[:4]

    if not classification.get("folder_path"):
        classification["folder_path"] = "22-knowledge-base/unsorted"

    return classification


def _fallback_classification(text, source, pre_type, dsa_pattern):
    return {
        "domain": "knowledge-base",
        "subdomain": "unsorted",
        "type": pre_type,
        "title": (text or "").strip()[:50],
        "tags": [source, "unsorted", "review-needed", pre_type],
        "folder_path": "22-knowledge-base/unsorted",
        "complexity": "beginner",
        "creator": "",
        "summary": (text or "").strip()[:100],
        "dsa_pattern": dsa_pattern,
        "confidence": 0.0,
    }


def classify_with_groq(text, source, source_url, pre_type, dsa_pattern):
    if not GROQ_API_KEY:
        return None

    try:
        prompt = build_classification_prompt(text, source, source_url, pre_type, dsa_pattern)

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
            )

        print(f"  [Jarvis] Groq status: {response.status_code}")

        if response.status_code != 200:
            print(f"  [Jarvis] Groq error body: {response.text[:300]}")
            return None

        data = response.json()
        response_text = data["choices"][0]["message"]["content"]
        print(f"  [Jarvis] Groq raw response: {response_text[:300]}")

        result = extract_json(response_text)
        if result is None:
            print("  [Jarvis] Groq response could not be parsed as JSON")
            return None

        if result.get("folder_path"):
            result["folder_path"] = validate_folder_path(result["folder_path"])

        result["classifier_used"] = "groq"
        result.setdefault("confidence", 0.75)
        return result

    except httpx.TimeoutException:
        print("  [Jarvis] Groq request timed out")
        return None
    except httpx.RequestError as exception:
        print(f"  [Jarvis] Groq connection error: {exception}")
        return None
    except Exception as exception:
        print(f"  [Jarvis] Groq unexpected error: {exception}")
        return None


def classify_with_keywords(text, source, source_url, pre_type, dsa_pattern):
    lower_text = (text or "").lower()

    if pre_type == "dsa" and dsa_pattern:
        domain = "dsa"
        subdomain = dsa_pattern
        folder_path = f"04-dsa/{dsa_pattern}"
    elif pre_type == "dsa":
        domain = "dsa"
        subdomain = "arrays"
        folder_path = "04-dsa/arrays"
    elif pre_type == "bug":
        domain = "knowledge-base"
        subdomain = "bugs"
        folder_path = "22-knowledge-base/bugs-i-faced"
    elif pre_type == "snippet":
        domain = "programming"
        subdomain = "snippets"
        folder_path = "22-knowledge-base/snippets"
    elif pre_type == "video-summary":
        domain = "creator-content"
        subdomain = "videos"
        folder_path = "21-creators/general"
    elif pre_type == "article":
        domain = "knowledge-base"
        subdomain = "articles"
        folder_path = "22-knowledge-base/articles"
    else:
        if any(
            word in lower_text
            for word in [
                "redis",
                "rdb",
                "aof",
                "sorted set",
                "hash map redis",
                "pub/sub",
                "redis cluster",
            ]
        ):
            folder_path = "08-databases/redis"
        elif any(
            word in lower_text
            for word in ["postgres", "postgresql", "pg", "psql"]
        ):
            folder_path = "08-databases/postgresql"
        elif any(
            word in lower_text
            for word in ["mongodb", "mongoose", "bson", "aggregation pipeline", "atlas"]
        ):
            folder_path = "08-databases/mongodb"
        elif any(
            word in lower_text
            for word in ["mysql", "innodb", "mariadb"]
        ):
            folder_path = "08-databases/mysql"
        elif any(
            word in lower_text
            for word in ["firebase", "firestore", "realtime database"]
        ):
            folder_path = "08-databases/firebase"
        elif any(
            word in lower_text
            for word in ["supabase", "supabase auth", "supabase storage"]
        ):
            folder_path = "08-databases/supabase"
        elif any(
            word in lower_text
            for word in [
                "sql",
                "query",
                "join",
                "index",
                "schema",
                "normalization",
                "transaction",
                "acid",
            ]
        ):
            folder_path = "08-databases/sql"
        elif any(
            word in lower_text
            for word in [
                "react",
                "jsx",
                "hooks",
                "usestate",
                "useeffect",
                "component",
                "props",
                "redux",
                "zustand",
            ]
        ):
            folder_path = "05-frontend/react"
        elif any(
            word in lower_text
            for word in [
                "nextjs",
                "next.js",
                "app router",
                "server component",
                "getserversideprops",
            ]
        ):
            folder_path = "05-frontend/nextjs"
        elif any(
            word in lower_text
            for word in [
                "css",
                "tailwind",
                "flexbox",
                "grid",
                "animation",
                "responsive",
                "sass",
                "stylesheet",
            ]
        ):
            folder_path = "05-frontend/css"
        elif any(
            word in lower_text
            for word in [
                "javascript",
                "js",
                "dom",
                "event loop",
                "closure",
                "prototype",
                "async await",
                "promise",
            ]
        ):
            folder_path = "05-frontend/javascript"
        elif any(
            word in lower_text
            for word in [
                "typescript",
                "type alias",
                "interface ts",
                "generic type",
                "ts enum",
                "ts decorator",
                ".ts file",
            ]
        ):
            folder_path = "03-programming/typescript"
        elif any(
            word in lower_text
            for word in [
                "jwt",
                "token",
                "auth",
                "oauth",
                "session",
                "cookie",
                "bearer",
                "refresh token",
            ]
        ):
            folder_path = "06-backend/authentication"
        elif any(
            word in lower_text
            for word in ["express", "middleware", "app.use", "router", "req res next"]
        ):
            folder_path = "06-backend/nodejs"
        elif any(
            word in lower_text
            for word in ["fastapi", "pydantic", "uvicorn", "starlette"]
        ):
            folder_path = "06-backend/fastapi"
        elif any(
            word in lower_text
            for word in ["graphql", "resolver", "schema", "mutation", "query", "subscription"]
        ):
            folder_path = "06-backend/graphql"
        elif any(
            word in lower_text
            for word in ["websocket", "socket.io", "realtime", "ws://"]
        ):
            folder_path = "06-backend/websocket"
        elif any(
            word in lower_text
            for word in ["microservice", "service mesh", "grpc", "event driven"]
        ):
            folder_path = "06-backend/microservices"
        elif any(
            word in lower_text
            for word in [
                "kafka",
                "rabbitmq",
                "message queue",
                "pubsub",
                "broker",
                "consumer",
                "producer",
            ]
        ):
            folder_path = "06-backend/message-queues"
        elif any(
            word in lower_text
            for word in ["caching", "cache", "ttl", "eviction", "invalidation"]
        ):
            folder_path = "06-backend/caching"
        elif any(
            word in lower_text
            for word in [
                "rest api",
                "http method",
                "get post put delete",
                "status code",
                "request response",
                "api endpoint",
                "endpoint design",
            ]
        ):
            folder_path = "06-backend/rest-api"
        elif any(
            word in lower_text
            for word in ["docker", "dockerfile", "container", "image", "docker-compose", "registry"]
        ):
            folder_path = "10-devops/docker"
        elif any(
            word in lower_text
            for word in [
                "kubernetes",
                "k8s",
                "pod",
                "deployment",
                "service",
                "ingress",
                "helm",
                "kubectl",
            ]
        ):
            folder_path = "10-devops/kubernetes"
        elif any(
            word in lower_text
            for word in [
                "github actions",
                "gitlab ci",
                "jenkins",
                "pipeline",
                "workflow yml",
                "ci/cd",
            ]
        ):
            folder_path = "10-devops/ci-cd"
        elif any(
            word in lower_text
            for word in ["nginx", "reverse proxy", "load balancer", "upstream"]
        ):
            folder_path = "10-devops/nginx"
        elif any(
            word in lower_text
            for word in ["terraform", "ansible", "infrastructure as code", "iac"]
        ):
            folder_path = "10-devops/terraform"
        elif any(
            word in lower_text
            for word in ["grafana", "prometheus", "monitoring", "alert", "dashboard metrics"]
        ):
            folder_path = "10-devops/monitoring"
        elif any(
            word in lower_text
            for word in [
                "aws",
                "ec2",
                "s3",
                "lambda",
                "rds",
                "cloudfront",
                "iam",
                "vpc",
                "eks",
                "ecs",
            ]
        ):
            folder_path = "11-cloud/aws"
        elif any(
            word in lower_text
            for word in ["gcp", "google cloud", "bigquery", "cloud run", "firebase"]
        ):
            folder_path = "11-cloud/gcp"
        elif any(
            word in lower_text
            for word in ["azure", "microsoft cloud", "azure functions"]
        ):
            folder_path = "11-cloud/azure"
        elif any(
            word in lower_text
            for word in ["serverless", "lambda", "cloud function", "faas"]
        ):
            folder_path = "11-cloud/serverless"
        elif any(
            word in lower_text
            for word in [
                "langchain",
                "llamaindex",
                "llm",
                "gpt",
                "claude",
                "gemini",
                "prompt",
                "token",
                "context window",
            ]
        ):
            folder_path = "12-ai-ml/llms"
        elif any(
            word in lower_text
            for word in ["rag", "retrieval", "vector", "embedding", "semantic", "chromadb", "pinecone"]
        ):
            folder_path = "12-ai-ml/rag"
        elif any(
            word in lower_text
            for word in ["agent", "tool calling", "function calling", "autonomous", "multi-agent"]
        ):
            folder_path = "12-ai-ml/ai-agents"
        elif any(
            word in lower_text
            for word in [
                "pytorch",
                "tensorflow",
                "neural network",
                "training",
                "model",
                "loss function",
                "backprop",
            ]
        ):
            folder_path = "12-ai-ml/deep-learning"
        elif any(
            word in lower_text
            for word in ["machine learning", "sklearn", "regression", "classification", "clustering"]
        ):
            folder_path = "12-ai-ml/machine-learning"
        elif any(
            word in lower_text
            for word in ["xss", "csrf", "injection", "owasp", "vulnerability", "exploit", "sanitize"]
        ):
            folder_path = "13-security/web-security"
        elif any(
            word in lower_text
            for word in ["ssl", "tls", "https", "certificate", "encryption", "decrypt", "cipher"]
        ):
            folder_path = "13-security/cryptography"
        elif any(
            word in lower_text
            for word in ["system design", "scalability", "horizontal scale", "vertical scale", "distributed"]
        ):
            folder_path = "09-system-design/scalability"
        elif any(
            word in lower_text
            for word in ["load balanc", "round robin", "least connection"]
        ):
            folder_path = "09-system-design/load-balancing"
        elif any(
            word in lower_text
            for word in ["cap theorem", "consistency", "availability", "partition tolerance"]
        ):
            folder_path = "09-system-design/cap-theorem"
        elif any(
            word in lower_text
            for word in ["bash", "shell script", "chmod", "grep", "awk", "sed", "pipe", "stdin stdout"]
        ):
            folder_path = "19-linux-shell/bash-scripting"
        elif any(
            word in lower_text
            for word in ["linux", "ubuntu", "debian", "systemd", "cron", "ssh", "vim", "tmux"]
        ):
            folder_path = "19-linux-shell/linux-basics"
        elif any(
            word in lower_text
            for word in ["python", "pip", "virtualenv", "decorator", "generator", "asyncio", "pydantic"]
        ):
            folder_path = "03-programming/python"
        elif any(
            word in lower_text
            for word in ["golang", "go lang", "goroutine", "channel go", "struct go"]
        ):
            folder_path = "03-programming/golang"
        elif any(
            word in lower_text
            for word in ["rust", "ownership", "borrow", "lifetime", "cargo"]
        ):
            folder_path = "03-programming/rust"
        else:
            folder_path = "22-knowledge-base"

        parts = folder_path.split("/")
        domain_map = {
            "04-dsa": "dsa",
            "05-frontend": "frontend",
            "06-backend": "backend",
            "08-databases": "databases",
            "09-system-design": "system-design",
            "10-devops": "devops",
            "11-cloud": "cloud",
            "12-ai-ml": "ai-ml",
            "13-security": "security",
            "19-linux-shell": "linux-shell",
            "03-programming": "programming",
            "22-knowledge-base": "knowledge-base",
        }
        domain = domain_map.get(parts[0], "knowledge-base")
        subdomain = parts[1] if len(parts) > 1 else "general"

    words = re.findall(r"[A-Za-z0-9]+", text or "")
    title = " ".join(words[:6]).title() if words else "Untitled Note"

    tags = []
    seen = set()
    for word in re.findall(r"[A-Za-z0-9]+", text or ""):
        if len(word) <= 4:
            continue
        lower_word = word.lower()
        if lower_word in seen:
            continue
        tags.append(lower_word)
        seen.add(lower_word)
        if len(tags) == 4:
            break
    while len(tags) < 4:
        tags.append("unsorted")

    return {
        "domain": domain,
        "subdomain": subdomain,
        "type": pre_type,
        "title": title,
        "tags": tags,
        "folder_path": folder_path,
        "complexity": "beginner",
        "creator": "",
        "summary": (text or "").strip()[:100],
        "dsa_pattern": dsa_pattern,
        "confidence": 0.5,
        "classifier_used": "keywords",
    }


def classify_note(text, source, source_url):
    pre_type = detect_note_type(text, source)
    dsa_pattern = detect_dsa_pattern(text)
    prompt = build_classification_prompt(text, source, source_url, pre_type, dsa_pattern)

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(MODEL_NAME)
            response = model.generate_content(prompt)
            raw_text = getattr(response, "text", "") or ""
            cleaned = clean_json_response(raw_text)
            parsed = json.loads(cleaned)
            normalized = _normalize_classification(parsed, pre_type, dsa_pattern, text, source)
            normalized.setdefault("confidence", 0.85)
            normalized["classifier_used"] = "gemini"
            if normalized.get("folder_path"):
                normalized["folder_path"] = validate_folder_path(normalized["folder_path"])
            return normalized
        except Exception:
            print("  [Jarvis] Gemini quota hit -- trying Groq...")

    if GROQ_API_KEY:
        groq_result = classify_with_groq(text, source, source_url, pre_type, dsa_pattern)
        if groq_result is not None:
            normalized = _normalize_classification(groq_result, pre_type, dsa_pattern, text, source)
            normalized.setdefault("confidence", 0.75)
            normalized["classifier_used"] = "groq"
            print("  [Jarvis] Classified via Groq")
            return normalized
        print("  [Jarvis] Groq failed -- using keyword classifier...")

    keyword_result = classify_with_keywords(text, source, source_url, pre_type, dsa_pattern)
    print("  [Jarvis] Classified via keywords (offline mode)")
    return keyword_result


def format_note(text, classification, source, source_url, timestamp):
    date_value = timestamp[:10] if timestamp else ""
    resources = f"- [{source_url}]({source_url})" if source_url else "<!-- Add links here -->"
    return f'''---
title: "{classification['title']}"
date: {date_value}
domain: {classification['domain']}
subdomain: {classification['subdomain']}
type: {classification['type']}
tags: {classification['tags']}
source: {source}
source_url: {source_url}
complexity: {classification['complexity']}
creator: {classification['creator']}
reviewed: false
---

# {classification['title']}

## Summary
{classification['summary']}

## Notes
{text}

## Key Points
<!-- Add key takeaways here -->

## Examples
<!-- Add examples or code here -->

## Related Topics
<!-- [[wikilinks]] to related notes will be added automatically -->

## Resources
{resources}

---
*Captured: {timestamp} | Source: {source} | Jarvis*
'''


def reclassify_unsorted():
    from pathlib import Path
    from jarvis.config import REPO_PATH
    import shutil

    unsorted_path = REPO_PATH / "22-knowledge-base" / "unsorted"
    if not unsorted_path.exists():
        print("No unsorted folder found.")
        return

    files = list(unsorted_path.glob("*.md"))
    if not files:
        print("Unsorted folder is already empty.")
        return

    print(f"Reclassifying {len(files)} unsorted notes...")

    for filepath in files:
        content = filepath.read_text(encoding="utf-8")

        lines = content.split("\n")
        note_text = ""
        in_notes = False
        for line in lines:
            if line.strip() == "## Notes":
                in_notes = True
                continue
            if in_notes and line.startswith("## "):
                break
            if in_notes:
                note_text += line + "\n"
        note_text = note_text.strip()

        if not note_text:
            note_text = filepath.stem.replace("-", " ")

        print(f"  Reclassifying: {filepath.name[:50]}")

        pre_type = detect_note_type(note_text, "cli")
        dsa_pattern = detect_dsa_pattern(note_text)
        classification = classify_with_keywords(
            note_text, "cli", "", pre_type, dsa_pattern
        )

        new_folder = REPO_PATH / classification["folder_path"]
        new_folder.mkdir(parents=True, exist_ok=True)
        new_path = new_folder / filepath.name

        shutil.move(str(filepath), str(new_path))
        print(f"  Moved to: {classification['folder_path']}/{filepath.name}")

    remaining = list(unsorted_path.glob("*.md"))
    if not remaining:
        try:
            unsorted_path.rmdir()
            print("Unsorted folder removed.")
        except Exception:
            pass

    print("Reclassification complete.")
