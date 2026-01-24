import pdfplumber
import re
import os
import json

class ContentParser:
    @staticmethod
    def parse_pdf(file_path, use_ai=False, model_name="qwen3:4b"):
        """
        Parses a PDF file. 
        If use_ai=True, sends text to Ollama for smart extraction.
        """
        extracted_data = []
        full_text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        if use_ai:
                            # Clean text immediately to avoid huge blocks of whitespace
                            cleaned = text.strip()
                            if cleaned:
                                full_text += cleaned + "\n\n"
                        else:
                            lines = text.split('\n')
                            extracted_data.extend(ContentParser._parse_lines(lines))
            
            if use_ai:
                print(f"DEBUG: Captured {len(full_text)} chars from PDF.")
                if not full_text.strip():
                    raise ValueError("No text extracted from PDF. Is it a scanned image? Text-based AI requires selectable text.")
                extracted_data = ContentParser._parse_with_llm(full_text, model_name)
                
        except Exception as e:
            print(f"Error parsing PDF: {e}")
            raise e
            
        return extracted_data

    @staticmethod
    def _parse_with_llm(full_text, model_name="qwen3:4b"):
        """
        Uses Ollama via raw HTTP request to extract structured vocabulary.
        """
        import requests
        import json
        
        # Limit text
        chunk = full_text[:2000] # Reduced to 2000 to be faster
        print(f"DEBUG: Sending {len(chunk)} chars to model {model_name}...")
        print(f"DEBUG INPUT SNIPPET: {chunk[:200]}...") # Show what we send
        
        url = "http://localhost:11434/api/chat"
        
        prompt = f"""
        Analyze this raw text from a PDF. Extract English vocabulary words and their translations.
        
        Rules:
        1. Return ONLY a JSON list.
        2. Format: [{{"text": "word", "phonetic": "", "translation": "meaning"}}]
        3. Ignore headers like "Treasure Box", "Class Name".
        4. If text is messy, do your best to extract valid words.
        
        Raw Text:
        {chunk}
        """
        
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2}
        }
        
        try:
            # Increased timeout to 300s (5 min) because local LLM can be slow
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            
            result = response.json()
            content = result.get("message", {}).get("content", "")
            
            print(f"DEBUG RAW LLM RESPONSE:\n{content}") 
            
            # Robust JSON extraction
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group()
                return json.loads(json_str)
            else:
                # Fallback: maybe it returned a list not inside []?
                raise ValueError("No JSON list found.")
                
        except Exception as e:
            print(f"AI Parse Error: {e}")
            raise RuntimeError(f"Ollama Request Failed: {e}")

    @staticmethod
    def _parse_lines(lines):
        # Pass 1: Extract all raw items 
        raw_items = []
        re_chinese = re.compile(r'[\u4e00-\u9fff]+')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 1. Blocklist Filters
            if re.search(r'^(Class|Name|No\.|Treasure\s*Box|Unit\s*\d+|Page\s*\d+|序号)', line, re.IGNORECASE):
                continue
            if "英文" in line and "中文" in line:
                continue

            # 2. Key Heuristic: Valid items MUST have a Chinese translation
            if not re_chinese.search(line):
                continue
                
            # 3. Cleanup Leading Junk
            clean_line = re.sub(r'^(\d+|No\.?|•|-|\^|\*)\s*[.,;]?\s*', '', line).strip()
            clean_line = clean_line.lstrip('.,;!?-^ *')
            
            if not clean_line:
                continue

            # 4. Split English vs Chinese
            match = re_chinese.search(clean_line)
            if match:
                zh_start = match.start()
                
                english_part = clean_line[:zh_start].strip()
                translation_part = clean_line[zh_start:].strip()
                
                # Further cleanup
                phonetic = ""
                
                # FIX: Handle fused POS tags like "entryn." -> "entry" "n."
                # Regex looks for: 2+ letters + (n.|v.|adj.|...) at end of string
                # This must run BEFORE phonetic check because sometimes phonetic follows
                fused_pos_match = re.search(r'([a-zA-Z]{2,})((?:n|v|adj|adv|prep|conj|pron|num|art|vi|vt)\.?)$', english_part)
                if fused_pos_match:
                     english_part = fused_pos_match.group(1) # Keep only the word part
                
                phonetic_match = re.search(r'(/[^/]+/|\[[^\]]+\])', english_part)
                if phonetic_match:
                    phonetic = phonetic_match.group(1)
                    english_part = english_part.replace(phonetic, '').strip()
                
                # Cleanup: remove leading asterisks again from English part if split left some
                # Also remove leading apostrophes (') as requested
                english_part = english_part.lstrip('* \'')

                # Cleanup Part of Speech (n., v., adj., etc.)
                # Use \b to ensure we match whole words, allowing for optional dot
                # Expanded list: n, v, adj, adv, prep, conj, pron, num, art, vi, vt, aux, modal, pl, abbr
                english_part = re.sub(r'\b(n|v|adj|adv|prep|conj|pron|num|art|vi|vt|aux|modal|pl|abbr)\.?(\/[a-z]+)?\.?\s*$', '', english_part, flags=re.IGNORECASE).strip()
                
                # Cleanup Trailing Numbers (e.g. "break 15")
                # Remove a number at the very end of the English string
                english_part = re.sub(r'\s+\d+$', '', english_part).strip()

                # Cleanup Translation Part (Aggressive Splitter)
                split_match = re.search(r'\s+\d+\s+[a-zA-Z]', translation_part)
                if split_match:
                    translation_part = translation_part[:split_match.start()].strip()
                    
                header_match = re.search(r'\s+(Treasure\s+Box|Unit\s+\d|Page\s+\d)', translation_part, re.IGNORECASE)
                if header_match:
                    translation_part = translation_part[:header_match.start()].strip()
                    
                english_segments = list(re.finditer(r'(\s+[a-zA-Z\s\']+)', translation_part))
                cut_index = -1
                for seg in english_segments:
                    text_seg = seg.group(1).strip()
                    if len(text_seg) < 2: continue
                    if text_seg.startswith('(') and text_seg.endswith(')'): continue
                    if text_seg.lower() in ['sb.', 'sth.', 'sb', 'sth', 'do sth.', 'do sth']: continue
                    if re.search(r'[a-zA-Z]{2,}', text_seg):
                         cut_index = seg.start()
                         break
                
                if cut_index != -1:
                    translation_part = translation_part[:cut_index].strip()
                
                # Force remove start-of-line numbering
                english_part = re.sub(r'^\d+\.?\s*', '', english_part).strip()
                english_part = english_part.replace('*', '').strip()

                if english_part and len(english_part) > 0:
                     raw_items.append({
                        "text": english_part,
                        "phonetic": phonetic,
                        "translation": translation_part
                    })
        
        # Pass 2: Logic Fixes (Merging and Corrections)
        final_results = []
        i = 0
        while i < len(raw_items):
            current = raw_items[i]
            
            # Logic A: Move trailing "(" to translation
            # e.g. "be old enough (" -> "be old enough", Trans: "(年..."
            if current['text'].endswith('('):
                current['text'] = current['text'][:-1].strip()
                current['translation'] = '(' + current['translation']
            
            # Logic B: Merge Split Lines
            # Condition: Unbalanced parentheses in English part
            # e.g. "share sth. (share" ... next line "with sb.)"
            open_count = current['text'].count('(')
            close_count = current['text'].count(')')
            
            if open_count > close_count and i + 1 < len(raw_items):
                next_item = raw_items[i+1]
                
                # Check eligibility for merge
                # 1. Next start with lowercase OR 2. Next has ')' to help balance
                next_text = next_item['text']
                if next_text and (next_text[0].islower() or ')' in next_text):
                    # Merge
                    current['text'] += " " + next_text
                    current['translation'] += next_item['translation'] # Append translation directly
                    
                    # Update phonetic if missing in current but present in next (rare but possible)
                    if not current['phonetic'] and next_item['phonetic']:
                        current['phonetic'] = next_item['phonetic']
                        
                    i += 1 # Skip next item as it is merged
            
            # Final Safety: Remove any residual digits that might have been part of merged content?
            # (Usually not needed if Pass 1 is clean)
            
            final_results.append(current)
            i += 1
            
        return final_results
