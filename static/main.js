// Global variables
let currentSessionId = null;
let currentStep = 1;
let categoryChart = null;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    setupFileUpload();
    updateStepStatus();
    
    // Handle window resize for chart responsiveness
    window.addEventListener('resize', function() {
        if (categoryChart) {
            // Update chart options based on new screen size
            const isMobile = window.innerWidth < 768;
            categoryChart.options.scales.x.ticks.font.size = isMobile ? 10 : 12;
            categoryChart.options.scales.y.ticks.font.size = isMobile ? 10 : 12;
            categoryChart.options.plugins.tooltip.titleFont.size = isMobile ? 12 : 14;
            categoryChart.options.plugins.tooltip.bodyFont.size = isMobile ? 11 : 13;
            categoryChart.update('none'); // Update without animation
        }
    });
});

// File upload setup
function setupFileUpload() {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');

    // Click to upload
    uploadArea.addEventListener('click', () => fileInput.click());

    // File input change
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });
}

// Handle file selection
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        handleFile(file);
    }
}

// Handle file upload
async function handleFile(file) {
    // Validate file
    const allowedTypes = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
                         'application/vnd.ms-excel', 'text/csv'];
    if (!allowedTypes.includes(file.type) && !file.name.match(/\.(xlsx|xls|csv)$/i)) {
        showError('upload-error', 'Please select a valid Excel or CSV file');
        return;
    }

    if (file.size > 5 * 1024 * 1024) {
        showError('upload-error', 'File size must be less than 5MB');
        return;
    }

    // Show loading
    document.getElementById('upload-loading').classList.add('show');
    clearError('upload-error');
    
    // Simulate upload progress
    simulateUploadProgress();

    try {
        // Upload file
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Upload failed');
        }

        // Success
        currentSessionId = data.session_id;
        displayFileInfo(data);
        completeStep(1);
        activateStep(2);

    } catch (error) {
        showError('upload-error', error.message);
    } finally {
        document.getElementById('upload-loading').classList.remove('show');
    }
}

// Display file information
function displayFileInfo(data) {
    const fileInfo = document.getElementById('file-info');
    const columnSelector = document.getElementById('column-selector');
    const verbatimSelect = document.getElementById('verbatim-column');

    // Populate file info
    fileInfo.innerHTML = `
        <h4>File Information</h4>
        <p><strong>Filename:</strong> ${data.filename}</p>
        <p><strong>Total Rows:</strong> ${data.total_rows}</p>
        <p><strong>Detected Verbatim Column:</strong> ${data.detected_verbatim_column || 'None'}</p>
        <p><strong>Detection Confidence:</strong> ${data.detection_confident ? '✓ High' : '⚠ Low'}</p>
    `;

    // Populate column selector
    verbatimSelect.innerHTML = '';
    data.columns.forEach(col => {
        const option = document.createElement('option');
        option.value = col;
        option.textContent = col;
        if (col === data.detected_verbatim_column) {
            option.selected = true;
        }
        verbatimSelect.appendChild(option);
    });

    fileInfo.style.display = 'block';
    columnSelector.style.display = 'block';

    // If detection is confident, auto-proceed
    if (data.detection_confident) {
        completeStep(2);
        activateStep(3);
        document.getElementById('generate-categories-btn').disabled = false;
    }
}

// Update verbatim column
async function updateColumn() {
    if (!currentSessionId) return;

    const selectedColumn = document.getElementById('verbatim-column').value;
    
    try {
        const response = await fetch(`/sessions/${currentSessionId}/column`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ column: selectedColumn })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to update column');
        }

        showSuccess('column-error', 'Column updated successfully');
        completeStep(2);
        activateStep(3);
        document.getElementById('generate-categories-btn').disabled = false;

    } catch (error) {
        showError('column-error', error.message);
    }
}

// Generate categories
async function generateCategories() {
    if (!currentSessionId) return;

    document.getElementById('categories-loading').classList.add('show');
    document.getElementById('generate-categories-btn').disabled = true;
    clearError('categories-error');

    try {
        const response = await fetch(`/sessions/${currentSessionId}/suggest`, {
            method: 'POST'
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to generate categories');
        }

        displayCategories(data.categories, data.sample_size, data.total_comments);
        completeStep(3);
        activateStep(4);
        document.getElementById('classify-btn').disabled = false;

    } catch (error) {
        showError('categories-error', error.message);
        document.getElementById('generate-categories-btn').disabled = false;
    } finally {
        document.getElementById('categories-loading').classList.remove('show');
    }
}

// Global categories storage
let currentCategories = [];

// Display categories
function displayCategories(categories, sampleSize, totalComments) {
    console.log('=== DISPLAY CATEGORIES START ===');
    console.log('Categories received:', categories);
    console.log('Sample size:', sampleSize, 'Total comments:', totalComments);
    
    currentCategories = categories; // Store for editing
    const categoryList = document.getElementById('category-list');
    const samplePercentage = ((sampleSize / totalComments) * 100).toFixed(1);
    
    categoryList.innerHTML = `
        <h4>Generated Categories:</h4>
        <p class="info"><strong>Analysis:</strong> Analyzed ${samplePercentage}% of comments (${sampleSize} of ${totalComments}) to generate these categories</p>
    `;

    categories.forEach((cat, index) => {
        console.log(`Creating category ${index}:`, cat);
        
        // Create main category item container
        const categoryItem = document.createElement('div');
        categoryItem.className = 'category-item';
        categoryItem.setAttribute('data-index', index);
        categoryItem.style.cssText = `
            position: relative !important;
            background: white !important;
            border: 1px solid #ddd !important;
            padding: 15px 80px 15px 15px !important;
            margin: 8px 0 !important;
            border-radius: 6px !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
            transition: box-shadow 0.2s ease !important;
        `;
        
        // Create display content
        const displayDiv = document.createElement('div');
        displayDiv.className = 'category-display';
        displayDiv.innerHTML = `
            <strong style="font-size: 16px; color: #333;">${cat.title}</strong><br>
            <small style="color: #666; line-height: 1.4;">${cat.description}</small>
        `;
        
        // Create edit form (initially hidden)
        const editForm = document.createElement('div');
        editForm.className = 'category-edit-form';
        editForm.style.display = 'none';
        editForm.innerHTML = `
            <input type="text" class="category-title-input" value="${cat.title}" placeholder="Category Title" style="width: 100%; padding: 8px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box;">
            <textarea class="category-description-input" placeholder="Category Description" style="width: 100%; padding: 8px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; height: 60px; resize: vertical;">${cat.description}</textarea>
            <div class="category-edit-actions" style="margin-top: 10px;">
                <button class="btn" onclick="saveCategory(${index})" style="margin-right: 5px;">Save</button>
                <button class="btn" onclick="cancelEdit(${index})">Cancel</button>
            </div>
        `;
        
        // Create edit button with highly visible styling
        const editButton = document.createElement('button');
        editButton.className = 'category-edit-btn';
        editButton.textContent = 'Edit';
        editButton.setAttribute('data-category-index', index);
        editButton.style.cssText = `
            position: absolute !important;
            top: 8px !important;
            right: 8px !important;
            background: #007bff !important;
            color: white !important;
            border: 2px solid #fff !important;
            padding: 8px 12px !important;
            border-radius: 4px !important;
            cursor: pointer !important;
            font-size: 14px !important;
            font-weight: bold !important;
            z-index: 1000 !important;
            display: block !important;
            visibility: visible !important;
            min-width: 50px !important;
            text-align: center !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2) !important;
        `;
        
        // Add click event listener directly
        editButton.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log(`Edit button clicked for category ${index}`);
            editCategory(index);
        });
        
        // Add hover effects
        editButton.addEventListener('mouseenter', function() {
            this.style.background = '#0056b3 !important';
            this.style.transform = 'translateY(-1px)';
            this.style.boxShadow = '0 4px 8px rgba(0,0,0,0.3) !important';
        });
        
        editButton.addEventListener('mouseleave', function() {
            this.style.background = '#007bff !important';
            this.style.transform = 'translateY(0)';
            this.style.boxShadow = '0 2px 4px rgba(0,0,0,0.2) !important';
        });
        
        // Assemble the category item
        categoryItem.appendChild(displayDiv);
        categoryItem.appendChild(editForm);
        categoryItem.appendChild(editButton);
        
        // Add to the list
        categoryList.appendChild(categoryItem);
        
        console.log(`Category ${index} item created successfully`);
        console.log('Edit button element:', editButton);
        console.log('Category item element:', categoryItem);
    });
    
    // Verify all buttons were created and are visible
    setTimeout(() => {
        console.log('=== VERIFYING EDIT BUTTONS ===');
        const allButtons = document.querySelectorAll('.category-edit-btn');
        console.log(`Found ${allButtons.length} edit buttons out of ${categories.length} categories`);
        
        allButtons.forEach((btn, idx) => {
            const rect = btn.getBoundingClientRect();
            const isVisible = rect.width > 0 && rect.height > 0;
            console.log(`Button ${idx}: visible=${isVisible}, dimensions=${rect.width}x${rect.height}`);
            
            if (!isVisible) {
                console.error(`Button ${idx} is not visible! Forcing visibility...`);
                btn.style.cssText = `
                    position: absolute !important;
                    top: 8px !important;
                    right: 8px !important;
                    background: #dc3545 !important;
                    color: white !important;
                    border: 2px solid #fff !important;
                    padding: 8px 12px !important;
                    border-radius: 4px !important;
                    cursor: pointer !important;
                    font-size: 14px !important;
                    font-weight: bold !important;
                    z-index: 10000 !important;
                    display: block !important;
                    visibility: visible !important;
                    opacity: 1 !important;
                `;
            }
        });
        
        console.log('=== DISPLAY CATEGORIES COMPLETE ===');
    }, 200);
}

// Classify comments
async function classifyComments() {
    if (!currentSessionId) return;

    document.getElementById('classify-loading').classList.add('show');
    document.getElementById('classify-btn').disabled = true;
    clearError('classify-error');

    try {
        // Start polling for progress
        setTimeout(pollClassificationProgress, 500);
        
        console.log('=== SENDING CATEGORIES TO BACKEND ===');
        console.log('Current categories being sent:', currentCategories);
        
        // Send updated categories to backend first
        const updateResponse = await fetch(`/sessions/${currentSessionId}/categories`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ categories: currentCategories })
        });

        if (!updateResponse.ok) {
            const updateData = await updateResponse.json();
            throw new Error(updateData.error || 'Failed to update categories');
        }
        
        const updateData = await updateResponse.json();
        console.log('Categories successfully updated on backend:', updateData);
        
        // Start the classification process
        const response = await fetch(`/sessions/${currentSessionId}/classify`, {
            method: 'POST'
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Classification failed');
        }

        displayResults(data);
        completeStep(4);
        activateStep(5);

    } catch (error) {
        showError('classify-error', error.message);
        document.getElementById('classify-btn').disabled = false;
        document.getElementById('classify-loading').classList.remove('show');
    }
}

// Poll for classification progress
async function pollClassificationProgress() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/sessions/${currentSessionId}/classify/progress`);
        const progress = await response.json();

        if (response.ok && progress.status !== 'not_started') {
            // Update progress bar
            const progressBar = document.getElementById('classify-progress');
            const progressText = document.getElementById('classify-progress-text');
            const loadingElement = document.getElementById('classify-loading');
            
            if (progressBar) {
                progressBar.style.width = `${progress.progress}%`;
            }
            
            if (progressText) {
                progressText.textContent = `${Math.round(progress.progress)}%`;
            }
            
            // Update status text
            const loadingText = loadingElement.querySelector('p');
            if (loadingText) {
                loadingText.textContent = progress.current_step || 'Classifying comments...';
            }

            // Continue polling if not completed
            if (!progress.completed && progress.status !== 'completed') {
                setTimeout(pollClassificationProgress, 1000); // Poll every second
            } else {
                // Classification completed, hide loading
                document.getElementById('classify-loading').classList.remove('show');
            }
        }
    } catch (error) {
        console.error('Progress polling error:', error);
        // Continue polling even if there's an error
        setTimeout(pollClassificationProgress, 2000);
    }
}

// Display results
function displayResults(data) {
    const resultsSummary = document.getElementById('results-summary');
    const resultsContainer = document.getElementById('results-container');
    const downloadButtons = document.getElementById('download-buttons');

    let summaryHTML = `
        <h4>Classification Complete!</h4>
        <p><strong>Total Classified:</strong> ${data.total_classified}</p>
    `;

    resultsSummary.innerHTML = summaryHTML;
    resultsSummary.style.display = 'block';
    
    // Create chart and detailed stats
    createCategoryChart(data.category_counts, data.total_classified);
    createDetailedStats(data.category_counts, data.total_classified);
    
    resultsContainer.style.display = 'block';
    downloadButtons.style.display = 'block';

    completeStep(5);
}

// Download CSV
function downloadCSV() {
    if (!currentSessionId) return;
    window.open(`/sessions/${currentSessionId}/download/csv`, '_blank');
}

// Download PDF with chart image
function downloadPDF() {
    if (!currentSessionId) return;
    
    // Capture chart as image if it exists
    if (categoryChart) {
        const chartImageData = categoryChart.toBase64Image('image/png', 1.0);
        
        // Send chart image data with PDF request
        fetch(`/sessions/${currentSessionId}/download/pdf`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                chart_image: chartImageData 
            })
        })
        .then(response => response.blob())
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'comments_analysis_report.pdf';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        })
        .catch(error => {
            console.error('Error downloading PDF:', error);
            // Fallback to regular PDF download
            window.open(`/sessions/${currentSessionId}/download/pdf`, '_blank');
        });
    } else {
        // No chart available, use regular download
        window.open(`/sessions/${currentSessionId}/download/pdf`, '_blank');
    }
}

// Utility functions
function showError(elementId, message) {
    const errorElement = document.getElementById(elementId);
    errorElement.textContent = message;
    errorElement.style.display = 'block';
}

function showSuccess(elementId, message) {
    const element = document.getElementById(elementId);
    element.textContent = message;
    element.className = 'success';
    element.style.display = 'block';
}

function clearError(elementId) {
    const errorElement = document.getElementById(elementId);
    errorElement.textContent = '';
    errorElement.style.display = 'none';
}

function updateStepStatus() {
    // Update step indicators based on current step
    for (let i = 1; i <= 5; i++) {
        const step = document.getElementById(`step-${getStepName(i)}`);
        const indicator = document.getElementById(`${getStepName(i)}-status`);
        
        if (i < currentStep) {
            step.classList.add('completed');
            step.classList.remove('active');
            indicator.classList.add('completed');
            indicator.classList.remove('pending', 'active');
        } else if (i === currentStep) {
            step.classList.add('active');
            step.classList.remove('completed');
            indicator.classList.add('active');
            indicator.classList.remove('pending', 'completed');
        } else {
            step.classList.remove('active', 'completed');
            indicator.classList.add('pending');
            indicator.classList.remove('active', 'completed');
        }
    }
}

function activateStep(stepNumber) {
    currentStep = stepNumber;
    updateStepStatus();
}

function completeStep(stepNumber) {
    // Mark step as completed but don't change current step
    const step = document.getElementById(`step-${getStepName(stepNumber)}`);
    const indicator = document.getElementById(`${getStepName(stepNumber)}-status`);
    
    step.classList.add('completed');
    indicator.classList.add('completed');
    indicator.classList.remove('pending', 'active');
}

function getStepName(stepNumber) {
    const stepNames = ['', 'upload', 'column', 'categories', 'classify', 'results'];
    return stepNames[stepNumber];
}

// Simulate upload progress
function simulateUploadProgress() {
    const progressBar = document.getElementById('upload-progress');
    const progressText = document.getElementById('upload-progress-text');
    let progress = 0;
    
    const interval = setInterval(() => {
        progress += Math.random() * 15 + 5; // Random increment between 5-20%
        if (progress > 100) progress = 100;
        
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
        }
        
        if (progressText) {
            progressText.textContent = `${Math.round(progress)}%`;
        }
        
        if (progress >= 100) {
            clearInterval(interval);
        }
    }, 200); // Update every 200ms
}

// Edit category
function editCategory(index) {
    console.log(`=== EDIT CATEGORY ${index} ===`);
    const categoryItem = document.querySelector(`[data-index="${index}"]`);
    
    if (!categoryItem) {
        console.error(`Could not find category item with index ${index}`);
        return;
    }
    
    const displayDiv = categoryItem.querySelector('.category-display');
    const editForm = categoryItem.querySelector('.category-edit-form');
    
    if (!displayDiv || !editForm) {
        console.error(`Could not find display div or edit form for category ${index}`);
        return;
    }
    
    console.log('Switching to edit mode for category:', currentCategories[index]);
    
    categoryItem.classList.add('editing');
    displayDiv.style.display = 'none';
    editForm.style.display = 'block';
    editForm.classList.add('show');
    
    // Focus on the title input
    const titleInput = editForm.querySelector('.category-title-input');
    if (titleInput) {
        titleInput.focus();
        titleInput.select();
    }
    
    console.log('Edit mode activated successfully');
}

// Save category
function saveCategory(index) {
    console.log(`=== SAVE CATEGORY ${index} ===`);
    const categoryItem = document.querySelector(`[data-index="${index}"]`);
    
    if (!categoryItem) {
        console.error(`Could not find category item with index ${index}`);
        return;
    }
    
    const titleInput = categoryItem.querySelector('.category-title-input');
    const descriptionInput = categoryItem.querySelector('.category-description-input');
    const displayDiv = categoryItem.querySelector('.category-display');
    const editForm = categoryItem.querySelector('.category-edit-form');
    
    if (!titleInput || !descriptionInput || !displayDiv || !editForm) {
        console.error('Could not find required form elements');
        return;
    }
    
    const newTitle = titleInput.value.trim();
    const newDescription = descriptionInput.value.trim();
    
    if (!newTitle || !newDescription) {
        alert('Please provide both a title and description for the category.');
        return;
    }
    
    console.log('Saving category changes:', {
        oldTitle: currentCategories[index].title,
        newTitle: newTitle,
        oldDescription: currentCategories[index].description,
        newDescription: newDescription
    });
    
    // Update the category data
    currentCategories[index].title = newTitle;
    currentCategories[index].description = newDescription;
    
    // Update the display
    displayDiv.innerHTML = `
        <strong style="font-size: 16px; color: #333;">${currentCategories[index].title}</strong><br>
        <small style="color: #666; line-height: 1.4;">${currentCategories[index].description}</small>
    `;
    
    // Hide edit form and show display
    categoryItem.classList.remove('editing');
    displayDiv.style.display = 'block';
    editForm.style.display = 'none';
    editForm.classList.remove('show');
    
    console.log('Category saved successfully:', currentCategories[index]);
    console.log('Updated categories array:', currentCategories);
}

// Cancel category edit
function cancelEdit(index) {
    console.log(`=== CANCEL EDIT CATEGORY ${index} ===`);
    const categoryItem = document.querySelector(`[data-index="${index}"]`);
    
    if (!categoryItem) {
        console.error(`Could not find category item with index ${index}`);
        return;
    }
    
    const displayDiv = categoryItem.querySelector('.category-display');
    const editForm = categoryItem.querySelector('.category-edit-form');
    const titleInput = categoryItem.querySelector('.category-title-input');
    const descriptionInput = categoryItem.querySelector('.category-description-input');
    
    if (!displayDiv || !editForm || !titleInput || !descriptionInput) {
        console.error('Could not find required form elements');
        return;
    }
    
    console.log('Canceling edit and restoring original values');
    
    // Reset form values to original
    titleInput.value = currentCategories[index].title;
    descriptionInput.value = currentCategories[index].description;
    
    // Hide edit form and show display
    categoryItem.classList.remove('editing');
    displayDiv.style.display = 'block';
    editForm.style.display = 'none';
    editForm.classList.remove('show');
    
    console.log('Edit canceled successfully');
}

// Create category chart
function createCategoryChart(categoryCounts, totalClassified) {
    const ctx = document.getElementById('categoryChart').getContext('2d');
    
    const labels = Object.keys(categoryCounts);
    const data = Object.values(categoryCounts);
    const percentages = data.map(count => ((count / totalClassified) * 100).toFixed(1));
    
    // Generate attractive colors
    const colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
        '#9966FF', '#FF9F40', '#FF6384', '#36A2EB',
        '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40'
    ];
    
    // Destroy existing chart if it exists
    if (categoryChart) {
        categoryChart.destroy();
    }
    
    categoryChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, labels.length),
                borderColor: colors.slice(0, labels.length).map(color => color + '80'),
                borderWidth: 2,
                hoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            layout: {
                padding: {
                    top: 10,
                    bottom: 10,
                    left: 10,
                    right: 10
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    grid: {
                        display: true,
                        color: '#e0e0e0'
                    },
                    ticks: {
                        font: {
                            size: window.innerWidth < 768 ? 10 : 12
                        }
                    }
                },
                y: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        font: {
                            size: window.innerWidth < 768 ? 10 : 12
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed.x;
                            const percentage = ((value / totalClassified) * 100).toFixed(1);
                            return `${value} comments (${percentage}%)`;
                        }
                    },
                    titleFont: {
                        size: window.innerWidth < 768 ? 12 : 14
                    },
                    bodyFont: {
                        size: window.innerWidth < 768 ? 11 : 13
                    }
                }
            },
            animation: {
                duration: 1000
            }
        }
    });
}

// Create detailed statistics
function createDetailedStats(categoryCounts, totalClassified) {
    const detailedStats = document.getElementById('detailed-stats');
    
    let statsHTML = '';
    
    // Sort categories by count (descending)
    const sortedCategories = Object.entries(categoryCounts)
        .sort(([,a], [,b]) => b - a);
    
    sortedCategories.forEach(([category, count], index) => {
        const percentage = ((count / totalClassified) * 100).toFixed(1);
        const barWidth = (count / Math.max(...Object.values(categoryCounts))) * 100;
        
        statsHTML += `
            <div style="margin-bottom: 15px; padding: 10px; border: 1px solid #eee; border-radius: 5px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                    <strong style="color: #333;">${category}</strong>
                    <span style="color: #666; font-weight: bold;">${count} (${percentage}%)</span>
                </div>
                <div style="background: #f0f0f0; height: 8px; border-radius: 4px; overflow: hidden;">
                    <div style="background: linear-gradient(90deg, #007bff, #0056b3); height: 100%; width: ${barWidth}%; transition: width 0.8s ease;"></div>
                </div>
            </div>
        `;
    });
    
    // Add summary statistics
    const avgPerCategory = (totalClassified / sortedCategories.length).toFixed(1);
    const mostCommon = sortedCategories[0];
    const leastCommon = sortedCategories[sortedCategories.length - 1];
    
    statsHTML += `
        <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
            <h5 style="margin-top: 0; color: #333;">Summary</h5>
            <p><strong>Categories:</strong> ${sortedCategories.length}</p>
            <p><strong>Avg per category:</strong> ${avgPerCategory} comments</p>
            <p><strong>Most common:</strong> ${mostCommon[0]} (${((mostCommon[1] / totalClassified) * 100).toFixed(1)}%)</p>
            <p><strong>Least common:</strong> ${leastCommon[0]} (${((leastCommon[1] / totalClassified) * 100).toFixed(1)}%)</p>
        </div>
    `;
    
    detailedStats.innerHTML = statsHTML;
}