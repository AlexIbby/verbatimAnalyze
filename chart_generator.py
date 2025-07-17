import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io
import base64
from PIL import Image

def generate_chart_image(category_data, chart_type='horizontal_bar'):
    """Generate a chart image for WeasyPrint PDF generation"""
    
    # Extract data
    categories = [cat['title'] for cat in category_data]
    counts = [cat['count'] for cat in category_data]
    percentages = [cat['percentage'] for cat in category_data]
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Define colors matching the HTML design
    colors = ['#16a085', '#27ae60', '#2c3e50', '#f39c12', '#e74c3c', '#9b59b6', '#3498db', '#95a5a6']
    bar_colors = [colors[i % len(colors)] for i in range(len(categories))]
    
    if chart_type == 'horizontal_bar':
        # Create horizontal bar chart
        bars = ax.barh(categories, counts, color=bar_colors)
        
        # Add value labels on bars
        for i, (bar, count, percentage) in enumerate(zip(bars, counts, percentages)):
            width = bar.get_width()
            ax.text(width + max(counts) * 0.01, bar.get_y() + bar.get_height()/2, 
                   f'{count} ({percentage:.1f}%)', 
                   ha='left', va='center', fontsize=10, fontweight='bold')
        
        ax.set_xlabel('Number of Responses', fontsize=12, fontweight='bold')
        ax.set_title('Category Distribution', fontsize=16, fontweight='bold', pad=20)
        
        # Invert y-axis to match data order
        ax.invert_yaxis()
        
    else:  # vertical bar chart
        bars = ax.bar(categories, counts, color=bar_colors)
        
        # Add value labels on bars
        for bar, count, percentage in zip(bars, counts, percentages):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + max(counts) * 0.01,
                   f'{count}\n({percentage:.1f}%)', 
                   ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax.set_ylabel('Number of Responses', fontsize=12, fontweight='bold')
        ax.set_title('Category Distribution', fontsize=16, fontweight='bold', pad=20)
        
        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45, ha='right')
    
    # Style the chart
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.set_facecolor('#f8f9fa')
    fig.patch.set_facecolor('white')
    
    # Remove top and right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#2c3e50')
    ax.spines['bottom'].set_color('#2c3e50')
    
    # Style the tick labels
    ax.tick_params(colors='#2c3e50', labelsize=10)
    
    # Tight layout
    plt.tight_layout()
    
    # Save to BytesIO
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                facecolor='white', edgecolor='none')
    buffer.seek(0)
    
    # Convert to base64 for embedding in HTML
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    plt.close()  # Close the figure to free memory
    
    return image_base64

def generate_pie_chart(category_data):
    """Generate a pie chart image"""
    
    # Extract data
    categories = [cat['title'] for cat in category_data]
    counts = [cat['count'] for cat in category_data]
    
    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # Define colors matching the HTML design
    colors = ['#16a085', '#27ae60', '#2c3e50', '#f39c12', '#e74c3c', '#9b59b6', '#3498db', '#95a5a6']
    pie_colors = [colors[i % len(colors)] for i in range(len(categories))]
    
    # Create pie chart
    wedges, texts, autotexts = ax.pie(counts, labels=categories, colors=pie_colors, 
                                      autopct='%1.1f%%', startangle=90)
    
    # Style the text
    for text in texts:
        text.set_fontsize(10)
        text.set_color('#2c3e50')
    
    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_color('white')
        autotext.set_fontweight('bold')
    
    ax.set_title('Category Distribution', fontsize=16, fontweight='bold', pad=20, color='#2c3e50')
    
    # Equal aspect ratio ensures that pie is drawn as a circle
    ax.axis('equal')
    
    # Set background
    fig.patch.set_facecolor('white')
    
    # Tight layout
    plt.tight_layout()
    
    # Save to BytesIO
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                facecolor='white', edgecolor='none')
    buffer.seek(0)
    
    # Convert to base64 for embedding in HTML
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    plt.close()  # Close the figure to free memory
    
    return image_base64