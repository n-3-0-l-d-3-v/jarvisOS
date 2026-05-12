import httpx
import json
import re
from typing import Optional

_slug_cache = {}


def extract_lc_number(text: str) -> Optional[int]:
    text_stripped = text.strip()

    match = re.search(r"\bLC-?(\d+)\b", text_stripped, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(r"\bleetcode[-\s]?(\d+)\b", text_stripped, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.match(r"^(\d+)[\.\s]", text_stripped)
    if match:
        return int(match.group(1))

    return None


def get_problem_slug(problem_number: int) -> Optional[str]:
    if problem_number in _slug_cache:
        return _slug_cache[problem_number]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://leetcode.com",
    }

    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            response = client.get("https://leetcode.com/api/problems/all/")

        if response.status_code != 200:
            return None

        payload = response.json()
        questions = payload.get("stat_status_pairs", [])
        for item in questions:
            stat = item.get("stat", {})
            if stat.get("frontend_question_id") == problem_number:
                slug = stat.get("question__title_slug")
                if slug:
                    _slug_cache[problem_number] = slug
                    return slug
    except Exception:
        return None

    return None


def fetch_problem(problem_number: int) -> Optional[dict]:
    try:
        slug = get_problem_slug(problem_number)
        if not slug:
            print("  [Jarvis] LeetCode: problem slug not found")
            return None

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://leetcode.com/problems/{slug}/",
            "Accept": "application/json",
        }

        payload = {
            "query": """
                query questionData($titleSlug: String!) {
                  question(titleSlug: $titleSlug) {
                    questionId
                    questionFrontendId
                    title
                    titleSlug
                    difficulty
                    topicTags {
                      name
                      slug
                    }
                    companyTagStats
                    hints
                    content
                  }
                }
            """,
            "variables": {"titleSlug": slug},
        }

        with httpx.Client(timeout=20.0, headers=headers) as client:
            response = client.post("https://leetcode.com/graphql", json=payload)

        if response.status_code != 200:
            print(f"  [Jarvis] LeetCode: fetch failed ({response.status_code})")
            return None

        data = response.json()
        question = data.get("data", {}).get("question")
        if not question:
            return None

        tags = [tag.get("name", "") for tag in question.get("topicTags", [])]

        company_stats = question.get("companyTagStats", "{}")
        companies = []
        if isinstance(company_stats, str):
            try:
                parsed = json.loads(company_stats)
                for bucket in ["1", "2", "3"]:
                    for item in parsed.get(bucket, []):
                        name = item.get("name", "")
                        if name:
                            companies.append(name)
                companies = companies[:5]
            except Exception:
                companies = []

        content = question.get("content", "") or ""
        clean = re.sub(r"<[^>]+>", "", content)
        clean = re.sub(r"&[a-zA-Z]+;", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        problem_summary = clean[:500]

        return {
            "problem_number": question.get("questionFrontendId", ""),
            "title": question.get("title", ""),
            "slug": slug,
            "difficulty": question.get("difficulty", ""),
            "tags": tags,
            "companies": companies,
            "hints": (question.get("hints", []) or [])[:2],
            "problem_summary": problem_summary,
            "url": f"https://leetcode.com/problems/{slug}/",
        }
    except Exception as exc:
        print(f"  [Jarvis] LeetCode: fetch error ({exc})")
        return None


def enrich_note_with_leetcode(text: str, classification: dict) -> Optional[dict]:
    number = extract_lc_number(text)
    if not number:
        return None

    print(f"  [Jarvis] LeetCode: detected problem #{number}")
    data = fetch_problem(number)
    if not data:
        print("  [Jarvis] LeetCode: fetch failed, continuing without")
        return None

    title = data.get("title", "")
    difficulty = data.get("difficulty", "")
    print(f"  [Jarvis] LeetCode: fetched '{title}' ({difficulty})")
    return data
