from config import llm_chat
from knowledge_graph import search_entities, search_relations, get_content_links
import os
import re

SYSTEM_PROMPT = """You are a knowledgeable assistant that answers questions based on a knowledge graph extracted from documents.
You will receive relevant entities and relationships from the knowledge graph as context.
Answer the user's question based on this context. If the context doesn't contain enough information, say so clearly.
Always answer in English, even if the original documents were in German.
Be concise and factual. When context includes source evidence, use it to justify key claims."""


def build_context(question, domain=None):
    keywords = extract_keywords(question)
    entities = []
    relations = []

    for kw in keywords:
        entities.extend(search_entities(kw, domain))
        relations.extend(search_relations(kw, domain))

    entities = dedupe_by_key(entities, "id")
    relations = dedupe_by_key(relations, "id")
    entities = rank_entities(question, entities)
    relations = rank_relations(question, relations)

    context_parts = []
    if entities:
        context_parts.append("ENTITIES FOUND:")
        for e in entities[:30]:
            proof = format_evidence(e.get("source_excerpt", ""))
            source = format_source_label(e)
            context_parts.append(
                f"  - {e['name']} ({e['entity_type']}): {e.get('description', '')} {source}"
                + (f"\n    evidence: \"{proof}\"" if proof else "")
            )

    if relations:
        context_parts.append("\nRELATIONSHIPS FOUND:")
        for r in relations[:30]:
            proof = format_evidence(r.get("source_excerpt", ""))
            source = format_source_label(r)
            context_parts.append(
                f"  - {r['subject']} --[{r['predicate']}]--> {r['object']}: {r.get('context', '')} {source}"
                + (f"\n    evidence: \"{proof}\"" if proof else "")
            )

    content_links = get_content_links(domain)
    if content_links:
        relevant_links = [l for l in content_links if any(
            kw in l.get("description", "").lower() for kw in keywords
        )][:10]
        if relevant_links:
            context_parts.append("\nCROSS-REFERENCES:")
            for link in relevant_links:
                context_parts.append(
                    f"  - {link['description']} [{link['link_type']}]: "
                    f"{os.path.basename(link['source_file_a'])} chunk {link['chunk_a']} <-> "
                    f"{os.path.basename(link['source_file_b'])} chunk {link['chunk_b']}"
                )

    if not context_parts:
        context_parts.append("No relevant information found in the knowledge graph for this query.")

    return "\n".join(context_parts), entities, relations


def extract_keywords(question):
    stop_words = {"what", "is", "are", "how", "does", "do", "the", "a", "an", "in", "on", "at",
                  "to", "for", "of", "with", "by", "from", "can", "could", "would", "should",
                  "will", "about", "tell", "me", "please", "explain", "describe", "which", "where",
                  "when", "who", "why", "this", "that", "these", "those", "it", "its", "and", "or",
                  "but", "not", "no", "yes", "i", "you", "we", "they", "he", "she", "my", "your"}
    words = question.lower().replace("?", "").replace(".", "").replace(",", "").split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    phrases = []
    for i in range(len(words) - 1):
        if words[i] not in stop_words or words[i+1] not in stop_words:
            phrases.append(f"{words[i]} {words[i+1]}")
    return keywords + phrases[:5]


def dedupe_by_key(items, key):
    seen = set()
    result = []
    for item in items:
        if item[key] not in seen:
            seen.add(item[key])
            result.append(item)
    return result


def answer_question(question, conversation_history, domain=None):
    context, entities, relations = build_context(question, domain)
    augmented_system = f"{SYSTEM_PROMPT}\n\nKNOWLEDGE GRAPH CONTEXT:\n{context}"
    messages = list(conversation_history)
    messages.append({"role": "user", "content": question})
    response = llm_chat(messages, system_prompt=augmented_system)

    if needs_proof(question):
        proof = build_proof_section(question, entities, relations)
        if proof:
            response = f"{response}\n\n{proof}"
    return response


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def tokenize(text):
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(t) > 2}


def rank_entities(question, entities):
    q_tokens = tokenize(question)
    scored = []
    for item in entities:
        text = " ".join([
            item.get("name", ""), item.get("name_translated", ""),
            item.get("description", ""), item.get("description_translated", ""),
            item.get("source_excerpt", ""),
        ])
        score = overlap_score(q_tokens, tokenize(text))
        if item.get("source_excerpt"):
            score += 1
        score += (item.get("confidence") or 1.0) * 2
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


def rank_relations(question, relations):
    q_tokens = tokenize(question)
    scored = []
    for item in relations:
        text = " ".join([
            item.get("subject", ""), item.get("subject_translated", ""),
            item.get("predicate", ""), item.get("object", ""),
            item.get("object_translated", ""), item.get("context", ""),
            item.get("context_translated", ""), item.get("source_excerpt", ""),
        ])
        score = overlap_score(q_tokens, tokenize(text))
        if item.get("source_excerpt"):
            score += 1
        score += (item.get("confidence") or 1.0) * 2
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


def overlap_score(tokens_a, tokens_b):
    if not tokens_a or not tokens_b:
        return 0
    return len(tokens_a.intersection(tokens_b))


def format_evidence(excerpt):
    cleaned = re.sub(r"\s+", " ", str(excerpt or "")).strip()
    if not cleaned:
        return ""
    return cleaned[:280]


def format_source_label(item):
    citation = format_citation(item)
    domain = item.get("domain", "unknown")
    chunk = item.get("source_chunk")
    chunk_label = f", chunk {chunk}" if chunk is not None else ""
    marker = item.get("source_marker", "")
    marker_label = f", marker: {marker}" if marker else ""
    return f"[domain: {domain}, source: {citation}{chunk_label}{marker_label}]"


def format_citation(item):
    source_file = item.get("source_file", "")
    if not source_file:
        return "unknown"

    file_name = os.path.basename(source_file)
    page = item.get("source_page")
    marker = item.get("source_marker", "")

    if page and str(source_file).lower().endswith(".pdf"):
        return f"[{file_name} p.{page}](file://{source_file}#page={page})"
    if marker:
        return f"[{file_name} {marker}](file://{source_file})"
    return f"[{file_name}](file://{source_file})"


def needs_proof(question):
    q = normalize_text(question)
    triggers = {
        "proof", "source", "sources", "evidence", "citation", "cite", "reference",
        "show document", "prove", "where in", "which document", "back this up",
    }
    return any(t in q for t in triggers)


def build_proof_section(question, entities, relations):
    items = []
    for e in entities[:8]:
        items.append({
            "kind": "entity",
            "label": e.get("name", ""),
            "source": format_source_label(e),
            "citation": format_citation(e),
            "evidence": format_evidence(e.get("source_excerpt", "")),
        })
    for r in relations[:8]:
        items.append({
            "kind": "relation",
            "label": f"{r.get('subject', '')} --[{r.get('predicate', '')}]--> {r.get('object', '')}",
            "source": format_source_label(r),
            "citation": format_citation(r),
            "evidence": format_evidence(r.get("source_excerpt", "")),
        })

    seen = set()
    lines = ["PROOF FROM ORIGINAL DOCUMENTS:"]
    count = 0
    for item in items:
        key = (item["label"], item["source"], item["evidence"])
        if key in seen:
            continue
        seen.add(key)
        if not item["evidence"]:
            continue
        count += 1
        lines.append(f"{count}. {item['label']}")
        lines.append(f"   source: {item['citation']}")
        lines.append(f"   details: {item['source']}")
        lines.append(f"   \"{item['evidence']}\"")
        if count >= 8:
            break

    if count == 0:
        return ""
    return "\n".join(lines)
