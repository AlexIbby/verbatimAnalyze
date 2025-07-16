from flask import Blueprint, request, jsonify, current_app
from openai import OpenAI
import json
import random
from routes.upload import upload_sessions

suggest_bp = Blueprint('suggest', __name__)

@suggest_bp.route('/sessions/<session_id>/suggest', methods=['POST'])
def suggest_categories(session_id):
    """Generate category suggestions based on sample comments"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        df = session['dataframe']
        verbatim_col = session['verbatim_column']
        
        if not verbatim_col or verbatim_col not in df.columns:
            return jsonify({'error': 'Verbatim column not set or invalid'}), 400
        
        # Get sample comments
        comments = df[verbatim_col].dropna().astype(str)
        comments = comments[comments.str.len() > 10]  # Filter out very short comments
        
        if len(comments) == 0:
            return jsonify({'error': 'No valid comments found in verbatim column'}), 400
        
        # Sample up to 50 comments for analysis
        sample_size = min(50, len(comments))
        sample_comments = comments.sample(n=sample_size, random_state=42).tolist()
        
        # Generate categories using OpenAI
        if not current_app.config.get('OPENAI_API_KEY'):
            # Fallback to predefined categories if no API key
            categories = get_fallback_categories()
        else:
            categories = generate_categories_with_llm(sample_comments)
        
        # Ensure "No Comment" category is always present
        has_no_comment = any(cat['title'] == 'No Comment' for cat in categories)
        if not has_no_comment:
            categories.append({
                "title": "No Comment",
                "description": "Empty, blank, or missing comments"
            })
        
        # Store categories in session
        session['categories'] = categories
        
        return jsonify({
            'session_id': session_id,
            'categories': categories,
            'sample_size': sample_size,
            'total_comments': len(comments)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Category suggestion error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@suggest_bp.route('/sessions/<session_id>/categories', methods=['POST'])
def update_categories(session_id):
    """Allow user to manually update categories"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        data = request.get_json()
        if not data or 'categories' not in data:
            return jsonify({'error': 'Categories required'}), 400
        
        categories = data['categories']
        
        # Validate categories format
        if not isinstance(categories, list):
            return jsonify({'error': 'Categories must be a list'}), 400
        
        for cat in categories:
            if not isinstance(cat, dict) or 'title' not in cat or 'description' not in cat:
                return jsonify({'error': 'Each category must have title and description'}), 400
        
        # Ensure "No Comment" category is always present
        has_no_comment = any(cat['title'] == 'No Comment' for cat in categories)
        if not has_no_comment:
            categories.append({
                "title": "No Comment",
                "description": "Empty, blank, or missing comments"
            })
        
        # Update session
        current_app.logger.info(f"=== UPDATING CATEGORIES ===")
        current_app.logger.info(f"Session ID: {session_id}")
        current_app.logger.info(f"Categories being stored: {categories}")
        
        # Get session data, modify it, and store it back
        session_data = upload_sessions[session_id]
        if session_data is None:
            current_app.logger.error(f"Session data is None for session {session_id}")
            return jsonify({'error': 'Session data not found'}), 404
        
        # Create a copy to avoid reference issues
        session_data_copy = dict(session_data)
        session_data_copy['categories'] = categories
        
        # Store the updated session data
        upload_sessions[session_id] = session_data_copy
        
        # Verify categories were stored
        stored_session = upload_sessions[session_id]
        current_app.logger.info(f"Categories after storage: {stored_session.get('categories') if stored_session else 'Session is None'}")
        
        # Double-check the storage worked
        if stored_session is None or stored_session.get('categories') is None:
            current_app.logger.error(f"Failed to store categories for session {session_id}")
            return jsonify({'error': 'Failed to save categories'}), 500
        
        return jsonify({
            'session_id': session_id,
            'categories': categories,
            'status': 'updated'
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Category update error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@suggest_bp.route('/sessions/<session_id>/debug', methods=['GET'])
def debug_session(session_id):
    """Debug endpoint to check session state"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        return jsonify({
            'session_id': session_id,
            'session_keys': list(session.keys()) if session else [],
            'has_categories': 'categories' in session if session else False,
            'categories_count': len(session.get('categories', [])) if session else 0,
            'categories': session.get('categories', []) if session else []
        }), 200
    
    except Exception as e:
        current_app.logger.error(f"Debug session error: {e}")
        return jsonify({'error': f'Debug error: {str(e)}'}), 500

def generate_categories_with_llm(sample_comments):
    """Use OpenAI to generate categories from sample comments"""
    try:
        client = OpenAI(api_key=current_app.config['OPENAI_API_KEY'])
        
        comments_text = "\n".join([f"- {comment}" for comment in sample_comments])
        
        prompt = f"""You are a research assistant analyzing survey feedback.

Here's a sample of survey comments:
---
{comments_text}
---

Generate 5-6 distinct categories that cover all feedback types. Each category should:
- Have a short title (≤4 words)
- Have a clear description explaining what comments belong in this category
- Be mutually exclusive (no overlap between categories)

Note: A "No Comment" category will be automatically added for blank/empty responses, so focus on categorizing meaningful content.

Return your response as a JSON list in this exact format:
[{{"title": "Category Name", "description": "Clear description of what this category covers"}}]

Only return the JSON, no other text."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a research assistant that helps categorize survey feedback."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.3
        )
        
        result = response.choices[0].message.content.strip()
        
        # Parse JSON response
        try:
            categories = json.loads(result)
            
            # Validate structure
            if not isinstance(categories, list):
                raise ValueError("Response is not a list")
            
            for cat in categories:
                if not isinstance(cat, dict) or 'title' not in cat or 'description' not in cat:
                    raise ValueError("Invalid category structure")
            
            return categories
            
        except (json.JSONDecodeError, ValueError) as e:
            current_app.logger.error(f"Failed to parse LLM response: {e}")
            return get_fallback_categories()
        
    except Exception as e:
        current_app.logger.error(f"LLM category generation failed: {e}")
        return get_fallback_categories()

def get_fallback_categories():
    """Fallback categories when LLM is not available"""
    return [
        {
            "title": "Service Quality",
            "description": "Comments about the quality of service delivery, staff performance, or service standards"
        },
        {
            "title": "Wait Times",
            "description": "Comments about waiting times, delays, scheduling, or appointment availability"
        },
        {
            "title": "Accessibility",
            "description": "Comments about physical access, digital access, or accommodation needs"
        },
        {
            "title": "Communication",
            "description": "Comments about information sharing, clarity of communication, or responsiveness"
        },
        {
            "title": "Process Issues",
            "description": "Comments about procedures, paperwork, bureaucracy, or system problems"
        },
        {
            "title": "Positive Feedback",
            "description": "General praise, compliments, or positive experiences with the service"
        },
        {
            "title": "No Comment",
            "description": "Empty, blank, or missing comments"
        }
    ]