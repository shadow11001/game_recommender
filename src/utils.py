import re

def normalize_title(title: str) -> str:
    """
    Normalizes a game title for easier matching.
    - Lowercase
    - Removes content in brackets/parentheses (e.g., 'Game (GOTY Edition)' -> 'game')
    - Removes special characters
    """
    if not title:
        return ""
    
    # Lowercase
    t = title.lower()
    
    # Remove things in brackets [] or parentheses ()
    t = re.sub(r'\[.*?\]', '', t)
    t = re.sub(r'\(.*?\)', '', t)
    
    # Replace common copyright/trademark symbols with space to avoid word fusion
    t = re.sub(r'[©®™℠]', ' ', t)

    # Remove special characters (keep alphanumeric and spaces)
    t = re.sub(r'[^a-z0-9\s]', '', t)
    
    # Collapse multiple spaces
    t = re.sub(r'\s+', ' ', t).strip()
    
    return t
