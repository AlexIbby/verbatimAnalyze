import pandas as pd
import re
import os
from openai import OpenAI
from flask import current_app

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def detect_verbatim_col(df):
    """
    Detect verbatim column using three-step strategy:
    1. Strict match for known headers
    2. Heuristic: long free-text + keyword matching
    3. LLM fallback
    """
    # Step 1: Strict match
    strict_patterns = [
        "how can we improve this service",
        "comments",
        "feedback",
        "verbatim"
    ]
    
    for col in df.columns:
        col_clean = col.strip().lower()
        if any(pattern in col_clean for pattern in strict_patterns):
            return col, True
    
    # Step 2: Heuristic approach
    long_cols = []
    keyword_cols = []
    
    for col in df.columns:
        # Check average cell length (convert to string first)
        avg_length = df[col].astype(str).str.len().mean()
        if avg_length > 25:
            long_cols.append(col)
        
        # Check for keywords
        if re.search(r"(improve|comment|feedback|verbatim|suggestion|opinion)", col, re.I):
            keyword_cols.append(col)
    
    # Prefer columns that are both long and contain keywords
    candidates = list(set(long_cols) & set(keyword_cols))
    if not candidates:
        candidates = long_cols or keyword_cols
    
    if len(candidates) == 1:
        return candidates[0], False
    elif len(candidates) > 1:
        # If multiple candidates, prefer the one with longest average text
        best_col = max(candidates, key=lambda col: df[col].astype(str).str.len().mean())
        return best_col, False
    
    # Step 3: LLM fallback
    try:
        col = llm_pick_verbatim(df.head(200))
        if col and col in df.columns:
            return col, False
    except Exception:
        pass
    
    # Final fallback: return first column with some text content
    for col in df.columns:
        if df[col].astype(str).str.len().mean() > 10:
            return col, False
    
    return df.columns[0] if len(df.columns) > 0 else None, False

def llm_pick_verbatim(df_sample):
    """Use OpenAI to identify the verbatim column"""
    if not current_app.config.get('OPENAI_API_KEY'):
        return None
    
    try:
        client = OpenAI(api_key=current_app.config['OPENAI_API_KEY'])
        
        # Prepare sample data
        columns_info = []
        for col in df_sample.columns:
            sample_values = df_sample[col].dropna().astype(str).head(3).tolist()
            avg_length = df_sample[col].astype(str).str.len().mean()
            columns_info.append(f"Column '{col}': avg_length={avg_length:.1f}, samples={sample_values}")
        
        prompt = f"""You are analyzing survey data columns to identify which contains free-text verbatim comments.

Columns information:
{chr(10).join(columns_info)}

Which column most likely contains free-text survey comments or feedback? 
Return only the exact column name, nothing else."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0
        )
        
        result = response.choices[0].message.content.strip()
        # Clean up the response to extract just the column name
        if result.startswith("'") and result.endswith("'"):
            result = result[1:-1]
        if result.startswith('"') and result.endswith('"'):
            result = result[1:-1]
        
        return result if result in df_sample.columns else None
        
    except Exception as e:
        current_app.logger.error(f"LLM verbatim detection failed: {e}")
        return None

def load_excel_file(filepath):
    """Load Excel file with fallback engines for legacy formats"""
    try:
        # Try openpyxl first (for modern .xlsx files)
        if filepath.endswith('.xlsx'):
            return pd.read_excel(filepath, engine='openpyxl')
        elif filepath.endswith('.xls'):
            # Use xlrd for legacy .xls files
            return pd.read_excel(filepath, engine='xlrd')
        elif filepath.endswith('.csv'):
            return pd.read_csv(filepath)
        else:
            raise ValueError("Unsupported file format")
    except Exception as e:
        # If it fails due to IRM protection, return specific error
        if "IRM" in str(e) or "protection" in str(e).lower():
            raise ValueError("IRM-protected. Please remove protection or supply a non-protected copy.")
        raise e