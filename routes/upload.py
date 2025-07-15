from flask import Blueprint, request, jsonify, current_app
import os
import uuid
import pandas as pd
from werkzeug.utils import secure_filename
from utils import allowed_file, detect_verbatim_col, load_excel_file

upload_bp = Blueprint('upload', __name__)

# Store upload sessions in memory (use Redis/database for production)
upload_sessions = {}

@upload_bp.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and initial processing"""
    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not supported. Please upload .xlsx, .xls, or .csv files'}), 400
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")
        file.save(filepath)
        
        # Load and analyze file
        try:
            df = load_excel_file(filepath)
        except ValueError as e:
            # Clean up file
            os.remove(filepath)
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            # Clean up file
            os.remove(filepath)
            return jsonify({'error': f'Failed to read file: {str(e)}'}), 400
        
        # Detect verbatim column
        verbatim_col, is_confident = detect_verbatim_col(df)
        
        # Store session data
        upload_sessions[session_id] = {
            'filepath': filepath,
            'filename': filename,
            'dataframe': df,
            'verbatim_column': verbatim_col,
            'column_detection_confident': is_confident,
            'total_rows': len(df),
            'columns': list(df.columns),
            'categories': None,
            'classified_data': None
        }
        
        # Prepare response
        response_data = {
            'session_id': session_id,
            'filename': filename,
            'total_rows': len(df),
            'columns': list(df.columns),
            'detected_verbatim_column': verbatim_col,
            'detection_confident': is_confident,
            'preview': df.head(5).to_dict('records') if len(df) > 0 else []
        }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        current_app.logger.error(f"Upload error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@upload_bp.route('/sessions/<session_id>/column', methods=['POST'])
def update_verbatim_column(session_id):
    """Allow user to manually override the detected verbatim column"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        data = request.get_json()
        if not data or 'column' not in data:
            return jsonify({'error': 'Column name required'}), 400
        
        column_name = data['column']
        session = upload_sessions[session_id]
        
        if column_name not in session['columns']:
            return jsonify({'error': 'Column not found in dataset'}), 400
        
        # Update session
        session['verbatim_column'] = column_name
        session['column_detection_confident'] = True  # User override is always confident
        
        return jsonify({
            'session_id': session_id,
            'verbatim_column': column_name,
            'status': 'updated'
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Column update error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@upload_bp.route('/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """Get session information"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        return jsonify({
            'session_id': session_id,
            'filename': session['filename'],
            'total_rows': session['total_rows'],
            'columns': session['columns'],
            'verbatim_column': session['verbatim_column'],
            'detection_confident': session['column_detection_confident'],
            'has_categories': session['categories'] is not None,
            'has_classifications': session['classified_data'] is not None
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Session get error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500