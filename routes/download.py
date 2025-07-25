from flask import Blueprint, send_file, jsonify, current_app, request, render_template
import os
import io
import base64
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from PIL import Image as PILImage
from routes.upload import upload_sessions
from openai import OpenAI
from chart_generator import generate_chart_image

# Always use ReportLab for PDF generation for better cross-platform compatibility

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

@download_bp.route('/sessions/<session_id>/report/preview', methods=['GET'])
def preview_report(session_id):
    """Preview the HTML report before downloading as PDF"""
    try:
        if session_id not in upload_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = upload_sessions[session_id]
        
        if session.get('classified_data') is None:
            return jsonify({'error': 'No classification data available'}), 400
        
        # Get data
        df = session['classified_data']
        categories = session['categories']
        verbatim_col = session['verbatim_column']
        filename = session['filename']
        
        # Generate insights
        insights = generate_insights_with_gpt4o(session)
        
        # Prepare category data for template
        category_counts = df['Comment Category'].value_counts()
        category_data = []
        
        for cat in categories:
            title = cat['title']
            description = cat['description']
            count = category_counts.get(title, 0)
            percentage = (count / len(df)) * 100 if len(df) > 0 else 0
            
            # Get sample quotes with row numbers
            category_df = df[df['Comment Category'] == title]
            sample_quotes = []
            if len(category_df) > 0:
                # Get the first 3 non-empty comments with their original row numbers
                sample_data = category_df[category_df[verbatim_col].notna() & 
                                        (category_df[verbatim_col].astype(str).str.len() > 0)].head(3)
                
                for _, row in sample_data.iterrows():
                    quote = str(row[verbatim_col])
                    row_num = row.name + 2  # +2 because pandas index is 0-based and CSV has header
                    
                    # Truncate very long quotes
                    if len(quote) > 200:
                        quote = quote[:200] + "..."
                    
                    sample_quotes.append({
                        'text': quote,
                        'row_num': row_num
                    })
            
            category_data.append({
                'title': title,
                'description': description,
                'count': count,
                'percentage': percentage,
                'sample_quotes': sample_quotes
            })
        
        # Add "No Comment" if present
        if 'No Comment' in category_counts:
            count = category_counts['No Comment']
            percentage = (count / len(df)) * 100
            category_data.append({
                'title': 'No Comment',
                'description': 'Empty, blank, or missing comments',
                'count': count,
                'percentage': percentage,
                'sample_quotes': []
            })
        
        # Render HTML template
        return render_template('report.html',
                             filename=filename,
                             total_responses=len(df),
                             verbatim_column=verbatim_col,
                             insights=insights,
                             category_data=category_data,
                             chart_data=None)  # No chart data for preview
        
    except Exception as e:
        current_app.logger.error(f"Report preview error: {e}")
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
                samples = samples[samples.str.len() > 0].head(25).tolist()
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
- Based on specific criticisms and feedback found in the sample comments
- Written in plain business language
- Cite specific themes and patterns from the actual comments provided

CRITICAL: Respond ONLY with a valid JSON object. Do not include any markdown formatting, explanations, or text outside the JSON. The response must start with { and end with }.

Provide your response as a JSON object with these sections:
{
  "key_insights": [
    "4-6 bullet points highlighting specific patterns and themes from the comments"
  ],
  "priority_opportunities": [
    "4-5 specific, actionable recommendations based on the feedback patterns"
  ],
  "sentiment_summary": "Brief overview of overall customer sentiment with specific observations",
  "risk_areas": [
    "3-4 areas that need immediate attention based on recurring complaints"
  ]
}

Focus on specific criticisms, complaints, and suggestions found in the sample comments. Reference actual issues mentioned by customers."""

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
- Sample comments: {cat['samples'][:25]}
"""

        user_prompt += """

Analyze the sample comments thoroughly and provide insights focusing on:
1. What specific pain points and criticisms are customers expressing?
2. What patterns emerge across the feedback categories?
3. Which operational issues appear most frequently in the comments?
4. What specific improvements are customers requesting?
5. Which problems should be prioritized based on frequency and severity of complaints?
6. What positive feedback can guide future improvements?

Pay close attention to recurring themes, specific service failures, and actionable suggestions within the actual customer comments provided."""

        # Make the API call
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        # Parse the JSON response
        insights_text = response.choices[0].message.content.strip()
        
        # Try to extract JSON from the response (handle markdown code blocks)
        try:
            # First, try direct JSON parsing
            insights = json.loads(insights_text)
            return insights
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', insights_text, re.DOTALL)
            if json_match:
                try:
                    insights = json.loads(json_match.group(1))
                    return insights
                except json.JSONDecodeError:
                    pass
            
            # Try to find JSON object in the text (look for { ... })
            json_match = re.search(r'\{.*\}', insights_text, re.DOTALL)
            if json_match:
                try:
                    insights = json.loads(json_match.group(0))
                    return insights
                except json.JSONDecodeError:
                    pass
            
            current_app.logger.warning(f"GPT-4o response was not valid JSON, using fallback. Response: {insights_text[:200]}...")
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
    """Generate a PDF report of the classification results using ReportLab"""
    return generate_pdf_with_reportlab(session, chart_image_data)


def generate_pdf_with_reportlab(session, chart_image_data=None):
    """Generate a PDF report using ReportLab with improved styling"""
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
    
    # Create custom styles that match the HTML design
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center alignment
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#2c3e50')
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=18,
        spaceAfter=20,
        spaceBefore=30,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#2c3e50')
    )
    
    subheading_style = ParagraphStyle(
        'CustomSubheading',
        parent=styles['Heading3'],
        fontSize=14,
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#16a085')
    )
    
    # Title
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
        story.append(Paragraph("Executive Summary", heading_style))
        story.append(Spacer(1, 10))
        
        # Sentiment Summary
        if insights.get('sentiment_summary'):
            story.append(Paragraph("<b>Overall Sentiment:</b>", subheading_style))
            story.append(Paragraph(insights['sentiment_summary'], styles['Normal']))
            story.append(Spacer(1, 10))
        
        # Create a bullet style with better spacing
        bullet_style = ParagraphStyle(
            'BulletList',
            parent=styles['Normal'],
            leftIndent=20,
            fontSize=11,
            fontName='Helvetica',
            textColor=colors.HexColor('#495057'),
            spaceAfter=8,
            spaceBefore=2,
            leading=16
        )
        
        # Key Insights
        if insights.get('key_insights'):
            story.append(Paragraph("<b>Key Insights:</b>", subheading_style))
            for insight in insights['key_insights']:
                story.append(Paragraph(f"• {insight}", bullet_style))
            story.append(Spacer(1, 15))
        
        # Priority Opportunities
        if insights.get('priority_opportunities'):
            story.append(Paragraph("<b>Priority Opportunities:</b>", subheading_style))
            for opportunity in insights['priority_opportunities']:
                story.append(Paragraph(f"• {opportunity}", bullet_style))
            story.append(Spacer(1, 15))
        
        # Risk Areas
        if insights.get('risk_areas'):
            story.append(Paragraph("<b>Areas Requiring Attention:</b>", subheading_style))
            for risk in insights['risk_areas']:
                story.append(Paragraph(f"• {risk}", bullet_style))
            story.append(Spacer(1, 20))
        
        story.append(Spacer(1, 20))
    else:
        # Show a note if insights are not available
        if not current_app.config.get('OPENAI_API_KEY'):
            story.append(Paragraph("Enhanced Analysis", heading_style))
            story.append(Paragraph("<i>Note: Enhanced insights and recommendations are available when OpenAI API key is configured.</i>", styles['Normal']))
            story.append(Spacer(1, 20))
    
    # Category summary table
    story.append(Paragraph("Category Summary", heading_style))
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
    
    # Create and style table with improved styling
    table = Table(table_data, colWidths=[4*inch, 1*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e9ecef')),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Add chart image
    try:
        # Prepare category data for chart generation
        category_data_for_chart = []
        for cat in categories:
            title = cat['title']
            count = category_counts.get(title, 0)
            percentage = (count / len(df)) * 100 if len(df) > 0 else 0
            category_data_for_chart.append({
                'title': title,
                'count': count,
                'percentage': percentage
            })
        
        # Add "No Comment" if present
        if 'No Comment' in category_counts:
            count = category_counts['No Comment']
            percentage = (count / len(df)) * 100
            category_data_for_chart.append({
                'title': 'No Comment',
                'count': count,
                'percentage': percentage
            })
        
        # Generate chart image using matplotlib
        chart_data = generate_chart_image(category_data_for_chart, chart_type='horizontal_bar')
        
        # Decode base64 image data
        image_bytes = base64.b64decode(chart_data)
        
        # Create PIL Image to get dimensions
        pil_image = PILImage.open(io.BytesIO(image_bytes))
        
        # Calculate appropriate size for PDF (max 6 inches wide)
        max_width = 6 * inch
        aspect_ratio = pil_image.height / pil_image.width
        img_width = min(max_width, pil_image.width * 0.75)  # 0.75 points per pixel
        img_height = img_width * aspect_ratio
        
        # Create ReportLab Image
        chart_image = Image(io.BytesIO(image_bytes), width=img_width, height=img_height)
        
        story.append(Paragraph("Category Distribution Chart", heading_style))
        story.append(Spacer(1, 10))
        story.append(chart_image)
        story.append(Spacer(1, 20))
        
    except Exception as e:
        current_app.logger.error(f"Error adding chart to PDF: {e}")
        # Fall back to provided chart data if available
        if chart_image_data:
            try:
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
                
                story.append(Paragraph("Category Distribution Chart", heading_style))
                story.append(Spacer(1, 10))
                story.append(chart_image)
                story.append(Spacer(1, 20))
                
            except Exception as e2:
                current_app.logger.error(f"Error adding fallback chart to PDF: {e2}")
                # Continue without chart if there's an error
                pass
    
    # Sample quotes for each category
    story.append(Paragraph("Sample Quotes by Category", heading_style))
    story.append(Spacer(1, 10))
    
    for cat in categories:
        title = cat['title']
        description = cat['description']
        
        # Category header
        story.append(Paragraph(f"<b>{title}</b>", subheading_style))
        story.append(Paragraph(f"<i>{description}</i>", styles['Normal']))
        story.append(Spacer(1, 5))
        
        # Get sample quotes with row numbers
        category_df = df[df['Comment Category'] == title]
        if len(category_df) > 0:
            # Get the first 3 non-empty comments with their original row numbers
            sample_data = category_df[category_df[verbatim_col].notna() & 
                                    (category_df[verbatim_col].astype(str).str.len() > 0)].head(3)
            
            if len(sample_data) > 0:
                # Create a bullet style for quotes (similar to executive summary)
                quote_bullet_style = ParagraphStyle(
                    'QuoteBullet',
                    parent=styles['Normal'],
                    leftIndent=20,
                    fontSize=11,
                    fontName='Helvetica',
                    textColor=colors.HexColor('#495057'),
                    spaceAfter=10,
                    spaceBefore=2,
                    leading=16
                )
                
                for _, row in sample_data.iterrows():
                    quote = str(row[verbatim_col])
                    row_num = row.name + 2  # +2 because pandas index is 0-based and CSV has header
                    
                    # Truncate very long quotes
                    if len(quote) > 200:
                        quote = quote[:200] + "..."
                    
                    # Format as bullet with row number
                    story.append(Paragraph(f"• \"{quote}\" <i>(Row {row_num})</i>", quote_bullet_style))
            else:
                story.append(Paragraph("No sample quotes available.", styles['Normal']))
        else:
            story.append(Paragraph("No comments in this category.", styles['Normal']))
        
        story.append(Spacer(1, 15))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return buffer