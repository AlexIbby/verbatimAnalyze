from flask import Blueprint, jsonify, current_app
from routes.upload import upload_sessions

summary_bp = Blueprint('summary', __name__)

@summary_bp.route('/summary/<session_id>.json', methods=['GET'])
def get_summary_json(session_id):
    """Get JSON summary of classification results for downstream tools"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if not session.get('classified_data') is not None:
            return jsonify({'error': 'No classification data available'}), 400
        
        df = session['classified_data']
        categories = session['categories']
        
        # Generate category statistics
        category_counts = df['Comment Category'].value_counts().to_dict()
        
        # Create category list with counts
        category_list = []
        for cat in categories:
            title = cat['title']
            count = category_counts.get(title, 0)
            category_list.append({
                'title': title,
                'count': count,
                'description': cat['description']
            })
        
        # Add "No Comment" category if present
        if 'No Comment' in category_counts:
            category_list.append({
                'title': 'No Comment',
                'count': category_counts['No Comment'],
                'description': 'Rows with empty or missing comments'
            })
        
        # Sort by count (descending)
        category_list.sort(key=lambda x: x['count'], reverse=True)
        
        summary_data = {
            'session_id': session_id,
            'filename': session['filename'],
            'total_rows': len(df),
            'total_with_comments': len(df[df['Comment Category'] != 'No Comment']),
            'categories': category_list,
            'generated_at': current_app.config.get('CURRENT_TIME', ''),
            'verbatim_column': session['verbatim_column']
        }
        
        return jsonify(summary_data), 200
        
    except Exception as e:
        current_app.logger.error(f"Summary generation error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@summary_bp.route('/sessions/<session_id>/report', methods=['GET'])
def get_report_data(session_id):
    """Get detailed report data with sample quotes"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if session.get('classified_data') is None:
            return jsonify({'error': 'No classification data available'}), 400
        
        df = session['classified_data']
        categories = session['categories']
        verbatim_col = session['verbatim_column']
        
        # Generate detailed report
        report_data = {
            'session_id': session_id,
            'filename': session['filename'],
            'total_rows': len(df),
            'verbatim_column': verbatim_col,
            'categories': []
        }
        
        # Get category statistics and samples
        for cat in categories:
            title = cat['title']
            category_df = df[df['Comment Category'] == title]
            count = len(category_df)
            
            # Get sample quotes (up to 5)
            samples = []
            if count > 0:
                sample_comments = category_df[verbatim_col].dropna().astype(str)
                sample_comments = sample_comments[sample_comments.str.len() > 0]
                samples = sample_comments.head(5).tolist()
            
            # Calculate percentage
            percentage = (count / len(df)) * 100 if len(df) > 0 else 0
            
            category_data = {
                'title': title,
                'description': cat['description'],
                'count': count,
                'percentage': round(percentage, 1),
                'sample_quotes': samples
            }
            
            report_data['categories'].append(category_data)
        
        # Add "No Comment" category if present
        no_comment_df = df[df['Comment Category'] == 'No Comment']
        if len(no_comment_df) > 0:
            no_comment_data = {
                'title': 'No Comment',
                'description': 'Rows with empty or missing comments',
                'count': len(no_comment_df),
                'percentage': round((len(no_comment_df) / len(df)) * 100, 1),
                'sample_quotes': []
            }
            report_data['categories'].append(no_comment_data)
        
        # Sort categories by count (descending)
        report_data['categories'].sort(key=lambda x: x['count'], reverse=True)
        
        return jsonify(report_data), 200
        
    except Exception as e:
        current_app.logger.error(f"Report data error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500