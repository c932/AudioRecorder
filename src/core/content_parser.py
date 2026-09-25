import pdfplumber
import fitz  # PyMuPDF for rendering PDF pages to images
import re
import os
import json
import base64
import mimetypes
import io


def _normalize_openai_base_url(base_url: str) -> str:
    """Ensure base_url ends with '/v1' so the OpenAI SDK can correctly build
    '/chat/completions'. If user input lacks the suffix, append it.
    Most OpenAI-compatible servers (llama.cpp, vLLM, Ollama, OpenAI) expose
    '/v1/chat/completions', so a missing '/v1' yields a 404 {"detail":"Not Found"}.
    """
    if not base_url:
        return base_url
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"
    return base_url


def _get_llm_client_and_model(config):
    """
    Returns (OpenAI_client, model_name) based on config's ai_provider.
    Unified helper shared across parse methods.
    """
    from openai import OpenAI
    
    provider = config.get("ai_provider", "")
    
    if "Custom" in provider:
        base_url = _normalize_openai_base_url(config.get("custom_base", "http://localhost:8080/v1"))
        api_key = config.get("custom_key") or "not-needed"
        model = config.get("custom_model", "")
        if not model:
            raise RuntimeError("Custom model name not configured. Please set it in Settings > AI Engine.")
        return OpenAI(base_url=base_url, api_key=api_key), model
        
    elif "Ollama" in provider:
        base_url = _normalize_openai_base_url(config.get("ollama_base", "http://localhost:11434/v1"))
        api_key = "ollama"
        model = config.get("ollama_model", "qwen2.5")
        return OpenAI(base_url=base_url, api_key=api_key), model
        
    elif "OpenAI" in provider:
        base_url = _normalize_openai_base_url(config.get("openai_base", "https://api.openai.com/v1"))
        api_key = config.get("openai_key", "")
        model = config.get("openai_model", "gpt-4o")
        if not api_key:
            raise RuntimeError("OpenAI API key not configured.")
        return OpenAI(base_url=base_url, api_key=api_key), model

    raise RuntimeError(f"No LLM provider configured. ai_provider='{provider}'. Please configure in Settings > AI Engine.")


def _get_omni_client(config):
    """Factory for the MiniCPM-o OmniClient (custom JWT+SSE API).

    Returns an OmniClient instance, or raises if omni is not configured.
    Use this instead of _get_llm_client_and_model when ai_provider is Omni.
    """
    from src.core.omni_client import OmniClient, OmniConfig
    return OmniClient(OmniConfig.from_config(config))


def _is_omni_provider(config) -> bool:
    """True if the config's ai_provider selects the MiniCPM-o omni channel."""
    provider = config.get("ai_provider", "")
    return "Omni" in provider or "MiniCPM" in provider


class ContentParser:
    @staticmethod
    def parse_pdf(file_path, use_ai=False, config=None, model_name=None):
        """
        Parses a PDF file. 
        If use_ai=True, sends text to LLM for smart extraction.
        If PDF is scanned (no text), falls back to multimodal vision-based parsing.
        
        Args:
            file_path: Path to PDF file
            use_ai: Whether to use AI smart parse
            config: Full config dict (from config.json). If None, falls back to model_name + Ollama.
            model_name: Legacy param for backward compatibility (Ollama model name)
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
                
                if full_text.strip():
                    # Text-based PDF: send text to LLM
                    if config:
                        extracted_data = ContentParser._parse_with_llm(full_text, config=config)
                    else:
                        extracted_data = ContentParser._parse_with_llm_legacy(full_text, model_name or "qwen3:4b")
                else:
                    # Scanned PDF: no text extracted, render pages as images and use vision
                    print("[ContentParser] No text extracted, attempting vision-based parsing...")
                    extracted_data = ContentParser._parse_pdf_as_images(file_path, config)
                
        except Exception as e:
            print(f"Error parsing PDF: {e}")
            raise e
            
        return extracted_data

    @staticmethod
    def _parse_pdf_as_images(file_path, config):
        """
        Renders PDF pages as images using PyMuPDF and sends them to a multimodal LLM.
        Used as fallback when pdfplumber cannot extract text (scanned PDFs).
        """
        if not config:
            raise RuntimeError("No configuration provided. Vision-based PDF parsing requires a configured LLM provider.")
        
        # Open PDF with PyMuPDF and render each page to image
        doc = fitz.open(file_path)
        page_images = []
        MAX_PAGES = 20  # Safety limit
        
        for page_idx, page in enumerate(doc):
            if page_idx >= MAX_PAGES:
                break
            # Render page at 150 DPI (good balance of quality vs speed)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("jpeg")
            page_images.append(base64.b64encode(img_bytes).decode("utf-8"))
        
        num_pages = len(page_images)
        doc.close()
        
        if not page_images:
            raise ValueError("PDF has no pages to render.")
        
        print(f"[ContentParser] Rendered {num_pages} PDF page(s) as images for vision parsing.")
        
        # Build multimodal message with all pages
        prompt = """Analyze these PDF page images which contain an English vocabulary list.
Extract all English words/phrases and their Chinese translations.

Rules:
1. Return ONLY a JSON list.
2. Format: [{"text": "word", "phonetic": "", "translation": "meaning"}]
3. If phonetic transcription is visible, include it.
4. Ignore headers, page numbers, and non-vocabulary content.
5. For phrases, keep them as single entries.
6. Process all pages shown and combine the results into one list.
"""
        
        content_parts = [{"type": "text", "text": prompt}]
        for idx, img_b64 in enumerate(page_images):
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })
        
        messages = [
            {"role": "user", "content": content_parts}
        ]
        
        try:
            client, model = _get_llm_client_and_model(config)
        except RuntimeError as e:
            raise RuntimeError(f"Cannot use vision model for scanned PDF: {e}")
        
        print(f"[ContentParser] Sending {num_pages} page image(s) to model: {model}")
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=3000,
                temperature=0.2
            )
            content = response.choices[0].message.content.strip()
            print(f"[ContentParser] Vision LLM response length: {len(content)} chars")
            
            # Robust JSON extraction
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group()
                result = json.loads(json_str)
                if isinstance(result, list) and all(isinstance(item, dict) for item in result):
                    return result
                raise ValueError("LLM returned unexpected JSON structure.")
            else:
                print(f"[ContentParser] Raw vision LLM response:\n{content[:500]}")
                raise ValueError("No JSON list found in vision LLM response. The model may not support vision.")
                
        except Exception as e:
            raise RuntimeError(f"Vision-based PDF parsing failed: {e}")

    @staticmethod
    def parse_image(image_path, config=None):
        """
        Analyzes an image using a multimodal LLM via OpenAI-compatible API.
        Sends image as base64 in the chat completion request (OpenAI vision format).
        
        Args:
            image_path: Path to image file (JPG, PNG, BMP, TIFF)
            config: Full config dict from config.json
            
        Returns: list of {"text": "word", "phonetic": "", "translation": "meaning"}
        """
        if not config:
            raise RuntimeError("No configuration provided. Please configure a Custom or OpenAI provider in Settings.")
        
        # Check file size and compress if needed (>2MB)
        file_size = os.path.getsize(image_path)
        MAX_SIZE = 2 * 1024 * 1024  # 2MB
        
        if file_size > MAX_SIZE:
            image_data = ContentParser._compress_image(image_path)
        else:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        
        # Build prompt for multimodal extraction
        prompt = """Analyze this image which contains an English vocabulary list.
Extract all English words/phrases and their Chinese translations.

Rules:
1. Return ONLY a JSON list.
2. Format: [{"text": "word", "phonetic": "", "translation": "meaning"}]
3. If phonetic transcription is visible, include it.
4. Ignore headers, page numbers, and non-vocabulary content.
5. For phrases, keep them as single entries.
6. If the image is blurry, do your best to read the text.
"""
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}"
                        }
                    }
                ]
            }
        ]
        
        try:
            client, model = _get_llm_client_and_model(config)
        except RuntimeError as e:
            raise RuntimeError(f"Cannot analyze image: {e}")
        
        print(f"[ContentParser] Analyzing image with model: {model}")
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2000,
                temperature=0.2
            )
            content = response.choices[0].message.content.strip()
            print(f"[ContentParser] LLM response length: {len(content)} chars")
            
            # Robust JSON extraction
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group()
                result = json.loads(json_str)
                # Validate structure
                if isinstance(result, list) and all(isinstance(item, dict) for item in result):
                    return result
                raise ValueError("LLM returned unexpected JSON structure.")
            else:
                print(f"[ContentParser] Raw LLM response:\n{content[:500]}")
                raise ValueError("No JSON list found in LLM response. The model may not support vision.")
                
        except Exception as e:
            raise RuntimeError(f"Image analysis failed: {e}")

    @staticmethod
    def _compress_image(image_path):
        """Compress image to reduce base64 payload size. Returns base64 string."""
        try:
            from PIL import Image
            import io
            
            img = Image.open(image_path)
            
            # Resize if width > 1024
            if img.width > 1024:
                ratio = 1024 / img.width
                new_size = (1024, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            
            # Convert to RGB if needed (handles RGBA, palette, etc.)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            buf.seek(0)
            
            return base64.b64encode(buf.read()).decode("utf-8")
            
        except ImportError:
            # PIL not available, just read raw file
            print("[ContentParser] PIL not available, using raw image (may be large)")
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _parse_with_llm(full_text, config=None):
        """
        Uses OpenAI-compatible API (via unified _get_llm_client) to extract vocabulary.
        Works with Ollama, OpenAI, Custom (llama.cpp), etc.
        """
        config = config or {}
        
        chunk = full_text[:2000]  # Limit to 2000 chars for speed
        client, model = _get_llm_client_and_model(config)
        
        print(f"[ContentParser] Sending {len(chunk)} chars to model {model}...")
        
        prompt = f"""Analyze this raw text from a PDF. Extract English vocabulary words and their translations.

Rules:
1. Return ONLY a JSON list.
2. Format: [{{"text": "word", "phonetic": "", "translation": "meaning"}}]
3. Ignore headers like "Treasure Box", "Class Name".
4. If text is messy, do your best to extract valid words.

Raw Text:
{chunk}"""
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.2
            )
            content = response.choices[0].message.content.strip()
            print(f"[ContentParser] LLM response:\n{content[:500]}")
            
            # Robust JSON extraction
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group()
                return json.loads(json_str)
            else:
                raise ValueError("No JSON list found in LLM response.")
                
        except Exception as e:
            print(f"[ContentParser] AI Parse Error: {e}")
            raise RuntimeError(f"LLM Request Failed: {e}")

    @staticmethod
    def _parse_with_llm_legacy(full_text, model_name="qwen3:4b"):
        """
        Legacy fallback: Uses Ollama via raw HTTP request (native /api/chat format).
        Only used when no config is passed (backward compatibility).
        """
        import requests
        
        chunk = full_text[:2000]
        print(f"[ContentParser] Legacy: Sending {len(chunk)} chars to Ollama model {model_name}...")
        
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
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            
            result = response.json()
            content = result.get("message", {}).get("content", "")
            print(f"[ContentParser] Legacy LLM response:\n{content[:500]}")
            
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_str = match.group()
                return json.loads(json_str)
            else:
                raise ValueError("No JSON list found.")
                
        except Exception as e:
            print(f"[ContentParser] Legacy AI Parse Error: {e}")
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
                fused_pos_match = re.search(r'([a-zA-Z]{2,})((?:n|v|adj|adv|prep|conj|pron|num|art|vi|vt)\.?)$', english_part)
                if fused_pos_match:
                     english_part = fused_pos_match.group(1)
                
                phonetic_match = re.search(r'(/[^/]+/|\[[^\]]+\])', english_part)
                if phonetic_match:
                    phonetic = phonetic_match.group(1)
                    english_part = english_part.replace(phonetic, '').strip()
                
                english_part = english_part.lstrip('* \'')

                english_part = re.sub(r'\b(n|v|adj|adv|prep|conj|pron|num|art|vi|vt|aux|modal|pl|abbr)\.?(\/[a-z]+)?\.?\s*$', '', english_part, flags=re.IGNORECASE).strip()
                
                english_part = re.sub(r'\s+\d+$', '', english_part).strip()

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
            
            if current['text'].endswith('('):
                current['text'] = current['text'][:-1].strip()
                current['translation'] = '(' + current['translation']
            
            open_count = current['text'].count('(')
            close_count = current['text'].count(')')
            
            if open_count > close_count and i + 1 < len(raw_items):
                next_item = raw_items[i+1]
                
                next_text = next_item['text']
                if next_text and (next_text[0].islower() or ')' in next_text):
                    current['text'] += " " + next_text
                    current['translation'] += next_item['translation']
                    
                    if not current['phonetic'] and next_item['phonetic']:
                        current['phonetic'] = next_item['phonetic']
                        
                    i += 1
            
            final_results.append(current)
            i += 1
            
        return final_results
