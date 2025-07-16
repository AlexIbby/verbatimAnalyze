from flask import Blueprint, request, jsonify, current_app, Response
from openai import AsyncOpenAI
import pandas as pd
import time
import json
import threading
import asyncio
from routes.upload import upload_sessions, classification_progress

classify_bp = Blueprint('classify', __name__)

@classify_bp.route('/sessions/<session_id>/classify', methods=['POST'])
def classify_comments(session_id):
    """Start classification process asynchronously"""
    current_app.logger.info(f"=== CLASSIFY ENDPOINT HIT for session {session_id} ===")
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if not session:
            return jsonify({'error': 'Session data not found. Please upload a file first.'}), 400
        
        if not session.get('categories'):
            return jsonify({'error': 'Categories not defined. Please generate categories first.'}), 400
        
        df = session.get('dataframe')
        verbatim_col = session.get('verbatim_column')
        categories = session.get('categories')
        
        if df is None:
            return jsonify({'error': 'File data not found. Please upload a file first.'}), 400
        
        if not verbatim_col or verbatim_col not in df.columns:
            return jsonify({'error': 'Verbatim column not set or invalid'}), 400
        
        # Check if classification is already in progress
        if session_id in classification_progress:
            current_progress = classification_progress[session_id]
            if current_progress.get('status') == 'processing':
                return jsonify({'error': 'Classification already in progress'}), 409
        
        # Initialize progress tracking
        classification_progress[session_id] = {
            'status': 'processing',
            'progress': 0,
            'total': len(df),
            'current_step': 'Starting classification...',
            'completed': False
        }
        current_app.logger.info(f"Initialized progress tracking for session {session_id}, total rows: {len(df)}")
        
        # Start classification in background thread with app context
        current_app.logger.info(f"Starting background thread for session {session_id}")
        thread = threading.Thread(
            target=perform_classification_async,
            args=(current_app._get_current_object(), df, verbatim_col, categories, session_id)
        )
        thread.daemon = True
        thread.start()
        current_app.logger.info(f"Background thread started for session {session_id}")
        
        # Return immediately with processing status
        return jsonify({
            'session_id': session_id,
            'status': 'processing',
            'message': 'Classification started'
        }), 202
        
    except Exception as e:
        current_app.logger.error(f"Classification error: {e}")
        # Mark as failed
        if session_id in classification_progress:
            classification_progress[session_id] = {
                'status': 'failed',
                'progress': 0,
                'total': classification_progress[session_id].get('total', 0),
                'current_step': f'Classification failed: {str(e)}',
                'completed': False,
                'error': str(e)
            }
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@classify_bp.route('/sessions/<session_id>/progress', methods=['GET'])
def progress_stream(session_id):
    """Server-sent events endpoint for real-time progress updates"""
    def generate():
        if session_id not in upload_sessions:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return
        
        # Stream progress updates
        while True:
            if session_id in classification_progress:
                progress_data = classification_progress[session_id]
                yield f"data: {json.dumps(progress_data)}\n\n"
                
                # Stop streaming when completed or failed
                if progress_data.get('completed') or progress_data.get('status') in ['completed', 'failed']:
                    break
            else:
                # No progress data yet
                yield f"data: {json.dumps({'status': 'not_started', 'progress': 0})}\n\n"
            
            time.sleep(0.5)  # Update every 500ms
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'})

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

def perform_classification_async(app, df, verbatim_col, categories, session_id):
    """Perform classification in background thread with proper error handling"""
    with app.app_context():
        try:
            current_app.logger.info(f"Starting background classification for session {session_id}")
            classified_df = perform_classification(df, verbatim_col, categories, session_id)
            
            # Store classified data back to session
            if session_id in upload_sessions:
                upload_sessions[session_id]['classified_data'] = classified_df
                current_app.logger.info(f"Stored classified data for session {session_id}")
            
            # Mark as completed
            classification_progress[session_id] = {
                'status': 'completed',
                'progress': 100,
                'total': len(df),
                'current_step': 'Classification completed',
                'completed': True
            }
            current_app.logger.info(f"Classification completed for session {session_id}")
            
        except Exception as e:
            current_app.logger.error(f"Background classification error: {e}")
            import traceback
            current_app.logger.error(f"Full traceback: {traceback.format_exc()}")
            # Mark as failed
            classification_progress[session_id] = {
                'status': 'failed',
                'progress': 0,
                'total': classification_progress[session_id].get('total', 0),
                'current_step': f'Classification failed: {str(e)}',
                'completed': False,
                'error': str(e)
            }

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
    
    # Always ensure "No Comment" is available as a category
    if "No Comment" not in category_titles:
        category_titles.append("No Comment")
    
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
        lambda row: get_classification_for_row(row, verbatim_col, classifications, category_titles, categories),
        axis=1
    )
    
    return classified_df

def classify_with_llm(comments, category_titles, session_id):
    """Classify comments using OpenAI API with async batching for efficiency"""
    # Run the async classification in a new event loop
    return asyncio.run(classify_with_llm_async(comments, category_titles, session_id))

async def classify_with_llm_async(comments, category_titles, session_id):
    """Async version of classify_with_llm with improved batching"""
    client = AsyncOpenAI(api_key=current_app.config['OPENAI_API_KEY'])
    classifications = {}
    
    # Semaphore to control concurrent requests (don't exceed rate limits)
    semaphore = asyncio.Semaphore(10)
    
    # Prepare system message for batch processing
    system_message = f"""You are a comment classifier. Classify each comment in the batch.

RULES:
1. Choose ONE of the following categories for each comment: {', '.join(category_titles)}.
2. Output ONLY a JSON array with the category for each comment in order.
3. If a comment is blank, empty, or just whitespace, use "No Comment".
4. If a comment is unclear or doesn't fit any category well, choose the closest match.

Example format: ["Category1", "Category2", "No Comment"]"""
    
    # Process comments in batches - send multiple comments per API call
    batch_size = 15  # Reduced batch size for better JSON parsing reliability
    comment_list = comments.tolist()
    comment_indices = comments.index.tolist()
    total_batches = len(range(0, len(comment_list), batch_size))
    
    # Create tasks for all batches
    tasks = []
    for batch_num, i in enumerate(range(0, len(comment_list), batch_size)):
        batch_comments = comment_list[i:i + batch_size]
        batch_indices = comment_indices[i:i + batch_size]
        
        task = classify_batch_async(client, semaphore, system_message, batch_comments, batch_indices, category_titles, session_id, batch_num, total_batches)
        tasks.append(task)
    
    # Execute all batches concurrently
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    for result in batch_results:
        if isinstance(result, Exception):
            current_app.logger.error(f"Batch classification failed: {result}")
            continue
        if result:
            classifications.update(result)
    
    return classifications

async def classify_batch_async(client, semaphore, system_message, batch_comments, batch_indices, category_titles, session_id, batch_num, total_batches):
    """Classify a batch of comments asynchronously"""
    async with semaphore:
        try:
            # Update progress
            progress = 20 + int((batch_num / total_batches) * 60)  # Progress from 20% to 80%
            classification_progress[session_id]['progress'] = progress
            classification_progress[session_id]['current_step'] = f'Processing batch {batch_num + 1} of {total_batches}...'
            
            # Create user message with numbered comments
            user_message = "\n".join([f"{i+1}. {comment}" for i, comment in enumerate(batch_comments)])
            
            # Use gpt-4o-mini for speed
            # TODO: Upgrade to gpt-4.1-nano when available for ~50% better latency
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                max_tokens=100,
                temperature=0
            )
            
            # Parse the JSON response
            result_text = response.choices[0].message.content.strip()
            
            try:
                # Try to parse as JSON array first
                if result_text.startswith('['):
                    categories_result = json.loads(result_text)
                else:
                    # Try to parse as JSON object with 'categories' key
                    result_obj = json.loads(result_text)
                    categories_result = result_obj.get('categories', result_obj.get('results', []))
                
                # Map results to indices
                batch_classifications = {}
                for i, (idx, category) in enumerate(zip(batch_indices, categories_result)):
                    if i < len(categories_result):
                        # Validate category
                        if category in category_titles:
                            batch_classifications[idx] = category
                        else:
                            current_app.logger.warning(f"Invalid category '{category}' returned, using default")
                            batch_classifications[idx] = category_titles[0]
                    else:
                        # Fallback if not enough results
                        batch_classifications[idx] = category_titles[0]
                
                return batch_classifications
                
            except json.JSONDecodeError as e:
                current_app.logger.error(f"JSON parsing failed for batch {batch_num}: {e}")
                current_app.logger.error(f"Response content: {result_text}")
                # Fallback to individual processing
                return await fallback_individual_classification(client, semaphore, batch_comments, batch_indices, category_titles)
                
        except Exception as e:
            current_app.logger.error(f"Batch {batch_num} classification failed: {e}")
            # Fallback to individual processing
            return await fallback_individual_classification(client, semaphore, batch_comments, batch_indices, category_titles)

async def fallback_individual_classification(client, semaphore, batch_comments, batch_indices, category_titles):
    """Fallback to individual comment classification if batch fails"""
    classifications = {}
    
    # Simple system message for individual classification
    system_message = f"""You label comments. 
RULES:
1. Choose ONE of the following categories exactly: {', '.join(category_titles)}.
2. Output only that category title exactly as written.
3. If the comment is blank, empty, or just whitespace, respond with "No Comment".
4. If the comment is unclear or doesn't fit any category well, choose the closest match from the list."""
    
    # Process individual comments
    tasks = []
    for comment, idx in zip(batch_comments, batch_indices):
        task = classify_single_comment_async(client, semaphore, system_message, comment, idx, category_titles)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in results:
        if isinstance(result, Exception):
            current_app.logger.error(f"Individual classification failed: {result}")
            continue
        if result:
            idx, category = result
            classifications[idx] = category
    
    return classifications

async def classify_single_comment_async(client, semaphore, system_message, comment, idx, category_titles):
    """Classify a single comment asynchronously"""
    async with semaphore:
        try:
            # Use gpt-4o-mini for speed
            # TODO: Upgrade to gpt-4.1-nano when available for ~50% better latency
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": str(comment)}
                ],
                max_tokens=20,
                temperature=0
            )
            
            result = response.choices[0].message.content.strip()
            
            # Validate result
            if result in category_titles:
                return (idx, result)
            else:
                current_app.logger.warning(f"Invalid category '{result}' for comment {idx}, using default")
                return (idx, category_titles[0])
                
        except Exception as e:
            current_app.logger.error(f"Single comment classification failed for {idx}: {e}")
            return (idx, category_titles[0])


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

def get_classification_for_row(row, verbatim_col, classifications, category_titles, categories):
    """Get classification for a specific row"""
    comment = row[verbatim_col]
    
    # Check if comment is empty or null
    if pd.isna(comment) or str(comment).strip() == '':
        return 'No Comment'
    
    # Get classification from our results
    classification = classifications.get(row.name, category_titles[0] if category_titles else 'Other')
    
    # Validate that the classification is one of our expected categories
    if classification not in category_titles:
        current_app.logger.warning(f"Classification '{classification}' not in expected categories {category_titles}, using default")
        return category_titles[0] if category_titles else 'Other'
    
    return classification