import os
import re
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
saved_goals = []

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
            # The structure might vary, so adapt field paths ingly
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
    """Generate job title suggestions based on user's skills using Claude AI"""
    try:
        logger.info(f"Generating job titles for skills: {skills}")
        
        if not skills or not isinstance(skills, list):
            logger.warning("No skills provided or invalid format")
            # Fallback to default options if no skills
            return ["Administrative Assistant", "Customer Service Representative", 
                    "Retail Associate", "Warehouse Associate", "Data Entry Specialist"]
        
        # Create a prompt for Claude to suggest job titles based on skills
        prompt = [
            {"role": "user", "content": f"""Based on the following skills, suggest {count} relevant entry-level 
            or early-career job titles that would be good matches. These should be realistic positions 
            that don't require extensive experience or advanced degrees.
            
            Skills: {', '.join(skills)}
            
            Return ONLY a simple list of job titles, one per line. Do not include explanations, 
            descriptions, or formatting beyond the titles themselves."""}
        ]
        
        # Get job title suggestions from Claude
        system_prompt = """You are a career advisor specializing in helping people find entry-level and 
        early-career positions based on their transferable skills. Focus on practical, accessible job titles 
        that don't require extensive experience or advanced education."""
        
        response = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=prompt,
            temperature=0.7,
            max_tokens=500
        )
        
        # Process the response to extract job titles
        job_titles_text = response.content[0].text.strip()
        logger.info(f"Claude response raw: {job_titles_text[:100]}...")
        
        # Parse job titles from response (handling different formats)
        job_titles = []
        for line in job_titles_text.split('\n'):
            # Remove any list markers or extra formatting
            cleaned_line = line.strip()
            # Remove numbered list markers (1., 2., etc.)
            if cleaned_line and re.match(r'^\d+\.', cleaned_line):
                cleaned_line = re.sub(r'^\d+\.\s*', '', cleaned_line)
            # Remove bullet points
            cleaned_line = cleaned_line.replace('• ', '').replace('* ', '')
            
            if cleaned_line:
                job_titles.append(cleaned_line)
        
        # Ensure we don't exceed requested count
        job_titles = job_titles[:count]
        
        logger.info(f"Generated {len(job_titles)} job titles: {job_titles}")
        
        # If we didn't get enough suggestions, add some defaults
        defaults = ["Administrative Assistant", "Customer Service Representative", 
                    "Retail Associate", "Warehouse Associate", "Data Entry Specialist"]
        
        while len(job_titles) < count and defaults:
            default_job = defaults.pop(0)
            if default_job not in job_titles:
                job_titles.append(default_job)
        
        return job_titles
        
    except Exception as e:
        logger.error(f"Error generating job titles: {e}")
        logger.error(traceback.format_exc())
        
        # Fallback to default options if the AI call fails
        defaults = ["Administrative Assistant", "Customer Service Representative", 
                    "Retail Associate", "Warehouse Associate", "Data Entry Specialist",
                    "Office Assistant", "Sales Associate", "Receptionist", 
                    "Customer Support Representative", "Inventory Clerk"]
        
        return defaults[:count]

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
        for the job titles they've expressed interest in throughout the conversation.
        
        Focus on building their confidence and self-efficacy.
        Break larger goals into small, achievable steps.
        Provide encouragement and address potential obstacles.
        Emphasize progress over perfection and help them visualize success.
        
        If the user asks about a specific job title, focus your goal recommendations on that role.
        Consider both short-term goals (next 3 months) and longer-term goals (6-12 months).
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
    """Handle the goal setting conversation with job context"""
    global saved_jobs, selected_job_title, suggested_jobs
    
    try:
        logger.info(f"Processing goal setting chat. Message: {message}")
        logger.info(f"Current history: {history}")
        
        # Get available job context
        available_jobs = []
        if saved_jobs:
            available_jobs = [job["title"] for job in saved_jobs]
        elif selected_job_title:
            available_jobs = [selected_job_title]
        elif suggested_jobs:
            available_jobs = suggested_jobs[:3]
            
        job_context = "Jobs of interest: " + ", ".join(available_jobs) if available_jobs else ""
        logger.info(f"Job context for goal setting: {job_context}")
        
        history = history or []
        formatted_history = format_chat_history(history)
        
        # Add the user message
        user_message = {"role": "user", "content": message}
        
        # Create system prompt with job context
        system_prompt = get_system_prompt("goal_setting") + "\n" + job_context
        
        # Get Claude's response
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
        error_history.append({"role": "assistant", "content": "I apologize for the technical difficulty. Could you please try rephrasing your message or asking something else?"})
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

def job_search(query, location, industry, history):
    """Search for jobs and integrate results into the conversation"""
    # Create loading message
    loading_history = history.copy() if history else []
    industry_text = f" in the {industry} industry" if industry and industry != "Any Industry" else ""
    loading_history.append({"role": "assistant", "content": f"Searching for jobs matching '{query}'{industry_text} in '{location if location else 'any location'}'..."})
    
    try:
        # Build a combined query with industry if specified
        search_query = query
        if industry and industry != "Any Industry":
            search_query = f"{query} {industry}"
            
        # Get job search results (without descriptions for efficiency)
        jobs = search_jobs(search_query, location, include_description=False)
        
        if not jobs:
            # No results found
            updated_history = job_matching_chat(
                f"I searched for '{query}' jobs{industry_text} {('in ' + location) if location else ''} but couldn't find any matches. "
                f"Do you want to try different keywords or locations?", 
                loading_history
            )
            return updated_history, []
        
        # Update conversation with job results
        updated_history = job_matching_chat(
            f"Show me jobs related to: {query}{industry_text}" + 
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

# Create a new function to load goals tab with saved jobs
def initialize_goal_setting():
    """Initialize goal setting tab with saved jobs from earlier steps"""
    global saved_jobs, selected_job_title, suggested_jobs
    
    available_jobs = []
    
    # First priority: use saved jobs from job search
    if saved_jobs:
        available_jobs = [job["title"] for job in saved_jobs]
    # Second priority: use the selected job title from skill mapping
    elif selected_job_title:
        available_jobs = [selected_job_title]
    # Third priority: use suggested jobs from skill mapping
    elif suggested_jobs:
        available_jobs = suggested_jobs[:3]  # Limit to 3 suggestions
    
    if not available_jobs:
        # Default welcome if no jobs are available
        return WELCOME_MESSAGES["goal_setting"]
    
    # Create a custom welcome message with the available jobs
    job_list = ", ".join([f"**{job}**" for job in available_jobs])
    
    custom_welcome = f"""👋 Welcome to Goal Setting! 

I noticed you've shown interest in these careers: {job_list}

I can help you:
- Identify skills needed for these roles
- Create achievable goals to build those skills
- Develop a step-by-step plan for career growth
- Address any concerns or obstacles

Which role would you like to focus on first?"""
    
    return [{"role": "assistant", "content": custom_welcome}]

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

# Add a function to create quick prompts for the goal setting tab
def create_goal_quick_prompt(prompt_text):
    """Create a function to handle a specific quick prompt for goal setting"""
    def handle_specific_goal_prompt(history):
        """Handle a specific pre-filled prompt for goal setting"""
        return goal_setting_chat(prompt_text, history)
    return handle_specific_goal_prompt

# Add debug logging to save_goal function
def save_goal(goal_text, job_title):
    """Save a goal to the saved goals list"""
    global saved_goals
    
    logger.info(f"save_goal called with text: '{goal_text}', job title: '{job_title}'")
    
    if not goal_text:
        logger.warning("Empty goal text, not saving")
        return [], gr.update(visible=False), gr.update(visible=True)
    
    # Create a goal object with completion status
    goal = {
        "text": goal_text,
        "job_title": job_title if job_title else "General Career Goal",
        "date_added": datetime.now().strftime("%Y-%m-%d"),
        "completed": False
    }
    
    # Add to saved goals
    saved_goals.append(goal)
    logger.info(f"Goal added. saved_goals now contains {len(saved_goals)} goals")
    logger.info(f"Latest goal: {goal}")
    
    # Print the entire saved_goals list for debugging
    logger.info(f"Full saved_goals list: {saved_goals}")
    
    # Update the saved goals display
    result = update_saved_goals_display()
    logger.info(f"update_saved_goals_display returned: {result}")
    return result

# Add this after saving a goal
def check_table_visibility():
    """Check if the table should be visible and force visibility if needed"""
    global saved_goals
    if saved_goals:
        return gr.update(visible=True), gr.update(visible=False)
    else:
        return gr.update(visible=False), gr.update(visible=True)

# Update the update_saved_goals_display function to add clearer completion status
def update_saved_goals_display():
    """Update the display of saved goals in tabular format"""
    global saved_goals
    
    logger.info(f"update_saved_goals_display called, saved_goals length: {len(saved_goals)}")
    
    if not saved_goals:
        logger.info("No saved goals found, hiding table and showing message")
        return [], gr.update(visible=False), gr.update(visible=True)
    
    # Format goals as table rows with clearer completion visualization
    display_data = []
    
    for i, goal in enumerate(saved_goals):
        # Make the completion status more visible with symbols or text
        completion_display = "✅ Complete" if goal["completed"] else "❌ Incomplete"
        
        display_data.append([
            i,  # Goal ID (hidden from user but used for toggling)
            goal["text"],
            goal["job_title"],
            goal["date_added"],
            completion_display  # Use text instead of just boolean for better UX
        ])
    
    logger.info(f"Formatted {len(display_data)} goals for table display")
    logger.info(f"Table data: {display_data}")
    logger.info(f"Returning: data={len(display_data)} rows, table visible=True, message visible=False")
    
    # Force explicit visibility update to ensure table appears
    return display_data, gr.update(visible=True), gr.update(visible=False)

# Update the toggle_goal_in_table function to be more robust
def toggle_goal_in_table(evt: gr.SelectData, goals):
    """Toggle the completion status of a goal when clicked in the table"""
    global saved_goals
    
    try:
        logger.info(f"toggle_goal_in_table called with event: {evt}")
        logger.info(f"Current goals table data: {goals}")
        
        # Get the row that was clicked
        row_index = evt.index[0]
        col_index = evt.index[1]  # Also track column
        
        logger.info(f"Row index clicked: {row_index}, Column index: {col_index}")
        
        # Only toggle if user clicked the "Completed" column (index 4) or the whole row
        if col_index == 4 or col_index is None:
            if 0 <= row_index < len(saved_goals):
                # Get the actual goal ID from the first column
                goal_id = goals[row_index][0] if goals and len(goals) > row_index else row_index
                logger.info(f"Goal ID to toggle: {goal_id}")
                
                # Toggle the completion status
                if 0 <= goal_id < len(saved_goals):
                    current_status = saved_goals[goal_id]["completed"]
                    saved_goals[goal_id]["completed"] = not current_status
                    logger.info(f"Toggled goal completion from {current_status} to {saved_goals[goal_id]['completed']}")
                    
                    # Return updated goals
                    result = update_saved_goals_display()
                    logger.info(f"Updated display after toggle: {result}")
                    return result
                else:
                    logger.warning(f"Invalid goal ID: {goal_id}")
            else:
                logger.warning(f"Invalid row index: {row_index}")
        else:
            logger.info(f"Click on non-completion column: {col_index}, not toggling")
        
        # No changes, return current state
        return goals, gr.update(visible=True), gr.update(visible=False)
    except Exception as e:
        logger.error(f"Error toggling goal in table: {e}")
        logger.error(traceback.format_exc())
        return goals, gr.update(visible=True), gr.update(visible=False)

# Add debug function for saved goals
def debug_saved_goals():
    """Debug function to check saved goals state"""
    global saved_goals
    logger.info(f"DEBUG: Current saved goals: {saved_goals}")
    
    # Return a message showing the number of saved goals
    message = f"DEBUG: There are {len(saved_goals)} saved goals."
    if saved_goals:
        message += "\n\nGoals in memory:\n"
        for i, goal in enumerate(saved_goals):
            message += f"{i}: {goal['text']} ({goal['job_title']}) - {'Completed' if goal['completed'] else 'Incomplete'}\n"
    
    # Try to force the table to update
    display_data = []
    for i, goal in enumerate(saved_goals):
        display_data.append([
            i, goal["text"], goal["job_title"], goal["date_added"], goal["completed"]
        ])
    
    return message, display_data, gr.update(visible=len(saved_goals) > 0), gr.update(visible=len(saved_goals) == 0)

# Add a new force refresh function
def force_refresh_goals_table():
    """Force refresh the goals table display"""
    global saved_goals
    
    logger.info(f"Force refreshing goals table with {len(saved_goals)} goals")
    
    if not saved_goals:
        return [], gr.update(visible=False), gr.update(visible=True)
    
    # Format goals as table rows
    display_data = []
    for i, goal in enumerate(saved_goals):
        display_data.append([
            i,
            goal["text"],
            goal["job_title"],
            goal["date_added"],
            goal["completed"]
        ])
    
    # Explicitly force table visibility
    return display_data, gr.update(visible=True), gr.update(visible=False)

# Add a direct goal completion toggle function
def toggle_goal_completion(goal_id):
    """Directly toggle a goal's completion status by ID"""
    global saved_goals
    
    logger.info(f"Directly toggling goal completion for goal ID: {goal_id}")
    
    try:
        # Convert to integer if needed
        goal_id = int(goal_id) if isinstance(goal_id, str) and goal_id.isdigit() else goal_id
        
        if isinstance(goal_id, int) and 0 <= goal_id < len(saved_goals):
            # Toggle the completion status
            current_status = saved_goals[goal_id]["completed"]
            new_status = not current_status
            saved_goals[goal_id]["completed"] = new_status
            
            logger.info(f"Goal {goal_id} toggled from {current_status} to {new_status}")
            
            # Return updated data and updated message
            return (f"Changed goal '{saved_goals[goal_id]['text']}' status to: "
                   f"{'✅ Completed' if new_status else '❌ Not Completed'}")
        else:
            logger.warning(f"Invalid goal ID to toggle: {goal_id}")
            return "Error: Invalid goal ID"
            
    except Exception as e:
        logger.error(f"Error in toggle_goal_completion: {e}")
        logger.error(traceback.format_exc())
        return f"Error toggling goal: {str(e)}"

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
            with gr.Tab("✨ 1. Skill Mapping") as skill_tab:
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
                                scale=7
                            )
                            skill_enter_btn = gr.Button("Enter", scale=1)
                            skill_clear = gr.Button("Clear Chat", scale=2)
                            
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
                            label="Select a job title you're interested in",
                            choices=[],
                            visible=False
                        )
                        proceed_to_jobs_btn = gr.Button("Explore This Job")
                
                # Event handlers for Skill Mapping tab
                result = skill_msg.submit(skill_mapping_chat, [skill_msg, skill_chat], [skill_chat, review_skills_btn]).then(
                    lambda: "", None, skill_msg)
                
                skill_enter_btn.click(
                    skill_mapping_chat, 
                    [skill_msg, skill_chat], 
                    [skill_chat, review_skills_btn]
                ).then(
                    lambda: "", None, skill_msg
                )
                
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
            with gr.Tab("💼 2. Job Matching") as job_tab:
                gr.Markdown("Step 2: Find job opportunities that match your skills and goals")
                
                # Add API status indicator
                api_status = gr.Markdown(check_api_status())
                
                with gr.Row():
                    with gr.Column(scale=3):
                        visible_job_query = gr.Textbox(
                            placeholder="Job title, skills, or keywords",
                            label="Search"
                        )
                    with gr.Column(scale=3):
                        job_location = gr.Textbox(
                            placeholder="City, state, or 'remote'", 
                            label="Location (optional)"
                        )
                with gr.Row():
                    with gr.Column(scale=3):
                        job_industry = gr.Dropdown(
                            choices=["Any Industry", "Healthcare", "Technology", "Retail", 
                                     "Manufacturing", "Education", "Finance", "Hospitality", 
                                     "Construction", "Transportation", "Administrative"],
                            value="Any Industry",
                            label="Industry (optional)"
                        )
                    with gr.Column(scale=3, min_width=100):
                        job_search_btn = gr.Button("Search Jobs", size="lg")
                
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
                    [visible_job_query, job_location, job_industry, job_chat], 
                    [job_chat, job_data_state]
                ).then(
                    # Clear the results first
                    lambda: [], 
                    None,
                    [job_results]
                ).then(
                    # Transform the job data for display table
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
                
            
            # Goal Setting Tab
            with gr.Tab("🎯 3. Goal Setting") as goal_tab:
                gr.Markdown("Step 3: Set achievable career goals and build confidence")
                with gr.Row():
                    with gr.Column(scale=2):
                        goal_chat = gr.Chatbot(
                            value=WELCOME_MESSAGES["goal_setting"],
                            height=400,
                            show_label=False,
                            type="messages"
                        )
                        with gr.Row():
                            goal_msg = gr.Textbox(
                                placeholder="Share your career aspirations and concerns...",
                                show_label=False,
                                scale=9
                            )
                            goal_clear = gr.Button("Clear", scale=1)
                        
                        # Add quick prompt buttons for goal setting
                        gr.Markdown("### Quick Goal Prompts")
                        with gr.Row():
                            create_goals_btn = gr.Button("🎯 Create Achievable Skill-Building Goals")
                            create_plan_btn = gr.Button("📝 Develop Step-by-Step Career Plan")
                        
                        with gr.Row():
                            current_role_btn = gr.Button("🚀 How To Advance In Current Role")
                            overcome_barriers_btn = gr.Button("🧠 Overcome Career Barriers")
                    
                    # Add a column for goal saving and tracking
                    with gr.Column(scale=1):
                        gr.Markdown("### Save Your Goal")
                        goal_text = gr.Textbox(
                            label="Goal to Save",
                            placeholder="Enter a specific goal you want to save...",
                            lines=3
                        )
                        goal_job = gr.Textbox(
                            label="Related Job Role (optional)",
                            placeholder="Enter the job role this goal relates to"
                        )
                        save_goal_btn = gr.Button("Save This Goal")
                        
                        gr.Markdown("### Your Saved Goals")
                        # Debug button to check saved goals
                        debug_goals_btn = gr.Button("Debug: Check Saved Goals")
                        
                        goal_instructions = gr.Markdown(
                            """### Managing Your Goals
                            - Each goal has an ID number in the first column
                            - To change a goal's completion status:
                              1. Enter the goal ID in the "Goal ID to Toggle" field below
                              2. Click "Toggle Completion Status"
                            - Goals marked ✅ are complete, ❌ are incomplete""", 
                            visible=False
                        )
                        saved_goals_table = gr.DataFrame(
                            headers=["ID", "Goal", "Job Role", "Date Added", "Completed"],
                            datatype=["number", "str", "str", "str", "bool"],
                            col_count=(5, "fixed"),
                            interactive=True,  # Changed from False to True to enable interactions
                            visible=False,
                            wrap=True,
                            elem_id="saved_goals_table"  # Add an element ID for easier debugging
                        )
                        no_goals_message = gr.Markdown("No goals saved yet. Create goals in the chat and save them here.")
                        
                        # Add a new debugging output element
                        debug_output = gr.Markdown("Debug information will appear here")
                        
                        # Add a force refresh button
                        force_refresh_btn = gr.Button("Force Refresh Table")
                        force_refresh_btn.click(
                            force_refresh_goals_table,
                            inputs=[],
                            outputs=[saved_goals_table, goal_instructions, no_goals_message]
                        )
                        
                        with gr.Row():
                            goal_toggle_id = gr.Number(
                                label="Goal ID to Toggle",
                                info="Enter the ID from the table above",
                                minimum=0,
                                step=1,
                                precision=0
                            )
                            goal_toggle_btn = gr.Button("Toggle Completion Status")

                        goal_status_msg = gr.Markdown("")

                        goal_toggle_btn.click(
                            toggle_goal_completion,
                            inputs=[goal_toggle_id],
                            outputs=[goal_status_msg]
                        ).then(
                            force_refresh_goals_table,
                            inputs=[],
                            outputs=[saved_goals_table, goal_instructions, no_goals_message]
                        )
                
                # Transfer state from job tab to goal tab
                goal_chat_state.change(lambda x: x, goal_chat_state, goal_chat)
                
                # Event handlers for the goal setting tab
                goal_msg.submit(goal_setting_chat, [goal_msg, goal_chat], [goal_chat]).then(
                    lambda: "", None, goal_msg)
                goal_clear.click(lambda: WELCOME_MESSAGES["goal_setting"], None, goal_chat)
                
                # Add event handlers for quick prompts
                create_goals_btn.click(
                    create_goal_quick_prompt("Based on our discussion, can you suggest 3-5 specific, achievable goals to help me build the key skills needed for this role? I'd like a mix of short-term (1-3 months) and medium-term (3-6 months) goals."), 
                    inputs=goal_chat, 
                    outputs=goal_chat
                )
                
                create_plan_btn.click(
                    create_goal_quick_prompt("Can you create a step-by-step career development plan for me? I'd like specific actions I can take over the next 6 months to make progress toward this career."), 
                    inputs=goal_chat, 
                    outputs=goal_chat
                )
                
                current_role_btn.click(
                    create_goal_quick_prompt("I'm currently employed but want to grow in my role or prepare for advancement. What specific goals would help me develop professionally while in my current position?"), 
                    inputs=goal_chat, 
                    outputs=goal_chat
                )
                
                overcome_barriers_btn.click(
                    create_goal_quick_prompt("I face some barriers to career advancement like [limited education/transportation challenges/childcare responsibilities/gaps in employment]. What achievable goals can help me overcome these barriers?"), 
                    inputs=goal_chat, 
                    outputs=goal_chat
                )
                
                # Add event handlers for goal saving
                save_goal_btn.click(
                    save_goal,
                    inputs=[goal_text, goal_job],
                    outputs=[saved_goals_table, goal_instructions, no_goals_message]
                ).then(
                    lambda: "", None, goal_text  # Clear the input after saving
                ).then(
                    check_table_visibility,  # Force check visibility
                    inputs=[],
                    outputs=[saved_goals_table, no_goals_message]
                ).then(
                    lambda: "Goal saved successfully! The goal has been added to your list.", None, debug_output
                )
                
                # Add event handler for clicking a row in the table
                saved_goals_table.select(
                    toggle_goal_in_table,
                    inputs=[saved_goals_table],
                    outputs=[saved_goals_table, goal_instructions, no_goals_message]
                )
                
                # Add the event handler for the debug button
                debug_goals_btn.click(
                    debug_saved_goals,
                    inputs=[],
                    outputs=[debug_output, saved_goals_table, goal_instructions, no_goals_message]
                )
        
        # About section
        with gr.Accordion("About Career Compass", open=False):
            gr.Markdown("""
            # Career Compass User Guide

Career Compass is an AI-powered career development assistant designed to help you discover your strengths, set achievable career goals, and find job opportunities that match your unique abilities. This guide will walk you through each feature of the application.

## Getting Started

Career Compass follows a three-step process to help you navigate your career journey:

1. **Skill Mapping** - Discover your transferable skills and strengths
2. **Job Matching** - Find job opportunities that match your skills and interests
3. **Goal Setting** - Create achievable career development plans

## Step 1: Skill Mapping

The Skill Mapping tab helps you identify your existing skills, including those from informal experiences and transferable abilities.

### How to Use Skill Mapping:

1. **Start a conversation** - Share information about:
   - Work you've done (paid or unpaid)
   - Projects you've completed
   - Problems you've solved
   - Skills you've taught yourself

2. **Review your skills** - After chatting, click the "Review My Skills" button when it appears to see your identified skills.

3. **Select skills to explore** - Choose up to 3 skills you'd like to focus on, then click "Find Jobs Based on Selected Skills".

4. **Explore job suggestions** - Review the suggested job titles that match your selected skills, then click "Explore This Job" to continue to the Job Matching tab.

### Skill Analysis Quick Prompts:

Use these buttons for quick skill insights:
- **Check Market Demand** - Discover how in-demand your skills are
- **How To Improve My Skills** - Get suggestions for skill development
- **Find Remote Work With My Skills** - Explore remote job opportunities

## Step 2: Job Matching

The Job Matching tab helps you find job opportunities that match your skills and interests.

### How to Use Job Matching:

1. **Search for jobs** - Enter:
   - Job title, skills, or keywords
   - Location (optional)
   - Industry (optional)
   - Click "Search Jobs"

2. **Review job results** - Browse the search results displayed in the table.

3. **Save interesting jobs** - Enter the job number from the table and click "Save Selected Job" to add it to your saved jobs list.

4. **Get job advice** - Use the chat to ask questions about specific careers or get job search advice.

*Note: If the API connection fails, sample job data will be used instead.*

## Step 3: Goal Setting

The Goal Setting tab helps you create achievable career goals and build confidence.

### How to Use Goal Setting:

1. **Discuss your career aspirations** - Share your:
   - Career interests
   - Important job factors (schedule, pay, location)
   - Obstacles you've faced
   - Initial steps you could take

2. **Use quick goal prompts** - Click any of these buttons for structured guidance:
   - **Create Achievable Skill-Building Goals**
   - **Develop Step-by-Step Career Plan**
   - **How To Advance In Current Role**
   - **Overcome Career Barriers**

3. **Save your goals** - Use the form to save specific goals:
   - Enter your goal in the text box
   - Optionally link it to a specific job role
   - Click "Save This Goal"

4. **Track goal progress** - Manage your saved goals:
   - View all saved goals in the table
   - Toggle a goal's completion status by entering its ID and clicking "Toggle Completion Status"
   - Goals are marked as ✅ Complete or ❌ Incomplete

## Tips for Getting the Most from Career Compass

1. **Be specific about your experiences** - Include details about your responsibilities, achievements, and challenges.

2. **Share your constraints** - Mention any limitations like schedule restrictions, education barriers, or location requirements.

3. **Ask follow-up questions** - The AI can provide more personalized guidance when you engage in conversation.

4. **Save your progress** - Save jobs and goals to track your career journey over time.

5. **Move between tabs** - You can return to previous tabs to refine your skills or job search at any time.

Career Compass is designed to be supportive and practical, meeting you where you are in your career journey. Remember that this tool is here to guide you, but the ultimate career decisions remain yours to make.
            """)
        
        # Add a tab change event handler
        tabs.select(
            fn=lambda: initialize_goal_setting(),
            inputs=None,
            outputs=goal_chat,
            # This triggers specifically when the Goal Setting tab is selected
            api_name="goal_tab_selected"
        )
    
    return app

# Main application
def main():
    app = build_ui()
    app.launch()

if __name__ == "__main__":
    main()
