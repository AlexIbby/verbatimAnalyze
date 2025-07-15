from flask import Blueprint, request, jsonify, current_app
from openai import OpenAI
import pandas as pd
import time
import threading
import json
import redis
from concurrent.futures import ThreadPoolExecutor, as_completed
from routes.upload import upload_sessions, get_redis_client

classify_bp = Blueprint('classify', __name__)

def store_progress(session_id, progress_data):
    """Store classification progress in Redis"""
    r = get_redis_client()
    r.set(f"progress:{session_id}", json.dumps(progress_data), ex=86400)  # 24 hours

def get_progress(session_id):
    """Get classification progress from Redis"""
    r = get_redis_client()
    progress_data = r.get(f"progress:{session_id}")
    if progress_data:
        return json.loads(progress_data)
    return None

def progress_exists(session_id):
    """Check if progress exists in Redis"""
    r = get_redis_client()
    return r.exists(f"progress:{session_id}")

# Legacy global variable for backward compatibility
classification_progress = type('ClassificationProgress', (), {
    '__contains__': lambda self, session_id: progress_exists(session_id),
    '__getitem__': lambda self, session_id: get_progress(session_id),
    '__setitem__': lambda self, session_id, data: store_progress(session_id, data)
})()

@classify_bp.route('/sessions/<session_id>/classify', methods=['POST'])
def classify_comments(session_id):
    """Start classification process in background and return immediately"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if not session.get('categories'):
            return jsonify({'error': 'Categories not defined. Please generate categories first.'}), 400
        
        df = session['dataframe']
        verbatim_col = session['verbatim_column']
        categories = session['categories']
        
        if not verbatim_col or verbatim_col not in df.columns:
            return jsonify({'error': 'Verbatim column not set or invalid'}), 400
        
        # Check if classification is already in progress
        if session_id in classification_progress:
            current_progress = classification_progress[session_id]
            if current_progress.get('status') == 'processing':
                return jsonify({'error': 'Classification already in progress'}), 409
        
        # Initialize progress tracking
        classification_progress[session_id] = {
            'status': 'starting',
            'progress': 0,
            'total': len(df),
            'current_step': 'Preparing classification...',
            'completed': False
        }
        
        # Start classification in background thread
        thread = threading.Thread(
            target=perform_classification_background,
            args=(session_id, df, verbatim_col, categories)
        )
        thread.daemon = True
        thread.start()
        
        # Return immediately with 202 Accepted
        return jsonify({
            'session_id': session_id,
            'status': 'accepted',
            'message': 'Classification started. Check /classify/progress for updates.'
        }), 202
        
    except Exception as e:
        current_app.logger.error(f"Classification error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

def perform_classification_background(session_id, df, verbatim_col, categories):
    """Background task for classification"""
    try:
        # Update status to processing
        classification_progress[session_id] = {
            'status': 'processing',
            'progress': 0,
            'total': len(df),
            'current_step': 'Starting classification...',
            'completed': False
        }
        
        # Perform classification
        classified_df = perform_classification(df, verbatim_col, categories, session_id)
        
        # Store classified data back to session
        session = upload_sessions[session_id]
        session['classified_data'] = classified_df
        upload_sessions[session_id] = session
        
        # Mark as completed
        classification_progress[session_id] = {
            'status': 'completed',
            'progress': 100,
            'total': len(df),
            'current_step': 'Classification completed',
            'completed': True
        }
        
    except Exception as e:
        current_app.logger.error(f"Background classification failed: {e}")
        classification_progress[session_id] = {
            'status': 'failed',
            'progress': 0,
            'total': len(df),
            'current_step': f'Classification failed: {str(e)}',
            'completed': False,
            'error': str(e)
        }

@classify_bp.route('/sessions/<session_id>/classify/progress', methods=['GET'])
def get_classification_progress(session_id):
    """Get the progress of classification process"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        # Return progress if available, otherwise default status
        if session_id in classification_progress:
            return jsonify(classification_progress[session_id]), 200
        else:
            return jsonify({
                'status': 'not_started',
                'progress': 0,
                'total': 0,
                'current_step': 'Not started',
                'completed': False
            }), 200
        
    except Exception as e:
        current_app.logger.error(f"Progress check error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@classify_bp.route('/sessions/<session_id>/classify/status', methods=['GET'])
def get_classification_status(session_id):
    """Get the status of classification process"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        status = {
            'session_id': session_id,
            'has_categories': session.get('categories') is not None,
            'has_classifications': session.get('classified_data') is not None,
            'total_rows': session['total_rows']
        }
        
        if session.get('classified_data') is not None:
            df = session['classified_data']
            status['category_counts'] = df['Comment Category'].value_counts().to_dict()
        
        return jsonify(status), 200
        
    except Exception as e:
        current_app.logger.error(f"Status check error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

def perform_classification(df, verbatim_col, categories, session_id):
    """Perform the actual classification of comments"""
    # Create a copy of the dataframe
    classified_df = df.copy()
    
    # Update progress
    classification_progress[session_id]['current_step'] = 'Analyzing comments...'
    classification_progress[session_id]['progress'] = 10
    
    # Get non-empty comments
    comments = df[verbatim_col].dropna().astype(str)
    comments = comments[comments.str.len() > 0]
    
    if len(comments) == 0:
        # If no comments, create empty category column
        classified_df['Comment Category'] = 'No Comment'
        classification_progress[session_id]['progress'] = 90
        return classified_df
    
    # Prepare category titles for LLM
    category_titles = [cat['title'] for cat in categories]
    
    # Update progress
    classification_progress[session_id]['current_step'] = 'Classifying comments...'
    classification_progress[session_id]['progress'] = 20
    
    # Initialize results
    classifications = {}
    
    if current_app.config.get('OPENAI_API_KEY'):
        # Use OpenAI for classification
        classifications = classify_with_llm(comments, category_titles, session_id)
    else:
        # Fallback to simple keyword matching
        classifications = classify_with_keywords(comments, categories, session_id)
    
    # Update progress
    classification_progress[session_id]['current_step'] = 'Finalizing results...'
    classification_progress[session_id]['progress'] = 90
    
    # Apply classifications to dataframe
    classified_df['Comment Category'] = classified_df.apply(
        lambda row: get_classification_for_row(row, verbatim_col, classifications, category_titles[0]),
        axis=1
    )
    
    return classified_df

def classify_with_llm(comments, category_titles, session_id):
    """Classify comments using OpenAI API with batching for efficiency"""
    client = OpenAI(api_key=current_app.config['OPENAI_API_KEY'])
    classifications = {}
    
    # Prepare system message
    system_message = f"""You label comments. 
RULES:
1. Choose ONE of the following categories exactly: {', '.join(category_titles)}.
2. Output only that category title.
3. If the comment is unclear or doesn't fit any category well, choose the closest match."""
    
    # Process comments in batches to respect rate limits
    batch_size = 20
    comment_list = comments.tolist()
    comment_indices = comments.index.tolist()
    total_batches = len(range(0, len(comment_list), batch_size))
    
    for batch_num, i in enumerate(range(0, len(comment_list), batch_size)):
        batch_comments = comment_list[i:i + batch_size]
        batch_indices = comment_indices[i:i + batch_size]
        
        # Update progress
        progress = 20 + int((batch_num / total_batches) * 60)  # Progress from 20% to 80%
        classification_progress[session_id]['progress'] = progress
        classification_progress[session_id]['current_step'] = f'Processing batch {batch_num + 1} of {total_batches}...'
        
        # Use ThreadPoolExecutor for parallel API calls within the batch
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(classify_single_comment, client, system_message, comment): idx
                for comment, idx in zip(batch_comments, batch_indices)
            }
            
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    classification = future.result()
                    classifications[idx] = classification
                except Exception as e:
                    current_app.logger.error(f"Failed to classify comment {idx}: {e}")
                    classifications[idx] = category_titles[0]  # Default to first category
        
        # Small delay between batches to respect rate limits
        if i + batch_size < len(comment_list):
            time.sleep(0.5)
    
    return classifications

def classify_single_comment(client, system_message, comment):
    """Classify a single comment using OpenAI API"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": str(comment)}
            ],
            max_tokens=20,
            temperature=0
        )
        
        result = response.choices[0].message.content.strip()
        return result
        
    except Exception as e:
        current_app.logger.error(f"Single comment classification failed: {e}")
        raise e

def classify_with_keywords(comments, categories, session_id):
    """Fallback classification using keyword matching"""
    classifications = {}
    
    # Create keyword mappings for each category
    keyword_map = {}
    for cat in categories:
        title = cat['title']
        description = cat['description'].lower()
        
        # Extract keywords from title and description
        keywords = []
        keywords.extend(title.lower().split())
        
        # Add some common keywords based on category names
        if 'wait' in title.lower() or 'time' in title.lower():
            keywords.extend(['wait', 'delay', 'slow', 'queue', 'appointment', 'booking'])
        elif 'service' in title.lower() or 'quality' in title.lower():
            keywords.extend(['service', 'staff', 'quality', 'professional', 'helpful'])
        elif 'access' in title.lower():
            keywords.extend(['access', 'parking', 'disabled', 'wheelchair', 'stairs'])
        elif 'communication' in title.lower():
            keywords.extend(['information', 'explain', 'told', 'communication', 'contact'])
        elif 'positive' in title.lower() or 'good' in title.lower():
            keywords.extend(['good', 'great', 'excellent', 'thank', 'appreciate', 'helpful'])
        elif 'process' in title.lower():
            keywords.extend(['process', 'paperwork', 'form', 'system', 'procedure'])
        
        keyword_map[title] = keywords
    
    # Classify each comment with progress tracking
    total_comments = len(comments)
    for i, (idx, comment) in enumerate(comments.items()):
        # Update progress every 50 comments
        if i % 50 == 0:
            progress = 20 + int((i / total_comments) * 60)  # Progress from 20% to 80%
            classification_progress[session_id]['progress'] = progress
            classification_progress[session_id]['current_step'] = f'Classifying comment {i + 1} of {total_comments}...'
        
        comment_lower = str(comment).lower()
        best_category = categories[0]['title']  # Default
        max_matches = 0
        
        for cat_title, keywords in keyword_map.items():
            matches = sum(1 for keyword in keywords if keyword in comment_lower)
            if matches > max_matches:
                max_matches = matches
                best_category = cat_title
        
        classifications[idx] = best_category
    
    return classifications

def get_classification_for_row(row, verbatim_col, classifications, default_category):
    """Get classification for a specific row"""
    comment = row[verbatim_col]
    
    # Check if comment is empty or null
    if pd.isna(comment) or str(comment).strip() == '':
        return 'No Comment'
    
    # Get classification from our results
    return classifications.get(row.name, default_category)