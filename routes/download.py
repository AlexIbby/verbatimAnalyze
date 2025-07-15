from flask import Blueprint, send_file, jsonify, current_app, request
import os
import io
import base64
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from PIL import Image as PILImage
from routes.upload import upload_sessions
from openai import OpenAI

download_bp = Blueprint('download', __name__)

@download_bp.route('/sessions/<session_id>/download/csv', methods=['GET'])
def download_csv(session_id):
    """Download the classified data as CSV"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if session.get('classified_data') is None:
            return jsonify({'error': 'No classification data available'}), 400
        
        df = session['classified_data']
        
        # Create CSV file in memory
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        
        # Convert to bytes
        csv_bytes = io.BytesIO()
        csv_bytes.write(csv_buffer.getvalue().encode('utf-8'))
        csv_bytes.seek(0)
        
        # Generate filename
        original_filename = session['filename']
        name_without_ext = os.path.splitext(original_filename)[0]
        csv_filename = f"{name_without_ext}_classified.csv"
        
        return send_file(
            csv_bytes,
            mimetype='text/csv',
            as_attachment=True,
            attachment_filename=csv_filename
        )
        
    except Exception as e:
        current_app.logger.error(f"CSV download error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@download_bp.route('/sessions/<session_id>/download/pdf', methods=['GET', 'POST'])
def download_pdf_report(session_id):
    """Download the classification report as PDF"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if session.get('classified_data') is None:
            return jsonify({'error': 'No classification data available'}), 400
        
        # Get chart image data if provided (for POST requests)
        chart_image_data = None
        if request.method == 'POST':
            json_data = request.get_json()
            if json_data and 'chart_image' in json_data:
                chart_image_data = json_data['chart_image']
        
        # Generate PDF report
        pdf_buffer = generate_pdf_report(session, chart_image_data)
        
        # Generate filename
        original_filename = session['filename']
        name_without_ext = os.path.splitext(original_filename)[0]
        pdf_filename = f"{name_without_ext}_report.pdf"
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            attachment_filename=pdf_filename
        )
        
    except Exception as e:
        current_app.logger.error(f"PDF download error: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

def generate_insights_with_gpt4o(session):
    """Generate key insights and opportunities using GPT-4o"""
    try:
        if not current_app.config.get('OPENAI_API_KEY'):
            return None
        
        client = OpenAI(api_key=current_app.config['OPENAI_API_KEY'])
        
        # Prepare data for analysis
        df = session['classified_data']
        categories = session['categories']
        verbatim_col = session['verbatim_column']
        
        # Get category distribution
        category_counts = df['Comment Category'].value_counts()
        total_responses = len(df)
        
        # Get sample quotes per category (more for analysis)
        category_data = []
        for cat in categories:
            title = cat['title']
            description = cat['description']
            count = category_counts.get(title, 0)
            percentage = (count / total_responses) * 100 if total_responses > 0 else 0
            
            # Get more sample quotes for better analysis
            category_df = df[df['Comment Category'] == title]
            sample_comments = []
            if len(category_df) > 0:
                samples = category_df[verbatim_col].dropna().astype(str)
                samples = samples[samples.str.len() > 0].head(8).tolist()
                sample_comments = samples
            
            category_data.append({
                'title': title,
                'description': description,
                'count': count,
                'percentage': percentage,
                'samples': sample_comments
            })
        
        # Prepare analysis prompt
        analysis_data = {
            'total_responses': total_responses,
            'categories': category_data,
            'verbatim_column': verbatim_col
        }
        
        system_prompt = """You are an expert customer experience analyst. Analyze survey data to provide actionable insights and opportunities.

Your analysis should be:
- Clear and actionable for business decision-makers
- Focused on key issues and opportunities
- Concise but insightful
- Written in plain business language

Provide your response as a JSON object with these sections:
{
  "key_insights": [
    "3-5 bullet points of the most important findings"
  ],
  "priority_opportunities": [
    "3-4 specific, actionable recommendations"
  ],
  "sentiment_summary": "Brief overview of overall customer sentiment",
  "risk_areas": [
    "2-3 areas that need immediate attention"
  ]
}

Focus on patterns, trends, and actionable recommendations rather than just repeating statistics."""

        user_prompt = f"""Analyze this customer feedback data:

SURVEY DETAILS:
- Total responses: {analysis_data['total_responses']}
- Feedback column: {analysis_data['verbatim_column']}

CATEGORY BREAKDOWN:
"""

        for cat in category_data:
            user_prompt += f"""
{cat['title']} ({cat['count']} responses, {cat['percentage']:.1f}%):
- Description: {cat['description']}
- Sample comments: {cat['samples'][:5]}  # Limit samples to avoid token limits
"""

        user_prompt += """

Please provide insights focusing on:
1. What are the biggest pain points for customers?
2. What opportunities exist to improve customer experience?
3. Which issues should be prioritized based on frequency and impact?
4. What positive trends can be built upon?"""

        # Make the API call
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1000,
            temperature=0.3
        )
        
        # Parse the JSON response
        insights_text = response.choices[0].message.content.strip()
        
        # Try to parse as JSON, fallback to text if it fails
        try:
            insights = json.loads(insights_text)
            return insights
        except json.JSONDecodeError:
            current_app.logger.warning("GPT-4o response was not valid JSON, using fallback")
            return {
                "key_insights": ["Analysis completed but formatting issue occurred"],
                "priority_opportunities": ["Review detailed category breakdown for specific areas to address"],
                "sentiment_summary": "Mixed feedback with areas for improvement identified",
                "risk_areas": ["Review individual categories for specific issues"]
            }
            
    except Exception as e:
        current_app.logger.error(f"Error generating insights with GPT-4o: {e}")
        return None

def generate_pdf_report(session, chart_image_data=None):
    """Generate a PDF report of the classification results"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*inch)
    
    # Get data
    df = session['classified_data']
    categories = session['categories']
    verbatim_col = session['verbatim_column']
    filename = session['filename']
    
    # Build story (content)
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    story.append(Paragraph("Comments Analysis Report", title_style))
    story.append(Spacer(1, 20))
    
    # File information
    story.append(Paragraph(f"<b>File:</b> {filename}", styles['Normal']))
    story.append(Paragraph(f"<b>Total Responses:</b> {len(df)}", styles['Normal']))
    story.append(Paragraph(f"<b>Verbatim Column:</b> {verbatim_col}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Generate and add insights if OpenAI is available
    insights = generate_insights_with_gpt4o(session)
    if insights:
        story.append(Paragraph("Executive Summary", styles['Heading2']))
        story.append(Spacer(1, 10))
        
        # Sentiment Summary
        if insights.get('sentiment_summary'):
            story.append(Paragraph(f"<b>Overall Sentiment:</b> {insights['sentiment_summary']}", styles['Normal']))
            story.append(Spacer(1, 10))
        
        # Key Insights
        if insights.get('key_insights'):
            story.append(Paragraph("<b>Key Insights:</b>", styles['Normal']))
            for insight in insights['key_insights']:
                story.append(Paragraph(f"• {insight}", styles['Normal']))
            story.append(Spacer(1, 10))
        
        # Priority Opportunities
        if insights.get('priority_opportunities'):
            story.append(Paragraph("<b>Priority Opportunities:</b>", styles['Normal']))
            for opportunity in insights['priority_opportunities']:
                story.append(Paragraph(f"• {opportunity}", styles['Normal']))
            story.append(Spacer(1, 10))
        
        # Risk Areas
        if insights.get('risk_areas'):
            story.append(Paragraph("<b>Areas Requiring Attention:</b>", styles['Normal']))
            for risk in insights['risk_areas']:
                story.append(Paragraph(f"• {risk}", styles['Normal']))
            story.append(Spacer(1, 15))
        
        story.append(Spacer(1, 20))
    else:
        # Show a note if insights are not available
        if not current_app.config.get('OPENAI_API_KEY'):
            story.append(Paragraph("Enhanced Analysis", styles['Heading2']))
            story.append(Paragraph("<i>Note: Enhanced insights and recommendations are available when OpenAI API key is configured.</i>", styles['Normal']))
            story.append(Spacer(1, 20))
    
    # Category summary table
    story.append(Paragraph("Category Summary", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    # Prepare table data
    table_data = [['Category', 'Count', 'Percentage']]
    category_counts = df['Comment Category'].value_counts()
    
    for cat in categories:
        title = cat['title']
        count = category_counts.get(title, 0)
        percentage = (count / len(df)) * 100 if len(df) > 0 else 0
        table_data.append([title, str(count), f"{percentage:.1f}%"])
    
    # Add "No Comment" if present
    if 'No Comment' in category_counts:
        count = category_counts['No Comment']
        percentage = (count / len(df)) * 100
        table_data.append(['No Comment', str(count), f"{percentage:.1f}%"])
    
    # Create and style table
    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Add chart image if provided
    if chart_image_data:
        try:
            # Decode base64 image data
            image_data = chart_image_data.split(',')[1]  # Remove data:image/png;base64, prefix
            image_bytes = base64.b64decode(image_data)
            
            # Create PIL Image to get dimensions
            pil_image = PILImage.open(io.BytesIO(image_bytes))
            
            # Calculate appropriate size for PDF (max 6 inches wide)
            max_width = 6 * inch
            aspect_ratio = pil_image.height / pil_image.width
            img_width = min(max_width, pil_image.width * 0.75)  # 0.75 points per pixel
            img_height = img_width * aspect_ratio
            
            # Create ReportLab Image
            chart_image = Image(io.BytesIO(image_bytes), width=img_width, height=img_height)
            
            story.append(Paragraph("Category Distribution Chart", styles['Heading2']))
            story.append(Spacer(1, 10))
            story.append(chart_image)
            story.append(Spacer(1, 20))
            
        except Exception as e:
            current_app.logger.error(f"Error adding chart to PDF: {e}")
            # Continue without chart if there's an error
            pass
    
    story.append(Spacer(1, 10))
    
    # Sample quotes for each category
    story.append(Paragraph("Sample Quotes by Category", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    for cat in categories:
        title = cat['title']
        description = cat['description']
        
        # Category header
        story.append(Paragraph(f"<b>{title}</b>", styles['Heading3']))
        story.append(Paragraph(f"<i>{description}</i>", styles['Normal']))
        story.append(Spacer(1, 5))
        
        # Get sample quotes
        category_df = df[df['Comment Category'] == title]
        if len(category_df) > 0:
            sample_comments = category_df[verbatim_col].dropna().astype(str)
            sample_comments = sample_comments[sample_comments.str.len() > 0]
            samples = sample_comments.head(3).tolist()
            
            if samples:
                for i, quote in enumerate(samples, 1):
                    # Truncate very long quotes
                    if len(quote) > 200:
                        quote = quote[:200] + "..."
                    story.append(Paragraph(f"{i}. \"{quote}\"", styles['Normal']))
                    story.append(Spacer(1, 3))
            else:
                story.append(Paragraph("No sample quotes available.", styles['Normal']))
        else:
            story.append(Paragraph("No comments in this category.", styles['Normal']))
        
        story.append(Spacer(1, 15))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return buffer