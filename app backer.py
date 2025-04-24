import os
import gradio as gr
import anthropic
import requests
import json
import random
import traceback
import logging
from datetime import datetime
from typing import Dict, List, Any

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize API clients
# Note: In production, API keys should be passed as environment variables
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = "claude-3-5-sonnet-20240620"  # Using Claude 3.5 Sonnet for a good balance of capability/cost

# Make sure users set their API keys
if not os.environ.get("ANTHROPIC_API_KEY"):
    logger.warning("ANTHROPIC_API_KEY not set. Please set this environment variable.")
    
if not os.environ.get("RAPIDAPI_KEY"):
    logger.warning("RAPIDAPI_KEY not set. Job search will fall back to sample data.")

# Shared state variables for cross-section data sharing
user_skills = []
selected_skills = []
suggested_jobs = []
saved_jobs = []
selected_job_title = ""

# Sample jobs to use as fallback if API fails
sample_jobs = [
    {
        "title": "HVAC Technician Apprentice",
        "company": "Cool Air Services",
        "location": "Harrisburg, PA",
        "url": "https://example.com/job1",
        "remote": False
    },
    {
        "title": "Customer Service Representative",
        "company": "Retail Support Inc.",
        "location": "Remote",
        "url": "https://example.com/job2",
        "remote": True
    },
    {
        "title": "Warehouse Associate",
        "company": "Distribution Central",
        "location": "Phoenix, AZ",
        "url": "https://example.com/job3",
        "remote": False
    },
    {
        "title": "Office Assistant",
        "company": "Business Solutions LLC",
        "location": "Chicago, IL",
        "url": "https://example.com/job4",
        "remote": False
    },
    {
        "title": "Entry-level Sales Representative",
        "company": "Growth Partners",
        "location": "Dallas, TX",
        "url": "https://example.com/job5",
        "remote": False
    }
]

# Search jobs using the Indeed API
def search_jobs(query, location, limit=10, include_description=False):
    """Search for jobs using the Indeed API"""
    import requests
    
    # The correct URL path according to the documentation
    url = "https://indeed12.p.rapidapi.com/jobs/search"
    
    # Parameter validation and defaults
    if not query:
        query = "entry level"  # Default search term
    
    # More aggressive cleaning for all parameters
    # Remove all non-ASCII characters from query and location
    if isinstance(query, str):
        query = ''.join(char for char in query if ord(char) < 128)
    
    if location and isinstance(location, str):
        location = ''.join(char for char in location if ord(char) < 128)
    
    # Prepare query parameters - EXACTLY matching the example in the API docs
    params = {
        "query": str(query),
        "location": str(location) if location else "remote",
        "page_id": "1",
        "locality": "us",
        "fromage": "1",
        "radius": "50",
        "sort": "date"
    }
    
    # Make sure API key is clean
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if isinstance(api_key, str):
        api_key = ''.join(char for char in api_key if ord(char) < 128)
    
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "indeed12.p.rapidapi.com"
    }
    
    try:
        logger.info(f"Calling Indeed API with params: {params}")
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        
        data = response.json()
        logger.info(f"API response received with structure: {list(data.keys())}")
        
        # The response structure might be different from what we expected
        formatted_jobs = []
        
        # Adjust this part based on the actual API response format
        if "hits" in data:
            job_items = data.get("hits", [])
        else:
            # If the API returns a different structure, try to find the jobs array
            job_items = data.get("jobs", [])
            if not job_items and isinstance(data, list):
                job_items = data  # Sometimes the API returns an array directly
        
        # Process only up to the limit
        for job in job_items[:limit]:
            # The structure might vary, so adapt field paths accordingly
            if "job_data" in job:
                job_data = job.get("job_data", {})
                title = job_data.get("job_title", "Untitled Position")
                company = job_data.get("company_name", "Unknown Company")
                job_location = job_data.get("job_location", {}).get("location_name", 
                                                       location if location else "Remote")
                description = job_data.get("job_description", "No description available") if include_description else ""
                url_link = job_data.get("job_apply_link", "https://indeed.com")
            else:
                # Direct structure - adapt field names based on actual API response
                title = job.get("title", job.get("job_title", "Untitled Position"))
                company = job.get("company", job.get("company_name", "Unknown Company"))
                job_location = job.get("location", location if location else "Remote")
                description = job.get("description", job.get("snippet", "No description available")) if include_description else ""
                url_link = job.get("url", job.get("link", "https://indeed.com"))
            
            # Create a job object with or without description based on the flag
            job_obj = {
                "title": title,
                "company": company,
                "location": job_location,
                "url": url_link,
                "remote": "remote" in str(job_location).lower() or "remote" in str(description).lower()
            }
            
            # Only include description and requirements if requested
            if include_description and description:
                # Limit description length and add ellipsis
                if len(description) > 300:
                    short_description = description.strip()[:300] + "..."
                else:
                    short_description = description
                
                job_obj["description"] = short_description
                job_obj["requirements"] = extract_requirements(description)
            
            formatted_jobs.append(job_obj)
        
        return formatted_jobs
        
    except Exception as e:
        logger.error(f"Error calling Indeed API: {e}")
        logger.error(traceback.format_exc())
        # Fall back to sample jobs if API fails
        return sample_jobs[:limit]  # Use the existing sample_jobs as fallback

def extract_requirements(description):
    """Extract likely requirements from job description"""
    # For a simple extraction, look for common requirement indicators
    if not description:
        return "No requirements specified"
    
    # Look for common requirement sections
    req_indicators = ["requirements", "qualifications", "what you'll need", "what you need", 
                     "skills required", "required skills"]
    
    lower_desc = description.lower()
    
    # Try to find requirements section
    for indicator in req_indicators:
        if indicator in lower_desc:
            # Find the indicator position
            pos = lower_desc.find(indicator)
            # Extract text after the indicator (up to 200 chars)
            req_text = description[pos:pos+200]
            # Trim to the first period or end of string
            period_pos = req_text.find(". ")
            if period_pos > 0:
                req_text = req_text[:period_pos+1]
            return req_text
    
    # If no specific requirements section found, return a generic message
    return "See job description for requirements"

# Generate job titles based on skills
def generate_job_titles(skills, count=10):
    """Generate job title suggestions based on user's skills"""
    # In production, this would use AI to dynamically generate relevant jobs
    # For demo, we'll use a predefined mapping with some randomization
    
    skill_to_jobs = {
        "communication": ["Customer Service Representative", "Sales Associate", "Receptionist", 
                        "Call Center Agent", "Public Relations Assistant"],
        "organization": ["Administrative Assistant", "Office Coordinator", "Data Entry Specialist",
                        "Inventory Clerk", "Project Coordinator"],
        "technical": ["IT Support Technician", "Computer Repair Specialist", "Network Technician",
                     "Software Tester", "Junior Developer"],
        "creative": ["Graphic Design Assistant", "Content Creator", "Social Media Coordinator",
                    "Photography Assistant", "Junior Copywriter"],
        "interpersonal": ["Customer Service Representative", "Sales Associate", "Retail Associate",
                         "Hospitality Staff", "Patient Care Assistant"],
        "problem-solving": ["Technical Support", "Customer Service", "Quality Assurance Tester",
                           "Maintenance Technician", "Help Desk Support"],
        "adaptability": ["Temporary Office Staff", "Event Staff", "Seasonal Retail Associate",
                        "On-Call Support", "Substitute Teacher Assistant"],
        "detail-oriented": ["Quality Control Inspector", "Data Entry Specialist", "Proofreader",
                           "Administrative Assistant", "Inventory Specialist"],
        "time-management": ["Scheduling Coordinator", "Administrative Assistant", "Delivery Driver",
                           "Order Fulfillment Specialist", "Production Assistant"],
        "teamwork": ["Retail Team Member", "Restaurant Staff", "Warehouse Associate",
                    "Customer Support Team Member", "Office Assistant"],
        "leadership": ["Shift Supervisor", "Team Lead", "Assistant Manager",
                      "Project Coordinator", "Training Assistant"],
        "analytical": ["Data Entry Analyst", "Research Assistant", "Inventory Analyst",
                      "Quality Assurance Tester", "Junior Bookkeeper"],
        "physical": ["Warehouse Associate", "Delivery Driver", "Retail Stock Associate",
                    "Manufacturing Assembler", "Fitness Center Staff"],
        "caregiving": ["Home Health Aide", "Childcare Assistant", "Elder Care Provider",
                      "Pet Care Attendant", "Residential Support Staff"],
        "teaching": ["Teacher's Assistant", "Tutor", "After-School Program Staff",
                    "Training Assistant", "Educational Support Staff"]
    }
    
    # Get job suggestions based on skills
    suggested_titles = set()
    for skill in skills:
        skill_lower = skill.lower()
        # Find the closest matching skill category
        for category in skill_to_jobs:
            if category in skill_lower or any(word in skill_lower for word in category.split('-')):
                suggested_titles.update(skill_to_jobs[category])
                break
    
    # If we couldn't find enough matches, add some default options
    defaults = ["Administrative Assistant", "Customer Service Representative", 
                "Retail Associate", "Warehouse Associate", "Data Entry Specialist"]
    
    suggested_titles = list(suggested_titles) if suggested_titles else []
    while len(suggested_titles) < count and defaults:
        default_job = defaults.pop(0)
        if default_job not in suggested_titles:
            suggested_titles.append(default_job)
    
    # If we have too many, randomly select to reach desired count
    if len(suggested_titles) > count:
        suggested_titles = random.sample(suggested_titles, count)
    
    return suggested_titles

# Chat History Management
def format_chat_history(history):
    """Format chat history from Gradio's messages format to Claude API format"""
    formatted_history = []
    try:
        logger.info(f"Formatting chat history: {history}")
        
        for msg in history:
            # Make sure we're just extracting role and content
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                formatted_history.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            else:
                logger.warning(f"Unexpected message format: {msg}")
    except Exception as e:
        logger.error(f"Error formatting chat history: {e}")
        logger.error(traceback.format_exc())
    
    logger.info(f"Formatted history: {formatted_history}")
    return formatted_history

def get_system_prompt(module):
    """Create appropriate system prompt based on the current module"""
    base_prompt = """You are Career Compass, an AI career advisor designed to help users discover career paths, 
    develop skills, and find job opportunities. Be supportive, encouraging, and practical.
    Focus on breaking down complex career goals into achievable steps.
    Always consider the user might have limited education or face barriers to employment.
    Be concise but warm in your responses."""
    
    module_prompts = {
        "skill_mapping": base_prompt + """
        In this module, help the user identify their existing skills, including soft skills and informal experience.
        Ask about their work history, education, hobbies, and life experiences.
        Translate their experiences into recognized transferable skills employers value.
        
        IMPORTANT FORMATTING: After a sufficient conversation, return a structured list of skills in this exact format:
        SKILLS_START
        1. [Skill Name]: [Brief description of how the user demonstrated this skill]
        2. [Skill Name]: [Brief description of how the user demonstrated this skill]
        ... and so on
        SKILLS_END
        
        The SKILLS_START and SKILLS_END tags are critical as they will be used to parse your response.
        Include 5-10 skills based on the conversation. Only include this structured format after sufficient conversation.
        """,
        
        "goal_setting": base_prompt + """
        In this module, help the user set SMART career goals (Specific, Measurable, Achievable, Relevant, Time-bound)
        for the specific job title they're interested in: """ + selected_job_title + """.
        Focus on building their confidence and self-efficacy.
        Break larger goals into small, achievable steps.
        Provide encouragement and address potential obstacles.
        Emphasize progress over perfection and help them visualize success.
        """,
        
        "job_matching": base_prompt + """
        In this module, help the user identify suitable job opportunities based on their skills and goals.
        Consider their constraints (location, schedule, education level).
        Discuss job titles they might not have considered but match their abilities.
        Explain why specific jobs might be a good match.
        Provide practical advice on job applications and interviews for these roles.
        """
    }
    
    return module_prompts.get(module, base_prompt)

# Claude Integration Functions
def get_claude_response(messages, system_prompt, temperature=0.7):
    """Get a response from Claude based on conversation history"""
    try:
        logger.info(f"System prompt: {system_prompt}")
        logger.info(f"Sending messages to Claude: {messages}")
        
        # Clean the messages to ensure only role and content are included
        cleaned_messages = []
        for msg in messages:
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                cleaned_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        logger.info(f"Cleaned messages: {cleaned_messages}")
        
        response = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=cleaned_messages,
            temperature=temperature,
            max_tokens=1000
        )
        
        logger.info(f"Claude response: {response.content[0].text[:100]}...")
        return response.content[0].text
    except Exception as e:
        logger.error(f"Error getting Claude response: {e}")
        logger.error(traceback.format_exc())
        return f"Sorry, I'm having trouble connecting right now. Please try again in a moment."

# Extract skills from AI response
def extract_skills(response):
    """Extract structured skills list from the AI's response"""
    skills = []
    if "SKILLS_START" in response and "SKILLS_END" in response:
        skills_section = response.split("SKILLS_START")[1].split("SKILLS_END")[0].strip()
        skill_items = skills_section.split("\n")
        
        for item in skill_items:
            item = item.strip()
            if item and ":" in item:
                # Extract just the skill name (before the colon)
                skill_name = item.split(":", 1)[0]
                # Remove any numbering
                if "." in skill_name:
                    skill_name = skill_name.split(".", 1)[1]
                skills.append(skill_name.strip())
    
    return skills

# Main application functions for each module
def skill_mapping_chat(message, history):
    """Handle the skill mapping conversation and extract skills when ready"""
    global user_skills
    
    try:
        logger.info(f"Processing skill mapping chat. Message: {message}")
        logger.info(f"Current history: {history}")
        
        history = history or []
        
        # Add the user message to history
        user_message = {"role": "user", "content": message}
        
        # Format the history for Claude
        formatted_history = format_chat_history(history)
        
        # Get Claude's response
        system_prompt = get_system_prompt("skill_mapping")
        response = get_claude_response(formatted_history + [user_message], system_prompt)
        
        # Check if response contains structured skills list
        if "SKILLS_START" in response and "SKILLS_END" in response:
            logger.info("Skills section found in response")
            # Extract skills for later use
            user_skills = extract_skills(response)
            logger.info(f"Extracted skills: {user_skills}")
            
            # Split response to show conversational part only (remove the structured data)
            display_response = response.split("SKILLS_START")[0].strip()
            if "SKILLS_END" in response:
                display_response += "\n\n" + response.split("SKILLS_END")[1].strip()
            
            # Add a prompt to review skills
            display_response += "\n\nI've identified several key skills from our conversation. Click the 'Review My Skills' button below to see them visualized and continue your career journey."
            
            # Update history and return
            updated_history = history.copy()
            updated_history.append(user_message)
            updated_history.append({"role": "assistant", "content": display_response})
            return updated_history, gr.update(visible=True)
        else:
            logger.info("Regular conversation (no skills section)")
            # Regular conversation - update history and return
            updated_history = history.copy()
            updated_history.append(user_message)
            updated_history.append({"role": "assistant", "content": response})
            return updated_history, gr.update(visible=False)
    except Exception as e:
        logger.error(f"Error in skill mapping chat: {e}")
        logger.error(traceback.format_exc())
        
        # Return a friendly error message and keep the conversation going
        error_history = history.copy() if history else []
        error_history.append({"role": "user", "content": message})
        error_history.append({"role": "assistant", "content": f"I apologize for the technical difficulty. Could you please try rephrasing your message or asking something else?"})
        return error_history, gr.update(visible=False)

def goal_setting_chat(message, history):
    """Handle the goal setting conversation"""
    try:
        logger.info(f"Processing goal setting chat. Message: {message}")
        logger.info(f"Current history: {history}")
        logger.info(f"Current selected job title: {selected_job_title}")
        
        history = history or []
        formatted_history = format_chat_history(history)
        
        # Add the user message
        user_message = {"role": "user", "content": message}
        
        # Get Claude's response with the selected job title in the system prompt
        system_prompt = get_system_prompt("goal_setting")
        response = get_claude_response(formatted_history + [user_message], system_prompt)
        
        # Update history and return
        updated_history = history.copy()
        updated_history.append(user_message)
        updated_history.append({"role": "assistant", "content": response})
        return updated_history
    except Exception as e:
        logger.error(f"Error in goal setting chat: {e}")
        logger.error(traceback.format_exc())
        
        # Return a friendly error message and keep the conversation going
        error_history = history.copy() if history else []
        error_history.append({"role": "user", "content": message})
        error_history.append({"role": "assistant", "content": f"I apologize for the technical difficulty. Could you please try rephrasing your message or asking something else?"})
        return error_history

def job_matching_chat(message, history, job_search_results=None):
    """Handle the job matching conversation"""
    try:
        logger.info(f"Processing job matching chat. Message: {message}")
        logger.info(f"Current history: {history}")
        
        history = history or []
        formatted_history = format_chat_history(history)
        
        # Create the user message
        user_message = {"role": "user", "content": message}
        
        # If job search results exist, include them in the prompt
        prompt_message = message
        if job_search_results:
            logger.info(f"Including job search results: {job_search_results}")
            job_info = "\n\nRecent job search results:\n" + json.dumps(job_search_results, indent=2)
            prompt_message += job_info
            prompt_user_message = {"role": "user", "content": prompt_message}
        else:
            prompt_user_message = user_message
        
        # Get Claude's response
        system_prompt = get_system_prompt("job_matching")
        response = get_claude_response(formatted_history + [prompt_user_message], system_prompt)
        
        # Update history and return
        updated_history = history.copy()
        updated_history.append(user_message)  # Add original user message to chat history
        updated_history.append({"role": "assistant", "content": response})
        return updated_history
    except Exception as e:
        logger.error(f"Error in job matching chat: {e}")
        logger.error(traceback.format_exc())
        
        # Return a friendly error message and keep the conversation going
        error_history = history.copy() if history else []
        error_history.append({"role": "user", "content": message})
        error_history.append({"role": "assistant", "content": f"I apologize for the technical difficulty. Could you please try rephrasing your message or asking something else?"})
        return error_history

def job_search(query, location, history):
    """Search for jobs and integrate results into the conversation"""
    # Create loading message
    loading_history = history.copy() if history else []
    loading_history.append({"role": "assistant", "content": f"Searching for jobs matching '{query}' in '{location if location else 'any location'}'..."})
    
    try:
        # Get job search results (without descriptions for efficiency)
        jobs = search_jobs(query, location, include_description=False)
        
        if not jobs:
            # No results found
            updated_history = job_matching_chat(
                f"I searched for '{query}' jobs {('in ' + location) if location else ''} but couldn't find any matches. "
                f"Do you want to try different keywords or locations?", 
                loading_history
            )
            return updated_history, []
        
        # Update conversation with job results
        updated_history = job_matching_chat(
            f"Show me jobs related to: {query}" + 
            (f" in {location}" if location else ""), 
            loading_history, 
            jobs
        )
        
        return updated_history, jobs
        
    except Exception as e:
        logger.error(f"Error in job search: {e}")
        logger.error(traceback.format_exc())
        
        # Return error message
        error_history = loading_history.copy()
        error_history.append({
            "role": "assistant", 
            "content": "I'm having trouble connecting to the job search service right now. Let me show you some sample positions instead."
        })
        
        # Fall back to sample jobs
        return error_history, sample_jobs[:5]

# Functions to handle the new flow
def display_skills():
    """Create visual representation of the extracted skills"""
    global user_skills
    
    try:
        logger.info(f"Displaying skills: {user_skills}")
        
        if not user_skills:
            logger.warning("No skills to display")
            return gr.update(visible=False, choices=[]), gr.update(visible=True, value="No skills have been identified yet. Continue chatting so I can learn more about your abilities.")
        
        # Create a visual representation of skills
        return gr.update(visible=True, choices=user_skills), gr.update(visible=False)
    except Exception as e:
        logger.error(f"Error displaying skills: {e}")
        logger.error(traceback.format_exc())
        return gr.update(visible=False, choices=[]), gr.update(visible=True, value="There was an error displaying your skills. Please try again.")

def select_skills(selected):
    """Handle selection of skills to focus on"""
    global selected_skills, suggested_jobs
    
    try:
        logger.info(f"Selected skills: {selected}")
        
        # Store selected skills (limit to 3)
        selected_skills = selected[:3] if selected else []
        
        if not selected_skills:
            logger.warning("No skills selected")
            return gr.update(visible=False), gr.update(visible=True, value="Please select at least one skill to continue."), gr.update(visible=False)
        
        # Generate job suggestions based on selected skills
        suggested_jobs = generate_job_titles(selected_skills, 10)
        logger.info(f"Generated job titles: {suggested_jobs}")
        
        # Return updates for each component
        return gr.update(visible=True, choices=suggested_jobs, value=[]), gr.update(visible=False), gr.update(visible=True, value=f"Based on your skills in {', '.join(selected_skills)}, here are some job titles you might consider:")
    except Exception as e:
        logger.error(f"Error selecting skills: {e}")
        logger.error(traceback.format_exc())
        return gr.update(visible=False), gr.update(visible=True, value="There was an error processing your skill selection. Please try again."), gr.update(visible=False)

def proceed_to_job_matching(selected_jobs):
    """Handle selection of job titles and transition to job matching tab"""
    global selected_job_title
    
    if not selected_jobs:
        return None
    
    # Store first selected job title for goal setting
    selected_job_title = selected_jobs[0] if selected_jobs else ""
    
    # Update job search query with selected job
    return selected_job_title

def save_job(job):
    """Add a job to the saved jobs list"""
    global saved_jobs
    
    if job and job not in saved_jobs:
        saved_jobs.append(job)
    
    # Update the saved jobs display
    return gr.update(value="\n\n".join([
        f"**{job['title']} - {job['company']}**\n" +
        f"Location: {job['location']}\n" +
        f"Remote: {'Yes' if job['remote'] else 'No'}\n" +
        f"URL: {job['url']}"
        for job in saved_jobs
    ]))

def proceed_to_goal_setting(job_title):
    """Set up goal setting tab with the selected job title"""
    global selected_job_title
    
    # Store the selected job title for goal setting
    selected_job_title = job_title
    
    # Update goal setting welcome message in the new format
    custom_welcome = f"""👋 Welcome to Goal Setting! I'll help you create achievable career goals for becoming a {selected_job_title}.

Let's start by exploring:
- What specific aspects of this role interest you?
- What skills do you already have that apply to this role?
- What skills might you need to develop?
- What timeline are you considering for this career transition?"""
    
    # Return updated welcome message in the new format
    return [{"role": "assistant", "content": custom_welcome}]

# Add this new function to handle the quick prompts
def handle_quick_prompt(prompt, history):
    """Process a pre-filled prompt for skill mapping"""
    return skill_mapping_chat(prompt, history)

# Add the create_quick_prompt function
def create_quick_prompt(prompt_text):
    """Create a function to handle a specific quick prompt"""
    def handle_specific_prompt(history):
        """Handle a specific pre-filled prompt for skill mapping"""
        return skill_mapping_chat(prompt_text, history)
    return handle_specific_prompt

# Initialize welcome messages for each module
WELCOME_MESSAGES = {
    "skill_mapping": [
        {"role": "assistant", "content": """👋 Welcome to Career Compass! Let's start by mapping your skills.

Tell me about:
- Work you've done (paid or unpaid)
- Projects you've completed
- Problems you've solved
- Responsibilities you've handled
- Skills you've taught yourself

Don't worry if they seem informal - many skills are valuable!"""}
    ],

    "goal_setting": [
        {"role": "assistant", "content": """👋 Welcome to Goal Setting! I'll help you create achievable career goals and build confidence.

Let's start by exploring:
- What kind of work interests you?
- What's important to you in a job? (Schedule, pay, location, etc.)
- What obstacles have you faced in reaching your career goals?
- What small step could you take this week toward your career?"""}
    ],

    "job_matching": [
        {"role": "assistant", "content": """👋 Welcome to Job Matching! I'll help you find opportunities that match your skills and goals.

You can:
1. Search for jobs using the search box above
2. Ask me questions about specific careers
3. Get advice on applying for jobs

What type of work are you interested in exploring?"""}
    ]
}

# Check API status
def check_api_status():
    """Check if the Indeed API is accessible"""
    if not os.environ.get("RAPIDAPI_KEY"):
        return "⚠️ API key not set. Using sample job data."
    
    try:
        # Make a minimal API call to check status using ASCII-only query
        result = search_jobs("test", "remote", 1)
        if result and isinstance(result, list) and len(result) > 0:
            return "✅ Indeed API connected"
        else:
            return "⚠️ API returned empty results. Using sample job data."
    except Exception as e:
        logger.error(f"API status check failed: {e}")
        return "❌ API connection failed. Using sample job data."

# UI Building
def build_ui():
    """Create the Gradio interface with the new linear flow"""
    with gr.Blocks(theme=gr.themes.Soft(), title="Career Compass") as app:
        gr.Markdown("# Career Compass 🧭")
        gr.Markdown("Your AI-powered career development assistant")
        
        # Create shared state variables
        job_query = gr.State("")
        
        with gr.Tabs() as tabs:
            # Skill Mapping Tab
            with gr.Tab("✨ Skill Mapping") as skill_tab:
                gr.Markdown("Step 1: Discover your strengths and transferable skills")
                with gr.Row():
                    with gr.Column(scale=2):
                        skill_chat = gr.Chatbot(
                            value=WELCOME_MESSAGES["skill_mapping"],
                            height=400,
                            show_label=False,
                            type="messages"
                        )
                        with gr.Row():
                            skill_msg = gr.Textbox(
                                placeholder="Tell me about your experiences and interests...",
                                show_label=False,
                                scale=9
                            )
                            skill_clear = gr.Button("Clear", scale=1)
                        
                            review_skills_btn = gr.Button("Review My Skills", visible=False)
                    
                    # Skill visualization area (initially hidden)
                    with gr.Column(scale=1, visible=False) as skill_vis_col:
                        gr.Markdown("### Your Identified Skills")
                        skill_error = gr.Markdown("Continue chatting so I can identify your skills.", visible=False)
                        skill_vis = gr.CheckboxGroup(
                            label="Select up to 3 skills you'd like to explore",
                            choices=[],
                            visible=False
                        )
                        skill_selection_error = gr.Markdown("", visible=False)
                        
                        # Keep the skill analysis quick prompts buttons (these aren't redundant)
                        gr.Markdown("### Skill Analysis")
                        with gr.Row():
                            select_skills_btn = gr.Button("🔍 Find Jobs Based on Selected Skills")
                            vis_market_demand_btn = gr.Button("📊 Check Market Demand")
                        
                        with gr.Row():
                            vis_skill_improve_btn = gr.Button("🚀 How To Improve My Skills")
                            vis_remote_jobs_btn = gr.Button("🏠 Find Remote Work With My Skills")
                        
                        
                        
                        gr.Markdown("### Suggested Job Titles") 
                        job_suggestion_text = gr.Markdown("", visible=False)
                        job_suggestions = gr.CheckboxGroup(
                            label="Select job titles you're interested in",
                            choices=[],
                            visible=False
                        )
                        proceed_to_jobs_btn = gr.Button("Explore These Jobs")
                
                # Event handlers for Skill Mapping tab
                result = skill_msg.submit(skill_mapping_chat, [skill_msg, skill_chat], [skill_chat, review_skills_btn]).then(
                    lambda: "", None, skill_msg)
                
                skill_clear.click(lambda: WELCOME_MESSAGES["skill_mapping"], None, skill_chat)
                                
                review_skills_btn.click(
                    fn=lambda: gr.update(visible=True),
                    outputs=skill_vis_col
                )
                
                review_skills_btn.click(
                    display_skills,
                    inputs=None,
                    outputs=[skill_vis, skill_error]
                )
                
                select_skills_btn.click(
                    select_skills,
                    inputs=skill_vis,
                    outputs=[job_suggestions, skill_selection_error, job_suggestion_text]
                )
                
                proceed_to_jobs_btn.click(
                    proceed_to_job_matching,
                    inputs=job_suggestions,
                    outputs=job_query
                ).then(
                    lambda: gr.Tabs(selected=1),
                    inputs=None,
                    outputs=tabs
                )
                
                # Quick prompt button handlers in skill analysis area

                vis_market_demand_btn.click(
                    create_quick_prompt(f"How in-demand are my skills {', '.join(user_skills[:3] if user_skills else [''])} in today's job market? Which ones are most valuable to employers right now?"), 
                    inputs=skill_chat, 
                    outputs=[skill_chat, review_skills_btn]
                )

                vis_skill_improve_btn.click(
                    create_quick_prompt(f"What are some practical ways I could improve or build upon my existing skills {', '.join(user_skills[:3] if user_skills else [''])}? Are there free or low-cost resources you recommend?"), 
                    inputs=skill_chat, 
                    outputs=[skill_chat, review_skills_btn]
                )

                vis_remote_jobs_btn.click(
                    create_quick_prompt(f"What remote work opportunities match my skills {', '.join(user_skills[:3] if user_skills else [''])}? I'm interested in flexible work options."), 
                    inputs=skill_chat, 
                    outputs=[skill_chat, review_skills_btn]
                )
            
            # Job Matching Tab
            with gr.Tab("💼 Job Matching") as job_tab:
                gr.Markdown("Step 2: Find job opportunities that match your skills and goals")
                
                # Add API status indicator
                api_status = gr.Markdown(check_api_status())
                
                with gr.Row():
                    visible_job_query = gr.Textbox(
                        placeholder="Job title, skills, or keywords",
                        label="Search"
                    )
                    job_location = gr.Textbox(placeholder="City, state, or 'remote'", label="Location (optional)")
                    job_search_btn = gr.Button("Search Jobs")
                
                # Sync the job query between tabs
                job_query.change(lambda x: x, job_query, visible_job_query)
                
                with gr.Row():
                    with gr.Column(scale=2):
                        job_chat = gr.Chatbot(
                            value=WELCOME_MESSAGES["job_matching"],
                            height=350,
                            show_label=False,
                            type="messages"
                        )
                        job_msg = gr.Textbox(
                            placeholder="Ask about specific careers or job search advice...",
                            show_label=False
                        )
                        job_clear = gr.Button("Clear Chat")
                    
                    with gr.Column(scale=1):
                        gr.Markdown("### Search Results")
                        # Replace JSON with a DataFrame component
                        job_results = gr.DataFrame(
                            headers=["#", "Title", "Company", "Location", "Remote", "URL"],
                            datatype=["number", "str", "str", "str", "bool", "str"],
                            visible=False,
                            row_count=(5, "dynamic"),
                        )
                        # Store the full job data in a State (hidden from UI)
                        job_data_state = gr.State([])
                        
                        # Replace the dropdown with a number input
                        job_index_input = gr.Number(
                            label="Job Number (from table above)", 
                            minimum=1,
                            step=1,
                            visible=False
                        )
                        save_job_btn = gr.Button("Save Selected Job", visible=False)
                        
                        set_goal_btn = gr.Button("Set Goals for This Career", visible=False)
                        
                        gr.Markdown("### Saved Jobs")
                        saved_jobs_display = gr.Markdown("")
                
                # Event handlers for Job Matching tab
                job_msg.submit(job_matching_chat, [job_msg, job_chat], [job_chat]).then(
                    lambda: "", None, job_msg)
                
                # Update this function to format job results for the DataFrame
                def format_jobs_for_display(jobs):
                    if not jobs:
                        return []
                    
                    # Create data for DataFrame display with row numbers
                    display_data = []
                    
                    for i, job in enumerate(jobs):
                        display_data.append([
                            i+1,  # Add row number (1-based for user friendliness)
                            job["title"],
                            job["company"],
                            job["location"],
                            job["remote"],
                            job["url"]
                        ])
                    
                    return display_data
                
                job_search_btn.click(
                    job_search, 
                    [visible_job_query, job_location, job_chat], 
                    [job_chat, job_data_state]
                ).then(
                    # Clear the results first
                    lambda: [], 
                    None,
                    [job_results]
                ).then(
                    # Just transform the job data for display table
                    lambda jobs: format_jobs_for_display(jobs),
                    inputs=job_data_state,
                    outputs=job_results
                ).then(
                    lambda: gr.update(visible=True),
                    outputs=job_results
                ).then(
                    # Show the number input if we have results
                    lambda jobs: gr.update(visible=len(jobs) > 0, maximum=len(jobs)),
                    inputs=job_data_state,
                    outputs=job_index_input
                ).then(
                    lambda jobs: gr.update(visible=len(jobs) > 0),
                    inputs=job_data_state, 
                    outputs=save_job_btn
                ).then(
                    lambda: gr.update(visible=True),
                    outputs=set_goal_btn
                )
                
                job_clear.click(lambda: WELCOME_MESSAGES["job_matching"], None, job_chat)
                
                # Update the save_selected_job function to work with the number input
                def save_selected_job(selected_index, all_jobs):
                    if not selected_index or not all_jobs:
                        return gr.update(value="Please enter a job number to save.")
                    
                    try:
                        # Convert to zero-based index
                        index = int(selected_index) - 1
                        
                        if index < 0 or index >= len(all_jobs):
                            return gr.update(value=f"Invalid job number. Please enter a number between 1 and {len(all_jobs)}.")
                        
                        # Get the selected job
                        job = all_jobs[index]
                        return save_job(job)
                    except Exception as e:
                        logger.error(f"Error in save_selected_job: {e}")
                        return gr.update(value="Error saving job. Please try again.")
                
                save_job_btn.click(
                    save_selected_job,
                    inputs=[job_index_input, job_data_state],
                    outputs=saved_jobs_display
                )
                
                # Goal tab state for passing job title
                goal_chat_state = gr.State([])
                
                set_goal_btn.click(
                    proceed_to_goal_setting,
                    inputs=visible_job_query,
                    outputs=goal_chat_state
                ).then(
                    lambda: gr.Tabs(selected=2),
                    inputs=None,
                    outputs=tabs
                )
            
            # Goal Setting Tab
            with gr.Tab("🎯 Goal Setting") as goal_tab:
                gr.Markdown("Step 3: Set achievable career goals and build confidence")
                with gr.Column():
                    goal_chat = gr.Chatbot(
                        value=WELCOME_MESSAGES["goal_setting"],
                        height=400,
                        show_label=False,
                        type="messages"
                    )
                    goal_msg = gr.Textbox(
                        placeholder="Share your career aspirations and concerns...",
                        show_label=False
                    )
                    goal_clear = gr.Button("Clear Chat")
                
                # Transfer state from job tab to goal tab
                goal_chat_state.change(lambda x: x, goal_chat_state, goal_chat)
                
                goal_msg.submit(goal_setting_chat, [goal_msg, goal_chat], [goal_chat]).then(
                    lambda: "", None, goal_msg)
                goal_clear.click(lambda: WELCOME_MESSAGES["goal_setting"], None, goal_chat)
        
        # About section
        with gr.Accordion("About Career Compass", open=False):
            gr.Markdown("""
            ## Career Compass
            
            Career Compass helps you navigate your career journey through:
            
            * **Skill Mapping** - Discover your strengths and transferable skills
            * **Goal Setting** - Build confidence and create achievable career goals
            * **Job Matching** - Find opportunities that fit your unique abilities
            
            This tool is designed to be supportive and practical, meeting you where you are in your career journey.
            """)
    
    return app

# Main application
def main():
    app = build_ui()
    app.launch()

if __name__ == "__main__":
    main()
