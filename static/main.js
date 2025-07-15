// Global variables
let currentSessionId = null;
let currentStep = 1;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    setupFileUpload();
    updateStepStatus();
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

        displayCategories(data.categories);
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

// Display categories
function displayCategories(categories) {
    const categoryList = document.getElementById('category-list');
    categoryList.innerHTML = '<h4>Generated Categories:</h4>';

    categories.forEach(cat => {
        const categoryItem = document.createElement('div');
        categoryItem.className = 'category-item';
        categoryItem.innerHTML = `
            <strong>${cat.title}</strong><br>
            <small>${cat.description}</small>
        `;
        categoryList.appendChild(categoryItem);
    });
}

// Classify comments
async function classifyComments() {
    if (!currentSessionId) return;

    document.getElementById('classify-loading').classList.add('show');
    document.getElementById('classify-btn').disabled = true;
    clearError('classify-error');

    try {
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
    } finally {
        document.getElementById('classify-loading').classList.remove('show');
    }
}

// Display results
function displayResults(data) {
    const resultsSummary = document.getElementById('results-summary');
    const downloadButtons = document.getElementById('download-buttons');

    let summaryHTML = `
        <h4>Classification Complete!</h4>
        <p><strong>Total Classified:</strong> ${data.total_classified}</p>
        <h5>Category Breakdown:</h5>
    `;

    Object.entries(data.category_counts).forEach(([category, count]) => {
        const percentage = ((count / data.total_classified) * 100).toFixed(1);
        summaryHTML += `<p><strong>${category}:</strong> ${count} (${percentage}%)</p>`;
    });

    resultsSummary.innerHTML = summaryHTML;
    resultsSummary.style.display = 'block';
    downloadButtons.style.display = 'block';

    completeStep(5);
}

// Download CSV
function downloadCSV() {
    if (!currentSessionId) return;
    window.open(`/sessions/${currentSessionId}/download/csv`, '_blank');
}

// Download PDF
function downloadPDF() {
    if (!currentSessionId) return;
    window.open(`/sessions/${currentSessionId}/download/pdf`, '_blank');
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