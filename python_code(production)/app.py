"""
Intelligent Workflow Assistant
An AI-powered email processing system for customer support automation
"""

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_SHEETS_CREDS = os.getenv('GOOGLE_SHEETS_CREDS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', 'mock-spreadsheet-id')
MOCK_MODE = os.getenv('MOCK_MODE', 'false').lower() == 'true'

# Initialize OpenAI client
openai_client = None
if OPENAI_API_KEY and not MOCK_MODE:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Google Sheets client
sheets_client = None
if GOOGLE_SHEETS_CREDS and not MOCK_MODE:
    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDS)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        sheets_client = gspread.authorize(credentials)
    except Exception as e:
        print(f"Google Sheets initialization failed: {e}")
        sheets_client = None


def process_email_with_ai(email_content):
    """
    Process email content using OpenAI to extract key information
    
    Args:
        email_content (str): The email text to process
        
    Returns:
        dict: Extracted information including summary, customer name, topic, urgency
    """
    if MOCK_MODE or not openai_client:
        # Mock response for testing without API keys
        return {
            "summary": "Mock summary: Customer requesting help with login issues",
            "customer_name": "John Doe",
            "topic": "Login Issues",
            "urgency": "high"
        }
    
    try:
        prompt = f"""You are an AI assistant helping a customer support team. 
Analyze the following email and extract key information.

Email:
{email_content}

Please respond with ONLY a JSON object in this exact format:
{{
    "summary": "A brief 1-2 sentence summary of the email",
    "customer_name": "The customer's name (or 'Unknown' if not found)",
    "topic": "The main topic/category (e.g., Technical Issue, Billing, Feature Request)",
    "urgency": "high, medium, or low based on the email content"
}}

Do not include any other text, just the JSON object."""

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts structured information from customer support emails. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        # Parse the JSON response
        content = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        extracted_data = json.loads(content)
        
        # Validate required fields
        required_fields = ["summary", "customer_name", "topic", "urgency"]
        for field in required_fields:
            if field not in extracted_data:
                extracted_data[field] = "Unknown"
        
        # Normalize urgency
        urgency = extracted_data["urgency"].lower()
        if urgency not in ["high", "medium", "low"]:
            extracted_data["urgency"] = "medium"
        
        return extracted_data
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        print(f"Raw content: {content}")
        # Return a fallback response
        return {
            "summary": "Error processing email - manual review required",
            "customer_name": "Unknown",
            "topic": "Error",
            "urgency": "medium"
        }
    except Exception as e:
        print(f"OpenAI API error: {e}")
        raise Exception(f"AI processing failed: {str(e)}")


def create_task_in_sheets(extracted_data, original_email):
    """
    Create a new task record in Google Sheets
    
    Args:
        extracted_data (dict): Extracted information from AI
        original_email (str): The original email content
        
    Returns:
        dict: Result of the operation
    """
    if MOCK_MODE or not sheets_client:
        # Mock response
        return {
            "success": True,
            "message": "Task created in mock mode",
            "row_number": 42,
            "sheet_url": "https://docs.google.com/spreadsheets/d/mock-spreadsheet-id"
        }
    
    try:
        # Open the spreadsheet
        spreadsheet = sheets_client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.sheet1
        
        # Prepare row data
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [
            timestamp,
            extracted_data.get("customer_name", "Unknown"),
            extracted_data.get("topic", "Unknown"),
            extracted_data.get("urgency", "medium"),
            extracted_data.get("summary", "No summary"),
            original_email[:500]  # Truncate long emails
        ]
        
        # Append the row
        worksheet.append_row(row_data)
        
        # Get the row number
        row_number = len(worksheet.get_all_values())
        
        return {
            "success": True,
            "message": "Task created successfully",
            "row_number": row_number,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        }
        
    except Exception as e:
        print(f"Google Sheets error: {e}")
        raise Exception(f"Failed to create task in sheets: {str(e)}")


@app.route('/')
def index():
    """Render the main UI"""
    mode_message = "Running in MOCK MODE (no API calls)" if MOCK_MODE else "Live mode with API integration"
    return render_template('index.html', mode=mode_message)


@app.route('/process', methods=['POST'])
def process_email():
    """
    Main endpoint to process an email
    Accepts JSON with 'email_content' field
    """
    try:
        # Get email content from request
        if request.is_json:
            data = request.get_json()
            email_content = data.get('email_content', '')
        else:
            email_content = request.form.get('email_content', '')
        
        if not email_content or len(email_content.strip()) < 10:
            return jsonify({
                "success": False,
                "error": "Email content is required and must be at least 10 characters"
            }), 400
        
        # Step 1: Process with AI
        print("Processing email with AI...")
        extracted_data = process_email_with_ai(email_content)
        
        # Step 2: Create task in tracking system
        print("Creating task in Google Sheets...")
        task_result = create_task_in_sheets(extracted_data, email_content)
        
        # Return complete response
        return jsonify({
            "success": True,
            "extracted_data": extracted_data,
            "task_created": task_result,
            "message": "Email processed successfully!"
        })
        
    except Exception as e:
        print(f"Error processing email: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "mock_mode": MOCK_MODE,
        "openai_configured": bool(openai_client),
        "sheets_configured": bool(sheets_client)
    })


if __name__ == '__main__':
    print("=" * 60)
    print("Intelligent Workflow Assistant")
    print("=" * 60)
    print(f"Mock Mode: {MOCK_MODE}")
    print(f"OpenAI Configured: {bool(openai_client)}")
    print(f"Google Sheets Configured: {bool(sheets_client)}")
    print("=" * 60)
    print("\nStarting server on http://localhost:5000")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
