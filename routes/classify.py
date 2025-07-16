from flask import Blueprint, request, jsonify, current_app, Response
from openai import AsyncOpenAI
import pandas as pd
import time
import json
import threading
import asyncio
import numpy as np
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
            'processed': 0,
            'remaining': len(df),
            'current_step': 'Starting classification...',
            'completed': False,
            'start_time': time.time(),
            'estimated_time_remaining': None,
            'processing_rate': 0
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
                'processed': len(df),
                'remaining': 0,
                'current_step': 'Classification completed',
                'completed': True,
                'start_time': classification_progress[session_id].get('start_time', time.time()),
                'estimated_time_remaining': 0,
                'processing_rate': classification_progress[session_id].get('processing_rate', 0)
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
                'processed': classification_progress[session_id].get('processed', 0),
                'remaining': classification_progress[session_id].get('remaining', 0),
                'current_step': f'Classification failed: {str(e)}',
                'completed': False,
                'start_time': classification_progress[session_id].get('start_time', time.time()),
                'estimated_time_remaining': None,
                'processing_rate': classification_progress[session_id].get('processing_rate', 0),
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
    system_message = f"""You are an expert at analyzing customer feedback to identify specific issues and problems.

Your task is to classify comments about an online application process. Focus on identifying ISSUES and PROBLEMS that prevented users from completing their goals.

CATEGORIES: {', '.join(category_titles)}

CLASSIFICATION RULES:
1. If the comment describes a SPECIFIC PROBLEM or ISSUE (eligibility, technical, usability, process), classify it accordingly
2. If the comment is POSITIVE or PRAISE with no issues mentioned, use "Positive Remark" (if available)
3. If the comment doesn't fit any specific issue category, use "Other" (if available)
4. If the comment is blank/empty, use "No Comment"

EXAMPLES:
- "Good service" → "Positive Remark" (no issue mentioned)
- "Couldn't log in" → "Technical Issue" (specific technical problem)
- "Eligibility requirements unclear" → "Eligibility Issue" (specific eligibility problem)
- "Hard to find the submit button" → "Usability Issue" (specific UI problem)

Output a JSON object with "categories" array and "confidence" array (0-100 for each):
{{"categories": ["Category1", "Category2"], "confidence": [95, 80]}}"""
    
    # Process comments in batches - send multiple comments per API call
    batch_size = 10  # Reduced batch size to avoid token limits with confidence scores
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
            # Update progress with detailed information
            progress = 20 + int((batch_num / total_batches) * 60)  # Progress from 20% to 80%
            processed = batch_num * len(batch_comments)
            total_comments = classification_progress[session_id]['total']
            remaining = total_comments - processed
            
            # Calculate processing rate and time estimation
            start_time = classification_progress[session_id].get('start_time', time.time())
            elapsed_time = time.time() - start_time
            
            if elapsed_time > 0 and processed > 0:
                processing_rate = processed / elapsed_time  # comments per second
                estimated_time_remaining = remaining / processing_rate if processing_rate > 0 else None
            else:
                processing_rate = 0
                estimated_time_remaining = None
            
            classification_progress[session_id].update({
                'progress': progress,
                'processed': processed,
                'remaining': remaining,
                'current_step': f'Processing batch {batch_num + 1} of {total_batches} ({processed}/{total_comments} comments)',
                'processing_rate': round(processing_rate, 2),
                'estimated_time_remaining': round(estimated_time_remaining) if estimated_time_remaining else None
            })
            
            # Create user message with numbered comments
            user_message = "\n".join([f"{i+1}. {comment}" for i, comment in enumerate(batch_comments)])
            
            # Use gpt-4o for best classification accuracy
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                max_tokens=200,
                temperature=0
            )
            
            # Parse the JSON response
            result_text = response.choices[0].message.content.strip()
            
            try:
                # Try to parse as JSON object with categories and confidence
                if result_text.startswith('{'):
                    result_obj = json.loads(result_text)
                    categories_result = result_obj.get('categories', [])
                    confidence_result = result_obj.get('confidence', [])
                else:
                    # Fallback to array format (legacy)
                    categories_result = json.loads(result_text)
                    confidence_result = [None] * len(categories_result)
                
                # Map results to indices - ensure we have the right number of results
                batch_classifications = {}
                if len(categories_result) != len(batch_indices):
                    current_app.logger.warning(f"Batch {batch_num}: Expected {len(batch_indices)} results, got {len(categories_result)}")
                
                for i, idx in enumerate(batch_indices):
                    if i < len(categories_result):
                        category = categories_result[i]
                        confidence = confidence_result[i] if i < len(confidence_result) else None
                        
                        # Use semantic validation for low confidence or invalid categories
                        if confidence is not None and confidence < 70:
                            current_app.logger.info(f"Low confidence ({confidence}%) for comment {idx}, using semantic validation")
                            category, confidence, reason = await find_best_category_semantic(
                                client, batch_comments[i], category_titles, category, confidence
                            )
                        
                        # Validate category
                        if category in category_titles:
                            batch_classifications[idx] = category
                        else:
                            current_app.logger.warning(f"Invalid category '{category}' returned for comment {idx}, using semantic validation")
                            category, confidence, reason = await find_best_category_semantic(
                                client, batch_comments[i], category_titles
                            )
                            batch_classifications[idx] = category
                    else:
                        # Fallback if not enough results
                        current_app.logger.warning(f"Missing result for comment {idx}, using semantic validation")
                        category, confidence, reason = await find_best_category_semantic(
                            client, batch_comments[i], category_titles
                        )
                        batch_classifications[idx] = category
                
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
            # Use gpt-4o for best classification accuracy
            response = await client.chat.completions.create(
                model="gpt-4o",
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
    start_time = classification_progress[session_id].get('start_time', time.time())
    
    for i, (idx, comment) in enumerate(comments.items()):
        # Update progress every 50 comments
        if i % 50 == 0:
            progress = 20 + int((i / total_comments) * 60)  # Progress from 20% to 80%
            processed = i
            remaining = total_comments - processed
            
            # Calculate processing rate and time estimation
            elapsed_time = time.time() - start_time
            if elapsed_time > 0 and processed > 0:
                processing_rate = processed / elapsed_time  # comments per second
                estimated_time_remaining = remaining / processing_rate if processing_rate > 0 else None
            else:
                processing_rate = 0
                estimated_time_remaining = None
            
            classification_progress[session_id].update({
                'progress': progress,
                'processed': processed,
                'remaining': remaining,
                'current_step': f'Classifying comment {i + 1} of {total_comments} (keyword matching)',
                'processing_rate': round(processing_rate, 2),
                'estimated_time_remaining': round(estimated_time_remaining) if estimated_time_remaining else None
            })
        
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

async def find_best_category_semantic(client, comment, category_titles, original_category=None, confidence=None):
    """Find the best category using semantic similarity across all categories"""
    try:
        # Only do semantic re-classification if confidence is low or not provided
        confidence_threshold = 70  # Only re-classify if confidence < 70%
        if confidence is not None and confidence >= confidence_threshold:
            return original_category, confidence, "High confidence, skipping semantic check"
        
        # Create embedding for the comment
        comment_embedding_response = await client.embeddings.create(
            input=str(comment),
            model="text-embedding-3-small"
        )
        comment_embedding = np.array(comment_embedding_response.data[0].embedding)
        
        # Calculate similarity with all categories
        similarities = {}
        for category in category_titles:
            category_desc = get_category_description(category, category_titles)
            
            category_embedding_response = await client.embeddings.create(
                input=f"{category}: {category_desc}",
                model="text-embedding-3-small"
            )
            category_embedding = np.array(category_embedding_response.data[0].embedding)
            
            # Calculate cosine similarity
            similarity = np.dot(comment_embedding, category_embedding) / (
                np.linalg.norm(comment_embedding) * np.linalg.norm(category_embedding)
            )
            similarities[category] = similarity
        
        # Find best match
        best_category = max(similarities, key=similarities.get)
        best_similarity = similarities[best_category]
        
        # Log if semantic analysis suggests different category
        if original_category and best_category != original_category:
            current_app.logger.info(f"Semantic analysis suggests '{best_category}' (sim: {best_similarity:.3f}) instead of '{original_category}' (sim: {similarities.get(original_category, 0):.3f}) for: '{comment}'")
        
        # Convert similarity to confidence percentage
        semantic_confidence = int(best_similarity * 100)
        
        return best_category, semantic_confidence, f"Semantic similarity: {best_similarity:.3f}"
        
    except Exception as e:
        current_app.logger.error(f"Semantic category selection failed: {e}")
        return original_category, confidence, f"Semantic analysis failed: {e}"

def get_category_description(category_title, category_titles):
    """Get a description for semantic validation"""
    descriptions = {
        "Eligibility Issues": "problems with qualification requirements or application eligibility",
        "Technical Issues": "system errors, website problems, login failures, technical malfunctions",
        "Usability Issues": "user interface problems, navigation difficulties, confusing design",
        "Process Issues": "application procedures, documentation requirements, workflow problems",
        "Communication Issues": "unclear information, lack of guidance, poor communication",
        "Positive Remark": "positive feedback, praise, compliments, satisfaction, good experience",
        "Other": "miscellaneous comments that don't fit specific issue categories",
        "No Comment": "empty, blank, or missing responses"
    }
    return descriptions.get(category_title, category_title)