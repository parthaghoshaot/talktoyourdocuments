import json
import logging
import re
from config import llm_chat

logger = logging.getLogger("talktodata.extractor")

EXTRACTION_PROMPT = """You are a knowledge graph extraction engine. Given a text, extract entities and relationships in the SAME LANGUAGE as the input text.

Return ONLY valid JSON in this exact format:
{
  "language": "en|de",
  "entities": [
        {
            "name": "Entity Name",
            "type": "Person|Organization|Process|Document|Concept|Location|Product|Event|Other",
            "description": "Brief description",
            "evidence": "Short exact quote from the text that supports this entity"
        }
  ],
  "relations": [
        {
            "subject": "Entity A",
            "predicate": "relates_to|is_part_of|created_by|requires|produces|manages|contains|uses|defines|depends_on",
            "object": "Entity B",
            "context": "Brief explanation",
            "evidence": "Short exact quote from the text that supports this relation"
        }
  ]
}

Rules:
- Extract ALL meaningful entities (people, organizations, processes, concepts, products, etc.)
- Extract ALL meaningful relationships between entities and texts
- Keep entity names concise and normalized
- Use clear, descriptive predicates for relationships
- Context should be a brief explanation of the relationship
- evidence must be copied exactly from the provided text when possible (<= 220 chars)
- The "language" field must reflect the language of the input text ("en" for English, "de" for German)
- Keep all names, descriptions, and context in the ORIGINAL language of the text
- If the text is too short or has no meaningful entities, return empty arrays
- Do NOT include any text outside the JSON block"""

TRANSLATION_PROMPT = """You are a translation engine for knowledge graph data. Translate the following JSON entities and relations from {source_lang} to {target_lang}.

Return ONLY valid JSON in the exact same structure, but with all text fields translated to {target_lang} and should be meaningful.
Keep the "type" and "predicate" fields unchanged (they are standardized English terms).
Translate: name, description, subject, object, context fields.

Input JSON:
{json_data}"""


def extract_knowledge(text, chunk_size=3000):
    chunks = split_into_chunks(text, chunk_size=chunk_size)
    all_entities = []
    all_relations = []
    detected_language = "en"
    logger.info(f"Extracting knowledge: {len(chunks)} chunk(s), {len(text)} chars total")

    for i, chunk in enumerate(chunks):
        chunk_text = chunk["text"]
        if len(chunk_text.strip()) < 50:
            continue
        relevance = score_chunk_relevance(chunk_text)
        if relevance < 0.15:
            logger.info(
                f"  Chunk {i+1}/{len(chunks)} skipped: low relevance score={relevance:.2f}"
            )
            continue
        logger.info(f"  Chunk {i+1}/{len(chunks)}: {len(chunk_text)} chars -> calling LLM for extraction")
        entities, relations, lang = extract_from_chunk(chunk_text)
        logger.info(f"  Chunk {i+1} result: {len(entities)} entities, {len(relations)} relations, lang={lang}")
        for entity in entities:
            entity["source_chunk"] = chunk["chunk_index"]
            entity["source_excerpt"] = entity.get("evidence") or chunk_text[:300]
        for relation in relations:
            relation["source_chunk"] = chunk["chunk_index"]
            relation["source_excerpt"] = relation.get("evidence") or chunk_text[:300]
        all_entities.extend(entities)
        all_relations.extend(relations)
        if lang != "en":
            detected_language = lang

    all_entities = deduplicate_entities(all_entities)
    all_relations = normalize_and_deduplicate_relations(all_relations, all_entities)
    logger.info(f"After dedup: {len(all_entities)} unique entities")

    if detected_language != "en":
        logger.info(f"Translating KG data from {detected_language} -> en")
        all_entities, all_relations = add_translations(
            all_entities, all_relations, detected_language, "en"
        )
    else:
        logger.info("Translating KG data from en -> de")
        all_entities, all_relations = add_translations(
            all_entities, all_relations, "en", "de"
        )

    return all_entities, all_relations, detected_language


def extract_from_chunk(chunk):
    messages = [{"role": "user", "content": f"Extract knowledge graph from this text:\n\n{chunk}"}]
    try:
        response = llm_chat(messages, system_prompt=EXTRACTION_PROMPT)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            response = response.rsplit("```", 1)[0]
        data = json.loads(response)
        language = data.get("language", "en")
        entities = data.get("entities", [])
        relations = data.get("relations", [])
        valid_entities = [e for e in entities if "name" in e and "type" in e]
        valid_relations = [r for r in relations if "subject" in r and "predicate" in r and "object" in r]
        return valid_entities, valid_relations, language
    except (json.JSONDecodeError, KeyError, TypeError):
        return [], [], "en"


def add_translations(entities, relations, source_lang, target_lang):
    data_to_translate = {
        "entities": [{"name": e["name"], "description": e.get("description", "")} for e in entities],
        "relations": [{"subject": r["subject"], "object": r["object"], "context": r.get("context", "")} for r in relations]
    }

    lang_names = {"en": "English", "de": "German"}
    prompt = TRANSLATION_PROMPT.format(
        source_lang=lang_names.get(source_lang, source_lang),
        target_lang=lang_names.get(target_lang, target_lang),
        json_data=json.dumps(data_to_translate, ensure_ascii=False)
    )

    logger.info(f"  Translation LLM call: {source_lang} -> {target_lang} ({len(entities)} entities, {len(relations)} relations)")
    messages = [{"role": "user", "content": prompt}]
    try:
        response = llm_chat(messages, system_prompt="You are a precise translator. Return only valid JSON.")
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            response = response.rsplit("```", 1)[0]
        translated = json.loads(response)

        translated_entities = translated.get("entities", [])
        for i, e in enumerate(entities):
            if i < len(translated_entities):
                e["name_translated"] = translated_entities[i].get("name", "")
                e["description_translated"] = translated_entities[i].get("description", "")

        translated_relations = translated.get("relations", [])
        for i, r in enumerate(relations):
            if i < len(translated_relations):
                r["subject_translated"] = translated_relations[i].get("subject", "")
                r["object_translated"] = translated_relations[i].get("object", "")
                r["context_translated"] = translated_relations[i].get("context", "")

    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return entities, relations


def split_into_chunks(text, chunk_size):
    normalized = normalize_text(text)
    sections = split_into_sections(normalized)
    chunks = []
    overlap_sentences = 2

    for section in sections:
        section_chunks = build_chunks_from_section(section, chunk_size, overlap_sentences)
        chunks.extend(section_chunks)

    return [{"chunk_index": i, "text": c} for i, c in enumerate(chunks)]


def deduplicate_entities(entities):
    seen = {}
    for e in entities:
        key = e["name"].lower().strip()
        if key not in seen:
            seen[key] = e
        else:
            if len(e.get("description", "")) > len(seen[key].get("description", "")):
                seen[key] = e
    return list(seen.values())


def normalize_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def split_long_paragraph(paragraph, chunk_size):
    if len(paragraph) <= chunk_size:
        return [paragraph]

    parts = []
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    current = []
    current_len = 0

    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                parts.append(" ".join(current))
                current = []
                current_len = 0
            for i in range(0, len(sentence), chunk_size):
                parts.append(sentence[i:i + chunk_size])
            continue

        if current_len + len(sentence) + 1 > chunk_size and current:
            parts.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1

    if current:
        parts.append(" ".join(current))

    return parts


def split_into_sections(text):
    lines = text.split("\n")
    sections = []
    current = []

    def flush_current():
        if current:
            section_text = "\n".join(current).strip()
            if section_text:
                sections.append(section_text)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                current.append(line)
            continue

        if is_structure_marker(stripped):
            flush_current()
            current = [stripped]
            continue

        if current and len("\n".join(current)) > 2400 and is_heading_like(stripped):
            flush_current()
            current = [stripped]
            continue

        current.append(stripped)

    flush_current()
    return sections


def is_structure_marker(line):
    return bool(
        re.match(r"^\[(Page\s+\d+|Slide\s+\d+|Sheet:\s+[^\]]+)\]$", line)
    )


def is_heading_like(line):
    if len(line) > 100:
        return False
    if line.endswith(":"):
        return True
    return bool(re.match(r"^[A-Z0-9][A-Za-z0-9 \-_/]{2,80}$", line))


def build_chunks_from_section(section_text, chunk_size, overlap_sentences=2):
    sentences = split_into_sentences(section_text)
    if not sentences:
        return [section_text]

    chunks = []
    current_sentences = []
    current_len = 0

    for sentence in sentences:
        if len(sentence) > chunk_size:
            long_parts = split_long_paragraph(sentence, chunk_size)
            for part in long_parts:
                if current_sentences:
                    chunks.append(" ".join(current_sentences).strip())
                    current_sentences = []
                    current_len = 0
                chunks.append(part.strip())
            continue

        should_break = current_sentences and (
            current_len + len(sentence) + 1 > chunk_size
            or should_start_new_chunk(current_sentences, sentence, current_len, chunk_size)
        )
        if should_break:
            chunk_text = " ".join(current_sentences).strip()
            chunks.append(chunk_text)
            carry = current_sentences[-overlap_sentences:] if overlap_sentences > 0 else []
            current_sentences = list(carry)
            current_len = sum(len(s) + 1 for s in current_sentences)

        current_sentences.append(sentence)
        current_len += len(sentence) + 1

    if current_sentences:
        chunks.append(" ".join(current_sentences).strip())

    return [c for c in chunks if c]


def split_into_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def should_start_new_chunk(current_sentences, next_sentence, current_len, chunk_size):
    if current_len < max(700, int(chunk_size * 0.35)):
        return False
    current_tokens = lexical_tokens(" ".join(current_sentences[-5:]))
    next_tokens = lexical_tokens(next_sentence)
    if not current_tokens or not next_tokens:
        return False
    overlap = len(current_tokens.intersection(next_tokens)) / max(len(next_tokens), 1)
    return overlap < 0.08


def lexical_tokens(text):
    return {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) > 2}


def score_chunk_relevance(chunk_text):
    tokens = re.findall(r"[A-Za-z0-9_]+", chunk_text)
    if len(tokens) < 20:
        return 0.0

    unique_ratio = len(set(t.lower() for t in tokens)) / max(len(tokens), 1)
    alpha_ratio = sum(1 for t in tokens if re.search(r"[A-Za-z]", t)) / max(len(tokens), 1)

    marker_lines = 0
    lines = [l.strip() for l in chunk_text.split("\n") if l.strip()]
    for line in lines:
        if is_structure_marker(line) or is_heading_like(line):
            marker_lines += 1
    marker_penalty = min(marker_lines / max(len(lines), 1), 0.35)

    score = (0.55 * unique_ratio) + (0.45 * alpha_ratio) - marker_penalty
    return max(0.0, min(score, 1.0))


def normalize_entity_name(name):
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def normalize_and_deduplicate_relations(relations, entities):
    canonical_names = {}
    for e in entities:
        canonical_names[normalize_entity_name(e.get("name", ""))] = e.get("name", "")

    deduped = {}
    for relation in relations:
        subj = relation.get("subject", "").strip()
        obj = relation.get("object", "").strip()
        pred = relation.get("predicate", "").strip()
        if not subj or not obj or not pred:
            continue

        subj = canonical_names.get(normalize_entity_name(subj), subj)
        obj = canonical_names.get(normalize_entity_name(obj), obj)
        relation["subject"] = subj
        relation["object"] = obj

        key = (
            normalize_entity_name(subj),
            normalize_entity_name(pred),
            normalize_entity_name(obj),
            normalize_entity_name(relation.get("context", "")),
        )
        if key not in deduped:
            deduped[key] = relation
        else:
            existing = deduped[key]
            if len(relation.get("context", "")) > len(existing.get("context", "")):
                deduped[key] = relation

    return list(deduped.values())
