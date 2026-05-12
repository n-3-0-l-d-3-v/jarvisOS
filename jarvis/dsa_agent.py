import httpx
import json
import re

from jarvis.config import GROQ_API_KEY
from jarvis.formatter import format_dsa


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


def analyze_dsa_note(text, classification, leetcode_data=None):
    if not GROQ_API_KEY:
        print("  [Jarvis] DSA Agent: no Groq key, skipping enrichment")
        return None

    pattern = classification.get("dsa_pattern", "")
    title = classification.get("title", "")

    prompt = f"""
You are an expert competitive programmer and CS educator.
Analyze this LeetCode/DSA note and extract structured information.
Return ONLY valid JSON. Start with {{ end with }}. No explanation.

Raw note: {text}
Detected pattern: {pattern}
Title: {title}

Return this exact JSON:
{{
  "problem_number": "LC number if mentioned like LC-76 else empty string",
  "problem_name": "clean problem name without LC prefix",
  "pattern": "exact pattern: sliding-window|two-pointers|binary-search|dynamic-programming|backtracking|graphs|trees|heaps|linked-lists|stacks|greedy|tries|arrays|strings|hashing",
  "approach": "2-3 sentence explanation of the solution approach",
  "time_complexity": "Big O time like O(n) or O(n log n)",
  "space_complexity": "Big O space like O(1) or O(n)",
  "key_insight": "the single most important observation to solve this",
  "edge_cases": ["list", "of", "edge", "cases", "to", "watch"],
  "similar_problems": ["2-3 similar problem names or LC numbers"],
  "difficulty": "Easy|Medium|Hard",
  "companies": ["companies that ask this if well known else empty list"],
  "template_applicable": true,
  "template_name": "name of template if applicable else empty string",
  "mistakes_to_avoid": "common mistake developers make on this problem type"
}}
"""
    if leetcode_data:
        lc_context = f"""
Official LeetCode data:
- Title: {leetcode_data.get('title', '')}
- Difficulty: {leetcode_data.get('difficulty', '')}
- Topic Tags: {', '.join(leetcode_data.get('tags', []))}
- Companies: {', '.join(leetcode_data.get('companies', []))}
- Problem: {leetcode_data.get('problem_summary', '')[:300]}
"""
        prompt = prompt + lc_context

    try:
        with httpx.Client(timeout=20.0) as client:
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
                    "max_tokens": 800,
                },
            )

        print(f"  [Jarvis] DSA Agent (Groq) status: {response.status_code}")

        if response.status_code != 200:
            print(f"  [Jarvis] DSA Agent error: {response.text[:200]}")
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        print(f"  [Jarvis] DSA Agent response: {content[:200]}")

        parsed = extract_json(content)
        if parsed is None:
            print("  [Jarvis] DSA Agent: could not parse response")
            return None

        return parsed
    except Exception:
        print("  [Jarvis] DSA Agent: could not parse response")
        return None


def build_dsa_note(text, classification, enriched_data, timestamp, leetcode_data=None):
    if not enriched_data:
        return format_dsa(text, classification, "leetcode", "", timestamp)

    date_value = timestamp[:10] if timestamp else ""
    problem_number = enriched_data.get("problem_number", "")
    problem_name = enriched_data.get("problem_name") or classification.get("title", "Untitled Note")
    pattern = enriched_data.get("pattern") or classification.get("dsa_pattern", "arrays")
    difficulty = enriched_data.get("difficulty", "")
    time_complexity = enriched_data.get("time_complexity", "")
    space_complexity = enriched_data.get("space_complexity", "")
    companies = enriched_data.get("companies", []) or []
    edge_cases = enriched_data.get("edge_cases", []) or []
    similar_problems = enriched_data.get("similar_problems", []) or []

    edge_cases_lines = "\n".join(f"- {item}" for item in edge_cases) or "<!-- Add edge cases -->"
    similar_lines = "\n".join(f"- {item}" for item in similar_problems) or "<!-- Add similar problems -->"
    companies_lines = "\n".join(f"- {item}" for item in companies) if companies else "<!-- Add if known -->"

    tags = classification.get("tags", [])
    tags_json = json.dumps(tags)
    companies_json = json.dumps(companies)

    return f'''---
title: "{problem_name}"
date: {date_value}
domain: dsa
subdomain: {pattern}
type: dsa
tags: {tags_json}
source: leetcode
problem_number: "{problem_number}"
pattern: "{pattern}"
difficulty: "{difficulty}"
time_complexity: "{time_complexity}"
space_complexity: "{space_complexity}"
companies: {companies_json}
reviewed: false
---

# {problem_number} {problem_name}

## Pattern
{pattern}

## Problem Statement
{leetcode_data['problem_summary'] if leetcode_data else '<!-- Add problem statement -->'}

## LeetCode Link
{leetcode_data['url'] if leetcode_data else '<!-- Add URL -->'}

## Difficulty
{difficulty}

## My Notes
{text}

## Approach
{enriched_data.get("approach", "")}

## Key Insight
{enriched_data.get("key_insight", "")}

## Complexity
| | Value |
|---|---|
| Time | {time_complexity} |
| Space | {space_complexity} |

## Solution
```python
# Write your solution here
```

## Edge Cases
{edge_cases_lines}

## Common Mistakes
{enriched_data.get("mistakes_to_avoid", "")}

## Similar Problems
{similar_lines}

## Companies
{companies_lines}

## Related Patterns
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Pattern: {pattern} | Jarvis DSA*
'''
